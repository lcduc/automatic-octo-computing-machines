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
    
    # Auto-reload functionality removed