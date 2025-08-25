"""
Caching module for performance optimization.
Provides smart caching services for responses and embeddings.
"""

from .cache_service import (
    SmartCacheService,
    get_cache_service,
    clear_cache,
    get_cache_stats
)

__all__ = [
    "SmartCacheService", 
    "get_cache_service", 
    "clear_cache", 
    "get_cache_stats"
]
