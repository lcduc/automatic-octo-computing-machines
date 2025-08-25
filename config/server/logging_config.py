import os


class LoggingConfig:
    @staticmethod
    def LOG_LEVEL():
        return os.getenv("LOG_LEVEL", "INFO")

    @staticmethod
    def LOG_TO_FILE():
        return os.getenv("LOG_TO_FILE", "True").lower() == "true"

    @staticmethod
    def LOG_DIR():
        return os.getenv("LOG_DIR", "data/logs")

    @staticmethod
    def LOG_MAX_SIZE():
        return int(os.getenv("LOG_MAX_SIZE", "10485760"))

    @staticmethod
    def LOG_BACKUP_COUNT():
        return int(os.getenv("LOG_BACKUP_COUNT", "5"))
