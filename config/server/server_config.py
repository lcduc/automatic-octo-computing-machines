import os
from typing import List


class ServerConfig:
    @staticmethod
    def HOST():
        return os.getenv("HOST", "0.0.0.0")

    @staticmethod
    def PORT():
        return int(os.getenv("PORT", "8500"))

    @staticmethod
    def DEBUG():
        return os.getenv("DEBUG", "False").lower() == "true"

    @staticmethod
    def RELOAD():
        return os.getenv("RELOAD", "False").lower() == "true"

    @staticmethod
    def CORS_ORIGINS():
        return os.getenv("CORS_ORIGINS", "*").split(",")

    @staticmethod
    def CORS_ALLOW_CREDENTIALS():
        return os.getenv("CORS_ALLOW_CREDENTIALS", "True").lower() == "true"

    @staticmethod
    def UVICORN_WORKERS():
        return int(os.getenv("UVICORN_WORKERS", "1"))
    
    @staticmethod
    def AUTO_RELOAD_ENABLED():
        """Enable automatic reloading of data when files change."""
        return os.getenv("AUTO_RELOAD_ENABLED", "False").lower() == "true"
    
    @staticmethod
    def AUTO_RELOAD_DEBOUNCE_DELAY():
        """Debounce delay in seconds for auto-reload to prevent spam."""
        return float(os.getenv("AUTO_RELOAD_DEBOUNCE_DELAY", "10.0"))