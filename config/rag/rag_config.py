import os


class RAGConfig:
    @staticmethod
    def EMBEDDING_MODEL():
        return os.getenv("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")  # Multilingual support

    @staticmethod
    def RETRIEVAL_TOP_K():
        return int(os.getenv("RETRIEVAL_TOP_K", "3"))  # Reduced for faster processing

    @staticmethod
    def CHUNK_SIZE():
        return int(os.getenv("CHUNK_SIZE", "800"))  # Reduced for faster processing

    @staticmethod
    def CHUNK_OVERLAP():
        return int(os.getenv("CHUNK_OVERLAP", "0"))

    @staticmethod
    def SEMANTIC_WEIGHT():
        return float(os.getenv("SEMANTIC_WEIGHT", "0.7"))  # Better semantic focus

    @staticmethod
    def SIMILARITY_THRESHOLD():
        return float(os.getenv("SIMILARITY_THRESHOLD", "0.5"))  # Lower threshold for more results

    @staticmethod
    def DIVERSITY_THRESHOLD():
        return float(os.getenv("DIVERSITY_THRESHOLD", "0.8"))

    @staticmethod
    def MAX_RETRIEVAL_RESULTS():
        return int(os.getenv("MAX_RETRIEVAL_RESULTS", "3"))  # Further reduced for speed

    @staticmethod
    def EMBEDDING_BATCH_SIZE():
        return int(os.getenv("EMBEDDING_BATCH_SIZE", "32"))  # Batch processing optimization

    @staticmethod
    def USE_FAISS_INDEX():
        return os.getenv("USE_FAISS_INDEX", "True").lower() == "true"  # Enable FAISS by default

    @staticmethod
    def CACHE_EMBEDDINGS():
        return os.getenv("CACHE_EMBEDDINGS", "True").lower() == "true"  # Cache embeddings

    @staticmethod
    def CONTEXT_EXPANSION_ENABLED():
        return os.getenv("CONTEXT_EXPANSION_ENABLED", "True").lower() == "true"

    @staticmethod
    def CONTEXT_EXPANSION_RADIUS():
        return int(os.getenv("CONTEXT_EXPANSION_RADIUS", "1"))

    @staticmethod
    def MIN_CONTEXT_CHUNKS():
        return int(os.getenv("MIN_CONTEXT_CHUNKS", "0"))

    @staticmethod
    def MAX_CONTEXT_CHUNKS():
        return int(os.getenv("MAX_CONTEXT_CHUNKS", "5"))

    @staticmethod
    def RERANKER_MODEL():
        # Fast multilingual reranker for English + Vietnamese support
        return os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")

    @staticmethod
    def QUERY_ADAPTER_PATH():
        return os.getenv("RAG_QUERY_ADAPTER_PATH", os.path.join("data", "vectors", "query_adapter.npy"))

    @staticmethod
    def RERANKER_ENABLED():
        return os.getenv("RERANKER_ENABLED", "True").lower() == "true"  # Enabled for better quality