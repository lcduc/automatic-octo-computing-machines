"""
Infrastructure Domain
Handles caching, performance monitoring, and system infrastructure.
"""

from .caching.cache_service import SmartCacheService, get_cache_service
from .lifecycle import ApplicationLifecycle, StartupBanner

__all__ = [
    "SmartCacheService",
    "get_cache_service",
    "ApplicationLifecycle",
    "StartupBanner",
]
