"""
RAG Context Retriever - Hybrid search combining semantic and keyword-based approaches.
Handles document retrieval and result aggregation for enhanced search accuracy.
"""

from typing import List, Dict, Any, Union, Optional
import numpy as np
import logging
from rank_bm25 import BM25Okapi
from .embeddings import EmbeddingService, get_embedding_service
from core.storage.vector_store_optimized import OptimizedVectorStore
from .similarity import SimilarityCalculator
from .reranker import Reranker
from config.rag.rag_config import RAGConfig
import re
from utils.text_utils import TextUtils

logger = logging.getLogger(__name__)


class ContextRetriever:
    """
    Enhanced context retriever for RAG systems with hybrid search capabilities.
    Combines semantic embeddings and keyword search (BM25) for optimal retrieval.
    """

    def __init__(self, embedding_service=None, similarity_calculator=None):
        # Initialize core components for search and similarity calculation
        if embedding_service is None:
            self.embedding_service = get_embedding_service()
        else:
            self.embedding_service = embedding_service
        
        self.vector_store = OptimizedVectorStore()  # Use optimized vector store with FAISS/HDF5
        if similarity_calculator is None:
            self.similarity_calculator = SimilarityCalculator()
        else:
            self.similarity_calculator = similarity_calculator
        self.reranker = Reranker()

        # Best-effort: load query adapter once at initialization
        try:
            from config.rag.rag_config import RAGConfig
            self.embedding_service.load_query_adapter(RAGConfig.QUERY_ADAPTER_PATH())
        except Exception:
            pass

        # BM25 cache per loaded document corpus
        self._bm25_cache_key = None
        self._bm25_instance = None
        self._tokenized_docs = None

    def _ensure_numpy(self, embedding) -> np.ndarray:
        """Convert various embedding formats to numpy arrays for consistent processing."""
        if isinstance(embedding, list):
            return np.array(embedding)
        if hasattr(embedding, "numpy"):  # Handle PyTorch tensors
            return embedding.numpy()
        return np.array(embedding)

    def _tokenize(self, text: str) -> List[str]:
        """Tokenization for BM25: lowercase, strip punctuation, remove diacritics."""
        if not text:
            return []

        # Lowercase, remove Vietnamese accents, strip punctuation/symbols
        text = TextUtils.strip_vietnamese_accents(text.lower())
        text = re.sub(r"[^\w\s]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text.split()

    def _expand_context_with_adjacent_chunks(
        self, top_indices: List[int], total_documents: int, expansion_radius: int = 1
    ) -> List[int]:
        """
        Expand context by including adjacent chunks around the top results.
        Prioritize expanding the highest-scoring chunk first to ensure its
        neighbors are included within the maximum context cap, then expand
        remaining seeds in descending score order.
        Only include neighbors from the same source document.
        """
        if not RAGConfig.CONTEXT_EXPANSION_ENABLED():
            return top_indices

        # Get document metadata to check if chunks are from the same source
        document_metadata = self.vector_store.get_metadata()
        if not document_metadata or len(document_metadata) != total_documents:
            # Fallback: expand purely by index adjacency if metadata is missing
            logger.warning("⚠️ Document metadata not available, using index-adjacent expansion")
            max_chunks = RAGConfig.MAX_CONTEXT_CHUNKS()
            if max_chunks <= 0:
                return top_indices

            ordered: List[int] = []
            seen = set()

            def add_idx(i: int):
                if 0 <= i < total_documents and i not in seen and len(ordered) < max_chunks:
                    ordered.append(i)
                    seen.add(i)

            for seed in top_indices:
                if len(ordered) >= max_chunks:
                    break
                # Add window [seed - r, ..., seed + r] in ascending order
                start = max(0, seed - expansion_radius)
                end = min(total_documents - 1, seed + expansion_radius)
                for i in range(start, end + 1):
                    add_idx(i)
                    if len(ordered) >= max_chunks:
                        break

            logger.info(
                f"🔍 Context expansion (adjacency fallback): {len(top_indices)} -> {len(ordered)} chunks"
            )
            return ordered

        max_chunks = RAGConfig.MAX_CONTEXT_CHUNKS()
        if max_chunks <= 0:
            return top_indices

        # Maintain insertion order with a list, but guard uniqueness with a set
        ordered: List[int] = []
        seen = set()

        def add_idx(i: int):
            if 0 <= i < total_documents and i not in seen and len(ordered) < max_chunks:
                ordered.append(i)
                seen.add(i)

        # Group chunks by source to find proper adjacency within each source
        source_chunks = {}
        for i, metadata in enumerate(document_metadata):
            source_id = metadata.get("source_id", "unknown")
            if source_id not in source_chunks:
                source_chunks[source_id] = []
            source_chunks[source_id].append(i)

        # For each seed, find its position within its source and expand within that source only
        for seed_pos, seed in enumerate(top_indices):
            if len(ordered) >= max_chunks:
                break
            
            seed_source = document_metadata[seed].get("source_id", "unknown")
            if seed_source not in source_chunks:
                # If source not found, just add the seed itself
                add_idx(seed)
                continue
                
            # Find the seed's position within its source chunks
            source_chunk_indices = source_chunks[seed_source]
            try:
                seed_position_in_source = source_chunk_indices.index(seed)
            except ValueError:
                # Seed not found in source chunks, just add it
                add_idx(seed)
                continue
            
            # Calculate expansion range within the source
            start_in_source = max(0, seed_position_in_source - expansion_radius)
            end_in_source = min(len(source_chunk_indices) - 1, seed_position_in_source + expansion_radius)
            
            # Add chunks from the source in order
            for pos in range(start_in_source, end_in_source + 1):
                chunk_index = source_chunk_indices[pos]
                add_idx(chunk_index)
                if len(ordered) >= max_chunks:
                    break

        logger.info(
            f"🔍 Context expansion: {len(top_indices)} -> {len(ordered)} chunks"
        )
        return ordered

    def _ensure_minimum_context(
        self, results: List[Dict[str, Any]], documents: List[str]
    ) -> List[Dict[str, Any]]:
        """
        Ensure minimum number of context chunks are included for comprehensive responses.
        """
        min_chunks = RAGConfig.MIN_CONTEXT_CHUNKS()

        if len(results) >= min_chunks:
            return results

        logger.info(
            f"📚 Ensuring minimum {min_chunks} context chunks (current: {len(results)})"
        )

        # If we have fewer than minimum chunks, add more from the top results
        if len(documents) > len(results):
            # Get additional chunks that weren't in the top results
            used_indices = {result["index"] for result in results}
            available_indices = [
                i for i in range(len(documents)) if i not in used_indices
            ]

            # Add more chunks up to minimum
            additional_needed = min_chunks - len(results)
            for i in range(min(additional_needed, len(available_indices))):
                idx = available_indices[i]
                results.append(
                    {
                        "document": documents[idx],
                        "semantic_score": 0.0,  # Lower score for additional chunks
                        "keyword_score": 0.0,
                        "combined_score": 0.0,
                        "index": idx,
                    }
                )

        return results

    def hybrid_search(
        self,
        query: str,
        embeddings: np.ndarray,
        documents: List[str],
        k: int = 5,
        semantic_weight: float = 0.7,
    ) -> List[Dict[str, Any]]:
        """
        Perform enhanced hybrid search combining semantic and keyword-based approaches.
        Only returns results above the similarity threshold, even if fewer than k.

        Args:
            query: Search query to process
            embeddings: Document embeddings for semantic similarity
            documents: List of documents to search through
            k: Number of top results to return
            semantic_weight: Weight for semantic search vs keyword search (0-1)

        Returns:
            List of dictionaries containing documents, scores, and metadata
        """
        logger.info(f"🔍 Starting hybrid search for query: '{query[:50]}...'")
        logger.info(f"📊 Search parameters: k={k}, semantic_weight={semantic_weight}")
        logger.info(f"📚 Available documents: {len(documents)}")

        if len(documents) == 0:
            logger.warning("⚠️ No documents available for search")
            return []

        try:
            # No source filtering — search across all documents
            # Use ORIGINAL query (with diacritics) for semantic embedding
            query_embedding = self._ensure_numpy(
                self.embedding_service.encode([query], convert_to_numpy=True)
            )
            try:
                query_embedding = self.embedding_service.apply_query_adapter(query_embedding)
            except Exception:
                pass

            if RAGConfig.USE_FAISS_INDEX() and getattr(self.vector_store, "faiss_index", None) is not None:
                logger.info("Using FAISS for semantic search")
                top_similarities, top_indices = self.vector_store.fast_similarity_search(query_embedding, k)
                # Expand to full-length semantic score vector aligned with documents
                semantic_scores = np.zeros(len(documents), dtype=float)
                # Ensure numeric type and safe assignment
                for sim, idx in zip(top_similarities, top_indices):
                    if 0 <= int(idx) < len(semantic_scores):
                        semantic_scores[int(idx)] = float(sim)
            else:
                semantic_scores = self.similarity_calculator.cosine_similarity(
                    query_embedding, embeddings
                )

            # Keyword search using BM25 with simple in-memory cache
            try:
                cache_key = (len(documents), hash(documents[0]) if documents else 0)
            except Exception:
                cache_key = len(documents)
            if self._bm25_cache_key != cache_key:
                self._tokenized_docs = [self._tokenize(doc) for doc in documents]
                self._bm25_instance = BM25Okapi(self._tokenized_docs)
                self._bm25_cache_key = cache_key
            keyword_scores = self._bm25_instance.get_scores(self._tokenize(query)) if self._bm25_instance else np.zeros(len(documents))

            # Normalize scores to [0, 1] before combining
            norm_semantic_scores = self.similarity_calculator.normalize_similarities(
                semantic_scores
            )
            norm_keyword_scores = self.similarity_calculator.normalize_similarities(
                keyword_scores
            )
            # Combine normalized scores
            combined_scores = (
                semantic_weight * norm_semantic_scores
                + (1 - semantic_weight) * norm_keyword_scores
            )

            # Filter by similarity threshold before selecting top K (use combined score)
            threshold = RAGConfig.SIMILARITY_THRESHOLD()
            filtered_indices = [
                i for i in range(len(documents)) if combined_scores[i] >= threshold
            ]

            # Create results with metadata (store both raw and normalized scores)
            results = []
            for i in filtered_indices:
                results.append(
                    {
                        "document": documents[i],
                        "semantic_score": float(semantic_scores[i]),
                        "keyword_score": float(keyword_scores[i]),
                        "norm_semantic_score": float(norm_semantic_scores[i]),
                        "norm_keyword_score": float(norm_keyword_scores[i]),
                        "combined_score": float(combined_scores[i]),
                        "index": i,
                    }
                )

            # Sort by combined score for initial ranking
            results.sort(key=lambda x: x["combined_score"], reverse=True)
            candidate_multiplier = 4 if RAGConfig.RERANKER_ENABLED() else 1
            prelim_top_k = results[: max(k * candidate_multiplier, k)]

            top_k_results = prelim_top_k[:k]
            if RAGConfig.RERANKER_ENABLED():
                try:
                    top_k_results = self.reranker.rerank(query, prelim_top_k, k)
                except Exception as e:
                    logger.warning(f"⚠️ Reranking failed, using combined scores: {e}")

            # Apply context expansion to include adjacent chunks
            top_indices = [result["index"] for result in top_k_results]
            expanded_indices = self._expand_context_with_adjacent_chunks(
                top_indices, len(documents), RAGConfig.CONTEXT_EXPANSION_RADIUS()
            )

            # Rebuild final results directly from expanded indices order, preserving original scores when available
            expanded_results = []
            index_to_result = {r["index"]: r for r in top_k_results}
            for idx in expanded_indices:
                base = index_to_result.get(idx)
                if base:
                    expanded_results.append(base)
                else:
                    expanded_results.append(
                        {
                            "document": documents[idx],
                            "semantic_score": 0.0,
                            "keyword_score": 0.0,
                            "combined_score": 0.0,
                            "index": idx,
                        }
                    )

            # Ensure minimum context chunks
            final_results = self._ensure_minimum_context(expanded_results, documents)

            logger.info(
                f"🎯 Hybrid search completed: {len(final_results)} results (expanded from {len(top_k_results)})"
            )
            return final_results

        except Exception as e:
            logger.warning(f"⚠️ Hybrid search failed: {e}")
            return []

    def capture_user_feedback(
        self, query: str, relevant_docs: List[str], feedback: bool
    ):
        """Capture user feedback for future improvements."""
        if feedback:
            pass
        else:
            pass

    def debug_retrieval(
        self, query: str, embeddings: np.ndarray, documents: List[str], k: int = 5
    ) -> dict:
        """Debug retrieval process. If used for API, consider using a Pydantic model."""
        # TODO: Refactor to use a Pydantic model if this is exposed as an API response.
        logger.info(f"🔍 Debugging retrieval for query: '{query[:50]}...'")

        if len(documents) == 0:
            return {"error": "No documents available"}

        try:
            # Get semantic scores
            query_embedding = self._ensure_numpy(
                self.embedding_service.encode([query], convert_to_numpy=True)
            )
            semantic_scores = self.similarity_calculator.cosine_similarity(
                query_embedding, embeddings
            )

            # Get keyword scores
            tokenized_docs = [self._tokenize(doc) for doc in documents]
            bm25 = BM25Okapi(tokenized_docs)
            keyword_scores = bm25.get_scores(self._tokenize(query))

            # Normalize scores to [0, 1] before combining
            norm_semantic_scores = self.similarity_calculator.normalize_similarities(
                semantic_scores
            )
            norm_keyword_scores = self.similarity_calculator.normalize_similarities(
                keyword_scores
            )
            # Combine normalized scores
            combined_scores = (
                RAGConfig.SEMANTIC_WEIGHT() * norm_semantic_scores
                + (1 - RAGConfig.SEMANTIC_WEIGHT()) * norm_keyword_scores
            )

            # Filter by similarity threshold before sorting and selecting top K (use combined score)
            threshold = RAGConfig.SIMILARITY_THRESHOLD()
            filtered_indices = [
                i for i in range(len(documents)) if combined_scores[i] >= threshold
            ]

            # Create detailed results (store both raw and normalized scores)
            all_results = []
            for i in filtered_indices:
                all_results.append(
                    {
                        "index": i,
                        "document_preview": documents[i][:100].replace("\n", " "),
                        "semantic_score": float(semantic_scores[i]),
                        "keyword_score": float(keyword_scores[i]),
                        "norm_semantic_score": float(norm_semantic_scores[i]),
                        "norm_keyword_score": float(norm_keyword_scores[i]),
                        "combined_score": float(combined_scores[i]),
                        "above_threshold": float(combined_scores[i])
                        >= RAGConfig.SIMILARITY_THRESHOLD(),
                    }
                )

            # Sort by combined score for ranking
            all_results.sort(key=lambda x: x["combined_score"], reverse=True)
            # Get top k results (or fewer if not enough above threshold)
            top_k_results = all_results[:k]

            # Apply context expansion
            top_indices = [result["index"] for result in top_k_results]
            if isinstance(top_indices, np.ndarray):
                top_indices = top_indices.tolist()

            expanded_indices = self._expand_context_with_adjacent_chunks(
                top_indices, len(documents), RAGConfig.CONTEXT_EXPANSION_RADIUS()
            )

            # Get final results with expansion
            final_results = []
            for idx in expanded_indices:
                result = next((r for r in all_results if r["index"] == idx), None)
                if result:
                    final_results.append(result)

            return {
                "query": query,
                "total_documents": len(documents),
                "top_k_original": k,
                "final_chunks_retrieved": len(final_results),
                "threshold": RAGConfig.SIMILARITY_THRESHOLD(),
                "context_expansion_enabled": RAGConfig.CONTEXT_EXPANSION_ENABLED(),
                "expansion_radius": RAGConfig.CONTEXT_EXPANSION_RADIUS(),
                "all_scores": all_results,
                "top_k_results": top_k_results,
                "final_results": final_results,
                "expanded_indices": expanded_indices,
            }

        except Exception as e:
            logger.error(f"❌ Debug retrieval failed: {e}")
            return {"error": str(e)}
