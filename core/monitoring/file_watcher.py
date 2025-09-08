"""
File system watcher for automatic application updates when data changes.
Monitors key directories and triggers appropriate updates (vector store rebuild, cache refresh, etc.).
"""

import os
import time
import logging
import asyncio
from pathlib import Path
from typing import Dict, List, Callable, Optional, Set
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent, FileDeletedEvent, FileMovedEvent

logger = logging.getLogger(__name__)


class DataChangeHandler(FileSystemEventHandler):
    """
    Handles file system events for data directories.
    Triggers appropriate updates based on the type of change detected.
    """
    
    def __init__(self, update_callbacks: Dict[str, Callable]):
        """
        Initialize the handler with update callbacks.
        
        Args:
            update_callbacks: Dictionary mapping directory patterns to callback functions
        """
        self.update_callbacks = update_callbacks
        self.last_triggered = {}  # Track last trigger time to avoid spam
        self.debounce_delay = 10.0  # Increased to 10 seconds to reduce spam
        self.auto_reload_enabled = True  # Can be disabled
        self.ignored_extensions = {'.tmp', '.temp', '.swp', '.lock', '.log'}  # Ignore temp files
        self.ignored_patterns = {'__pycache__', '.git', '.vscode', '.idea'}  # Ignore system dirs
        
    def _should_ignore_file(self, file_path: str) -> bool:
        """Check if file should be ignored based on extension or path patterns."""
        file_path_lower = file_path.lower()
        
        # Check file extension
        for ext in self.ignored_extensions:
            if file_path_lower.endswith(ext):
                return True
        
        # Check path patterns
        for pattern in self.ignored_patterns:
            if pattern in file_path_lower:
                return True
        
        return False
    
    def _should_trigger_update(self, directory: str, file_path: str) -> bool:
        """Check if update should be triggered based on various conditions."""
        # Check if auto-reload is disabled
        if not self.auto_reload_enabled:
            logger.debug(f"⏸️ Auto-reload disabled, skipping update for {directory}")
            return False
        
        # Check if file should be ignored
        if self._should_ignore_file(file_path):
            logger.debug(f"🚫 Ignoring file {file_path} (temp/system file)")
            return False
        
        # Check debounce timing
        now = time.time()
        last_time = self.last_triggered.get(directory, 0)
        if (now - last_time) < self.debounce_delay:
            logger.debug(f"⏳ Skipping update for {directory} (debounced)")
            return False
        
        return True
    
    def _trigger_update(self, directory: str, event_type: str, file_path: str):
        """Trigger the appropriate update callback for the directory."""
        if not self._should_trigger_update(directory, file_path):
            return
            
        self.last_triggered[directory] = time.time()
        
        # Find the appropriate callback
        callback = None
        for pattern, cb in self.update_callbacks.items():
            if pattern in directory or directory.endswith(pattern):
                callback = cb
                break
        
        if callback:
            logger.info(f"🔄 Triggering update for {directory} (event: {event_type}, file: {os.path.basename(file_path)})")
            try:
                # Run callback in a separate task to avoid blocking
                asyncio.create_task(callback(directory, event_type, file_path))
            except Exception as e:
                logger.error(f"❌ Error in update callback for {directory}: {e}")
        else:
            logger.warning(f"⚠️ No callback found for directory: {directory}")
    
    def enable_auto_reload(self):
        """Enable automatic reloading."""
        self.auto_reload_enabled = True
        logger.info("✅ Auto-reload enabled")
    
    def disable_auto_reload(self):
        """Disable automatic reloading."""
        self.auto_reload_enabled = False
        logger.info("⏸️ Auto-reload disabled")
    
    def set_debounce_delay(self, delay: float):
        """Set the debounce delay in seconds."""
        self.debounce_delay = delay
        logger.info(f"⏱️ Debounce delay set to {delay} seconds")
    
    def on_created(self, event):
        if not event.is_directory:
            self._trigger_update(os.path.dirname(event.src_path), "created", event.src_path)
    
    def on_modified(self, event):
        if not event.is_directory:
            self._trigger_update(os.path.dirname(event.src_path), "modified", event.src_path)
    
    def on_deleted(self, event):
        if not event.is_directory:
            self._trigger_update(os.path.dirname(event.src_path), "deleted", event.src_path)
    
    def on_moved(self, event):
        if not event.is_directory:
            self._trigger_update(os.path.dirname(event.dest_path), "moved", event.dest_path)


