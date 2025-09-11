import os


class URLConfig:
    @staticmethod
    def URL_CHUNK_SIZE():
        return int(os.getenv("URL_CHUNK_SIZE", "1500"))

    @staticmethod
    def URL_CHUNK_OVERLAP():
        return int(os.getenv("URL_CHUNK_OVERLAP", "0"))

    @staticmethod
    def URL_MIN_CHUNK_SIZE():
        return int(os.getenv("URL_MIN_CHUNK_SIZE", "100"))

    @staticmethod
    def CRAWL_TIMEOUT():
        return int(os.getenv("CRAWL_TIMEOUT", "30"))

    @staticmethod
    def CRAWL_MAX_PAGES():
        return int(os.getenv("CRAWL_MAX_PAGES", "10"))

    @staticmethod
    def CRAWL_MAX_DEPTH():
        return int(os.getenv("CRAWL_MAX_DEPTH", "2"))

    @staticmethod
    def CRAWL_DELAY():
        return float(os.getenv("CRAWL_DELAY", "1.0"))

    @staticmethod
    def CRAWL_MAX_CONTENT_LENGTH():
        return int(os.getenv("CRAWL_MAX_CONTENT_LENGTH", "10485760"))
