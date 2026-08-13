"""
Infrastructure Domain
Handles caching, performance monitoring, and system infrastructure.
"""

from .audit_trail_service import AuditTrailService, get_audit_trail_service
from .cache_service import SmartCacheService, get_cache_service
from .lifecycle import ApplicationLifecycle, StartupBanner

__all__ = [
    "AuditTrailService",
    "get_audit_trail_service",
    "SmartCacheService",
    "get_cache_service",
    "ApplicationLifecycle",
    "StartupBanner",
]