class FileWatcher:
    """
    Main file watcher that monitors key directories for changes.
    Automatically triggers updates when data files are modified.
    """
    
    def __init__(self, watch_directories: List[str]):
        """
        Initialize the file watcher.
        
        Args:
            watch_directories: List of directories to monitor
        """
        self.watch_directories = watch_directories
        self.observer = Observer()
        self.handler = None
        self.is_running = False
        
    def setup_callbacks(self, update_callbacks: Dict[str, Callable]):
        """Setup update callbacks for different directory patterns."""
        self.handler = DataChangeHandler(update_callbacks)
        
    def start_watching(self):
        """Start monitoring the directories."""
        if not self.handler:
            raise ValueError("Callbacks must be setup before starting to watch")
            
        for directory in self.watch_directories:
            if os.path.exists(directory):
                self.observer.schedule(self.handler, directory, recursive=True)
                logger.info(f"👀 Watching directory: {directory}")
            else:
                logger.warning(f"⚠️ Directory does not exist: {directory}")
        
        self.observer.start()
        self.is_running = True
        logger.info("🚀 File watcher started")
        
    def stop_watching(self):
        """Stop monitoring the directories."""
        if self.is_running:
            self.observer.stop()
            self.observer.join()
            self.is_running = False
            logger.info("🛑 File watcher stopped")
    
    def is_alive(self) -> bool:
        """Check if the watcher is still running."""
        return self.is_running and self.observer.is_alive()


