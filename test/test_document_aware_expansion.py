#!/usr/bin/env python3
"""
Test Document-Aware Context Expansion

This script tests the improved context expansion that only includes neighboring chunks
if they're from the same document.
"""

import os
import sys
import logging
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Configure logging to show debug messages
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import project modules
from core.rag.retriever import ContextRetriever
from core.storage.vector_store_optimized import OptimizedVectorStore


def test_document_aware_expansion():
    """Test the document-aware context expansion feature."""
    print("🧪 Testing Document-Aware Context Expansion")
    print("=" * 60)
    
    # Initialize components
    retriever = ContextRetriever()
    vector_store = OptimizedVectorStore()
    
    # Load vector store
    print("📚 Loading vector store...")
    faiss_index, embeddings, documents = vector_store.load_vector_store()
    
    if documents is None or len(documents) == 0:
        print("❌ No documents found in vector store!")
        return
    
    print(f"✅ Loaded {len(documents)} documents")
    
    # Get document metadata
    metadata = vector_store.get_metadata()
    if metadata:
        print(f"📋 Document metadata available: {len(metadata)} entries")
        
        # Show document sources
        sources = {}
        for i, meta in enumerate(metadata):
            source = meta.get("source_id", "unknown")
            if source not in sources:
                sources[source] = []
            sources[source].append(i)
        
        print("📁 Document sources:")
        for source, indices in sources.items():
            print(f"   - {source}: chunks {min(indices)}-{max(indices)} ({len(indices)} chunks)")
    else:
        print("⚠️ No document metadata available")
    
    print()
    
    # Test with a query that should find relevant chunks
    test_query = "ban bien tap co nhung ai"
    print(f"🔍 Testing with query: '{test_query}'")
    print("-" * 40)
    
    # Perform hybrid search
    results = retriever.hybrid_search(
        query=test_query,
        embeddings=embeddings,
        documents=documents,
        k=3,
        semantic_weight=0.6
    )
    
    print(f"📊 Found {len(results)} results:")
    print()
    
    for i, result in enumerate(results, 1):
        chunk_idx = result['index']
        source = metadata[chunk_idx].get("source_id", "unknown") if metadata else "unknown"
        
        print(f"🏆 Result #{i}")
        print(f"   📄 Chunk Index: {chunk_idx}")
        print(f"   📁 Document Source: {source}")
        print(f"   🎯 Combined Score: {result['combined_score']:.4f}")
        print(f"   🧠 Semantic Score: {result['semantic_score']:.4f}")
        print(f"   🔤 Keyword Score: {result['keyword_score']:.4f}")
        print(f"   📏 Length: {len(result['document'])} chars")
        print(f"   📝 Preview: {result['document'][:100]}...")
        print()
    
    # Check if context expansion worked correctly
    print("🔍 Context Expansion Analysis:")
    print("-" * 40)
    
    if len(results) > 3:  # More than the requested k=3
        print("✅ Context expansion occurred")
        
        # Check if expanded chunks are from the same document
        if metadata:
            source_groups = {}
            for result in results:
                chunk_idx = result['index']
                source = metadata[chunk_idx].get("source_id", "unknown")
                if source not in source_groups:
                    source_groups[source] = []
                source_groups[source].append(chunk_idx)
            
            print("📁 Chunks grouped by document:")
            for source, indices in source_groups.items():
                indices.sort()
                print(f"   - {source}: {indices}")
                
                # Check if indices are consecutive (good sign for same document)
                if len(indices) > 1:
                    consecutive = all(indices[i] == indices[i-1] + 1 for i in range(1, len(indices)))
                    if consecutive:
                        print(f"     ✅ Consecutive chunks from same document")
                    else:
                        print(f"     ⚠️ Non-consecutive chunks (might be from different parts)")
    else:
        print("ℹ️ No context expansion occurred (only top-k results returned)")
    
    print()
    print("🎯 Test completed!")


if __name__ == "__main__":
    try:
        test_document_aware_expansion()
    except KeyboardInterrupt:
        print("\n👋 Interrupted by user. Goodbye!")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        logger.exception("Unexpected error in document-aware expansion test")
