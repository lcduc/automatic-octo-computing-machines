import os


class HealthConfig:
    @staticmethod
    def SERVICE_SUCCESS_RATE_THRESHOLD():
        return float(os.getenv("SERVICE_SUCCESS_RATE_THRESHOLD", "80.0"))

    @staticmethod
    def SERVICE_MIN_REQUESTS_FOR_HEALTH():
        return int(os.getenv("SERVICE_MIN_REQUESTS_FOR_HEALTH", "10"))

    @staticmethod
    def HEALTH_CHECK_INTERVAL():
        return int(os.getenv("HEALTH_CHECK_INTERVAL", "30"))

    @staticmethod
    def HEALTH_CHECK_TIMEOUT():
        return int(os.getenv("HEALTH_CHECK_TIMEOUT", "30"))

    @staticmethod
    def HEALTH_CHECK_START_PERIOD():
        return int(os.getenv("HEALTH_CHECK_START_PERIOD", "5"))

    @staticmethod
    def HEALTH_CHECK_RETRIES():
        return int(os.getenv("HEALTH_CHECK_RETRIES", "3"))
