import os
from typing import List


class FileConfig:
    @staticmethod
    def MAX_FILE_SIZE():
        return int(os.getenv("MAX_FILE_SIZE", "52428800"))

    @staticmethod
    def ALLOWED_EXTENSIONS():
        return os.getenv(
            "ALLOWED_EXTENSIONS", ".txt,.pdf,.docx,.doc,.csv,.xlsx,.xls"
        ).split(",")

    @staticmethod
    def MAX_FILES_PER_BATCH():
        return int(os.getenv("MAX_FILES_PER_BATCH", "10"))

    @staticmethod
    def MAX_TOTAL_BATCH_SIZE():
        return int(os.getenv("MAX_TOTAL_BATCH_SIZE", "209715200"))

    @staticmethod
    def CHUNKS_DIR():
        return os.getenv("CHUNKS_DIR", "data/chunks")

    @staticmethod
    def VECTORS_DIR():
        return os.getenv("VECTORS_DIR", "data/vectors")

    @staticmethod
    def TEMP_DIR():
        return os.getenv("TEMP_DIR", "data/temp")

    @staticmethod
    def VECTOR_STORE_PATH():
        return os.getenv("VECTOR_STORE_PATH", "data/vectors/vector_store.pkl")

    @staticmethod
    def CHUNK_SIZE():
        return int(os.getenv("CHUNK_SIZE", "1000"))

    @staticmethod
    def CHUNK_OVERLAP():
        return int(os.getenv("CHUNK_OVERLAP", "0"))
