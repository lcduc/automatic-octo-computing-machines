import os


class ConfidenceConfig:
    @staticmethod
    def CONFIDENCE_SCORING_ENABLED():
        return os.getenv("CONFIDENCE_SCORING_ENABLED", "True").lower() == "true"

    @staticmethod
    def CONFIDENCE_CONTEXT_WEIGHT():
        return float(os.getenv("CONFIDENCE_CONTEXT_WEIGHT", "0.35"))

    @staticmethod
    def CONFIDENCE_LENGTH_WEIGHT():
        return float(os.getenv("CONFIDENCE_LENGTH_WEIGHT", "0.20"))

    @staticmethod
    def CONFIDENCE_COHERENCE_WEIGHT():
        return float(os.getenv("CONFIDENCE_COHERENCE_WEIGHT", "0.25"))

    @staticmethod
    def CONFIDENCE_CITATION_WEIGHT():
        return float(os.getenv("CONFIDENCE_CITATION_WEIGHT", "0.10"))

    @staticmethod
    def CONFIDENCE_UNCERTAINTY_WEIGHT():
        return float(os.getenv("CONFIDENCE_UNCERTAINTY_WEIGHT", "0.10"))
