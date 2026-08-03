"""
Background task utilities for performance optimization.
Handles cache warming, cleanup, and maintenance tasks.
"""

import asyncio
import logging
import time
from typing import Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor
import gc

logger = logging.getLogger(__name__)


class BackgroundTaskManager:
    """
    Manages background tasks for performance optimization.
    Handles cache warming, cleanup, and maintenance.
    """
    
    #: Loop intervals in seconds.
    METRICS_SAMPLE_INTERVAL = 30
    MEMORY_CLEANUP_INTERVAL = 600

    def __init__(self, max_workers: int = 2):
        """Initialize the background task manager."""
        self.max_workers = max_workers
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.tasks = {}
        self.running = False
        self._loops: list = []

    async def start(self):
        """Start background task processing."""
        if self.running:
            logger.debug("Background task manager already running")
            return
        self.running = True
        logger.info("Background task manager started")

        self._loops = [
            asyncio.create_task(self._metrics_sampling_loop()),
            asyncio.create_task(self._cleanup_loop()),
        ]

    async def stop(self):
        """Stop background task processing and cancel running loops."""
        self.running = False
        for task in self._loops:
            task.cancel()
        self._loops = []
        self.executor.shutdown(wait=True)
        logger.info("Background task manager stopped")

    async def _metrics_sampling_loop(self):
        """
        Periodically sample CPU/memory into the performance monitor.

        Sampling lives here rather than in the request path so that the
        non-blocking psutil reading has a stable interval to measure against.
        """
        from .monitor import get_performance_monitor

        monitor = get_performance_monitor()
        while self.running:
            try:
                await asyncio.sleep(self.METRICS_SAMPLE_INTERVAL)
                if self.running:
                    monitor.record_system_metrics()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error in metrics sampling loop")

    async def _cleanup_loop(self):
        """Periodically clean up memory and caches."""
        while self.running:
            try:
                await asyncio.sleep(self.MEMORY_CLEANUP_INTERVAL)
                if self.running:
                    await self._cleanup_memory()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error in cleanup loop")

    async def _cleanup_memory(self):
        """Clean up memory and optimize caches."""
        try:
            collected = gc.collect()
            logger.debug("Garbage collection freed %d objects", collected)
        except Exception:
            logger.exception("Error during memory cleanup")


    def submit_task(self, task_name: str, func, *args, **kwargs):
        """Submit a background task for execution."""
        if task_name in self.tasks:
            logger.warning(f"Task {task_name} already running")
            return
            
        future = self.executor.submit(func, *args, **kwargs)
        self.tasks[task_name] = future
        
        # Clean up completed tasks
        def cleanup_task(fut):
            if task_name in self.tasks:
                del self.tasks[task_name]
                
        future.add_done_callback(cleanup_task)
        
    def get_status(self) -> Dict[str, Any]:
        """Get status of background tasks."""
        return {
            "running": self.running,
            "active_tasks": len(self.tasks),
            "max_workers": self.max_workers,
            "task_names": list(self.tasks.keys())
        }


# Global background task manager instance
_background_manager: Optional[BackgroundTaskManager] = None


def get_background_manager() -> BackgroundTaskManager:
    """Get the global background task manager instance."""
    global _background_manager
    if _background_manager is None:
        _background_manager = BackgroundTaskManager()
    return _background_manager


async def start_background_tasks():
    """Start all background tasks."""
    manager = get_background_manager()
    await manager.start()


async def stop_background_tasks():
    """Stop all background tasks."""
    manager = get_background_manager()
    await manager.stop()