class AutoReloadManager:
    """
    Manages automatic reloading of the application when data changes.
    Coordinates file watching with application updates.
    """
    
    def __init__(self):
        self.file_watcher = None
        self.vector_store = None
        self.cache_service = None
        # Load auto-reload settings from config
        from config.server.server_config import ServerConfig
        self.auto_reload_enabled = ServerConfig.AUTO_RELOAD_ENABLED()
        self.default_debounce_delay = ServerConfig.AUTO_RELOAD_DEBOUNCE_DELAY()
        
    def setup_vector_store(self, vector_store):
        """Setup vector store reference for auto-rebuild."""
        self.vector_store = vector_store
        
    def setup_cache_service(self, cache_service):
        """Setup cache service reference for auto-refresh."""
        self.cache_service = cache_service
        
    async def on_chunks_changed(self, directory: str, event_type: str, file_path: str):
        """Handle changes to document chunks - rebuild vector store."""
        logger.info(f"📄 Chunks changed in {directory}, rebuilding vector store...")
        
        if self.vector_store:
            try:
                # Rebuild vector store with new chunks
                await asyncio.get_event_loop().run_in_executor(
                    None, self.vector_store.rebuild_vector_store
                )
                logger.info("✅ Vector store rebuilt successfully")
            except Exception as e:
                logger.error(f"❌ Failed to rebuild vector store: {e}")
        else:
            logger.warning("⚠️ Vector store not available for rebuild")
    
    async def on_vectors_changed(self, directory: str, event_type: str, file_path: str):
        """Handle changes to vector store files - refresh cache."""
        logger.info(f"🔢 Vectors changed in {directory}, refreshing cache...")
        
        if self.cache_service:
            try:
                # Clear relevant caches
                await self.cache_service.clear_vector_cache()
                logger.info("✅ Vector cache refreshed")
            except Exception as e:
                logger.error(f"❌ Failed to refresh vector cache: {e}")
        else:
            logger.warning("⚠️ Cache service not available for refresh")
    
    async def on_wordnet_changed(self, directory: str, event_type: str, file_path: str):
        """Handle changes to Vietnamese wordnet data - refresh cache."""
        logger.info(f"🇻🇳 Wordnet changed in {directory}, refreshing cache...")
        
        if self.cache_service:
            try:
                # Clear wordnet cache
                await self.cache_service.clear_wordnet_cache()
                logger.info("✅ Wordnet cache refreshed")
            except Exception as e:
                logger.error(f"❌ Failed to refresh wordnet cache: {e}")
        else:
            logger.warning("⚠️ Cache service not available for wordnet refresh")
    
    def start_auto_reload(self, base_data_dir: str = "data"):
        """Start the auto-reload system."""
        # Define watch directories
        watch_dirs = [
            os.path.join(base_data_dir, "chunks"),
            os.path.join(base_data_dir, "vectors"),
            os.path.join(base_data_dir, "vietwordnet"),
        ]
        
        # Setup callbacks
        callbacks = {
            "chunks": self.on_chunks_changed,
            "vectors": self.on_vectors_changed,
            "vietwordnet": self.on_wordnet_changed,
        }
        
        # Initialize and start file watcher
        self.file_watcher = FileWatcher(watch_dirs)
        self.file_watcher.setup_callbacks(callbacks)
        
        # Set initial auto-reload state and debounce delay
        if self.file_watcher.handler:
            self.file_watcher.handler.auto_reload_enabled = self.auto_reload_enabled
            self.file_watcher.handler.debounce_delay = self.default_debounce_delay
        
        self.file_watcher.start_watching()
        
        if self.auto_reload_enabled:
            logger.info("🔄 Auto-reload system started (enabled)")
        else:
            logger.info("🔄 Auto-reload system started (disabled by default - use enable_auto_reload() to activate)")
    
    def stop_auto_reload(self):
        """Stop the auto-reload system."""
        if self.file_watcher:
            self.file_watcher.stop_watching()
            logger.info("🛑 Auto-reload system stopped")
    
    def enable_auto_reload(self):
        """Enable automatic reloading."""
        self.auto_reload_enabled = True
        if self.file_watcher and self.file_watcher.handler:
            self.file_watcher.handler.enable_auto_reload()
        logger.info("✅ Auto-reload enabled")
    
    def disable_auto_reload(self):
        """Disable automatic reloading."""
        self.auto_reload_enabled = False
        if self.file_watcher and self.file_watcher.handler:
            self.file_watcher.handler.disable_auto_reload()
        logger.info("⏸️ Auto-reload disabled")
    
    def set_debounce_delay(self, delay: float):
        """Set the debounce delay in seconds."""
        if self.file_watcher and self.file_watcher.handler:
            self.file_watcher.handler.set_debounce_delay(delay)
        logger.info(f"⏱️ Debounce delay set to {delay} seconds")
    
    def manual_rebuild_vector_store(self):
        """Manually trigger vector store rebuild."""
        logger.info("🔧 Manual vector store rebuild requested")
        if self.vector_store:
            try:
                # Run in executor to avoid blocking
                import asyncio
                loop = asyncio.get_event_loop()
                loop.run_in_executor(None, self.vector_store.rebuild_vector_store)
                logger.info("✅ Manual vector store rebuild completed")
            except Exception as e:
                logger.error(f"❌ Manual vector store rebuild failed: {e}")
        else:
            logger.warning("⚠️ Vector store not available for manual rebuild")
    
    def manual_refresh_cache(self):
        """Manually refresh all caches."""
        logger.info("🔧 Manual cache refresh requested")
        if self.cache_service:
            try:
                import asyncio
                loop = asyncio.get_event_loop()
                loop.run_in_executor(None, self.cache_service.clear_all_caches)
                logger.info("✅ Manual cache refresh completed")
            except Exception as e:
                logger.error(f"❌ Manual cache refresh failed: {e}")
        else:
            logger.warning("⚠️ Cache service not available for manual refresh")
    
    def get_status(self) -> dict:
        """Get current auto-reload status."""
        return {
            "auto_reload_enabled": self.auto_reload_enabled,
            "file_watcher_running": self.file_watcher.is_running if self.file_watcher else False,
            "debounce_delay": self.file_watcher.handler.debounce_delay if self.file_watcher and self.file_watcher.handler else 0,
            "vector_store_available": self.vector_store is not None,
            "cache_service_available": self.cache_service is not None,
        }


# Global instance for easy access
auto_reload_manager = AutoReloadManager()
