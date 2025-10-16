import os


class LLMConfig:
    @staticmethod
    def OPENAI_API_KEY():
        return os.getenv("OPENAI_API_KEY", "")

    @staticmethod
    def OPENAI_MODEL():
        return os.getenv("OPENAI_MODEL", "gpt-4o-mini")  # Fast and capable multilingual model

    @staticmethod
    def OPENAI_MAX_TOKENS():
        return int(os.getenv("OPENAI_MAX_TOKENS", "200"))

    @staticmethod
    def OPENAI_TEMPERATURE():
        return float(os.getenv("OPENAI_TEMPERATURE", "0.7"))

    @staticmethod
    def OPENAI_TIMEOUT():
        return int(os.getenv("OPENAI_TIMEOUT", "15"))  # Reasonable timeout for quality

    @staticmethod
    def LLM_CACHE_ENABLED():
        return os.getenv("LLM_CACHE_ENABLED", "True").lower() == "true"

    @staticmethod
    def LLM_CACHE_TTL():
        return int(os.getenv("LLM_CACHE_TTL", "3600"))  # 1 hour cache

    @staticmethod
    def LLM_CACHE_MAX_SIZE():
        return int(os.getenv("LLM_CACHE_MAX_SIZE", "500"))  # Increased cache size

    @staticmethod
    def LLM_CACHE_MAX_ENTRIES():
        return int(os.getenv("LLM_CACHE_MAX_ENTRIES", "1000"))  # More cache entries

    @staticmethod
    def LLM_MAX_WORKERS():
        return int(os.getenv("LLM_MAX_WORKERS", "5"))

    @staticmethod
    def MAX_CONTEXT_LENGTH():
        return int(os.getenv("MAX_CONTEXT_LENGTH", "2000"))  # Reduced for faster processing

    @staticmethod
    def LLM_HISTORY_LENGTH():
        return int(os.getenv("LLM_HISTORY_LENGTH", "9"))
