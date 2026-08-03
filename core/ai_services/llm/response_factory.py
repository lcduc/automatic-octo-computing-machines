"""
Builders for the chat payloads returned by ``ChatbotService``.

The confidence and search-metadata blocks used to be copy-pasted at every return
site; centralising them here keeps the wire format consistent and makes a change
to the response shape a one-line edit.
"""

# Standard library imports
from typing import Any, Dict, List, Optional

# Local imports
from models.responses import ChatResponse, StatusEnum

#: Number of top-scoring chunks reported back to the caller.
TOP_SCORE_SAMPLE_SIZE = 3


class ChatResponseFactory:
    """Assembles confidence/search metadata and the response objects around it."""

    def __init__(self, confidence_scorer):
        """
        Args:
            confidence_scorer: Scorer exposing ``get_confidence_level(score)``.
        """
        self._confidence_scorer = confidence_scorer

    def confidence_details(self, confidence) -> Dict[str, Any]:
        """Flatten a confidence result into its per-signal detail dict."""
        return {
            "context_alignment": confidence.context_alignment,
            "response_length_appropriateness": confidence.response_length_appropriateness,
            "semantic_coherence": confidence.semantic_coherence,
            "source_citation": confidence.source_citation,
            "uncertainty_indicators": confidence.uncertainty_indicators,
            "reasoning": confidence.reasoning,
        }

    def confidence_payload(self, confidence) -> Dict[str, Any]:
        """Build the ``{score, level, details}`` block used by ``ChatResponse``."""
        return {
            "score": confidence.overall_score,
            "level": self._confidence_scorer.get_confidence_level(confidence.overall_score),
            "details": self.confidence_details(confidence),
        }

    @staticmethod
    def top_scores(search_results: Optional[List[Dict[str, Any]]]) -> List[float]:
        """Extract the highest combined scores from the retrieved chunks."""
        results = search_results or []
        return [
            result.get("combined_score", 0)
            for result in results[:TOP_SCORE_SAMPLE_SIZE]
            if result.get("combined_score", 0) > 0
        ]

    def search_metadata(
        self,
        search_results: Optional[List[Dict[str, Any]]],
        cached: bool,
    ) -> Dict[str, Any]:
        """Build the search metadata block for a ``ChatResponse``."""
        return {
            "results_count": len(search_results or []),
            "top_scores": self.top_scores(search_results),
            "cached_response": cached,
        }

    def chat_response(
        self,
        query: str,
        response_text: str,
        confidence,
        search_results: Optional[List[Dict[str, Any]]],
        cached: bool,
    ) -> ChatResponse:
        """Build the pydantic ``ChatResponse`` returned by the query-only path."""
        return ChatResponse(
            status=StatusEnum.SUCCESS,
            message="Response generated successfully",
            response=response_text,
            query=query,
            confidence=self.confidence_payload(confidence),
            search_metadata=self.search_metadata(search_results, cached),
        )

    def history_payload(
        self,
        response_text: str,
        confidence,
        search_results: Optional[List[Dict[str, Any]]],
        cached: bool,
    ) -> Dict[str, Any]:
        """
        Build the dict payload used by the history-aware path.

        Kept as a plain dict because ``ChatService`` consumes these keys
        directly when assembling its own ``BaseResponse``.
        """
        return {
            "response": response_text,
            "confidence": confidence.overall_score,
            "confidence_level": self._confidence_scorer.get_confidence_level(
                confidence.overall_score
            ),
            "confidence_details": self.confidence_details(confidence),
            "search_results": {
                "count": len(search_results or []),
                "top_scores": self.top_scores(search_results),
            },
            "success": True,
            "cached": cached,
        }

    @staticmethod
    def history_error_payload(error_message: str) -> Dict[str, Any]:
        """Build the failure counterpart of :meth:`history_payload`."""
        return {
            "response": error_message,
            "confidence": 0.0,
            "confidence_level": "Low",
            "confidence_details": {},
            "search_results": {"count": 0, "top_scores": []},
            "success": False,
            "cached": False,
        }
