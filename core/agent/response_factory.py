"""
Builders for the chat payloads returned by ``ChatbotService``.

Every response shape — the pydantic ``ChatResponse``, the plain-dict history
payload, and the streaming SSE events — is assembled here so the wire format
(an ``{"answer": {...}, "citations": [...]}`` envelope) is defined in exactly
one place instead of being copy-pasted at every return site.
"""

# Standard library imports
from typing import Any, Dict, List, Optional

# Local imports
from models.responses import ChatResponse, StatusEnum


class ChatResponseFactory:
    """Assembles the answer/citations envelope and the response objects around it."""

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
        """Build the ``{score, level, details}`` block used by ``answer.confidence``."""
        return {
            "score": confidence.overall_score,
            "level": self._confidence_scorer.get_confidence_level(confidence.overall_score),
            "details": self.confidence_details(confidence),
        }

    def answer_payload(self, response_text: str, confidence, cached: bool) -> Dict[str, Any]:
        """Build the ``answer`` block shared by every response shape."""
        return {
            "text": response_text,
            "confidence": self.confidence_payload(confidence),
            "cached": cached,
        }

    @staticmethod
    def citations(search_results: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """
        Distinct sources behind the answer, highest-scoring first.

        One entry per source (deduplicated by ``source_id``), keeping that
        source's best-scoring retrieved chunk.
        """
        best_by_source: Dict[str, Dict[str, Any]] = {}
        for result in search_results or []:
            source_id = result.get("source_id", "unknown")
            score = result.get("combined_score", 0)
            existing = best_by_source.get(source_id)
            if existing is None or score > existing["score"]:
                best_by_source[source_id] = {
                    "source": result.get("source_name", source_id),
                    "type": result.get("source_type", "unknown"),
                    "score": round(score, 3),
                }
        return sorted(best_by_source.values(), key=lambda c: c["score"], reverse=True)

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
            query=query,
            answer=self.answer_payload(response_text, confidence, cached),
            citations=self.citations(search_results),
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
            "answer": self.answer_payload(response_text, confidence, cached),
            "citations": self.citations(search_results),
            "success": True,
        }

    @staticmethod
    def history_error_payload(error_message: str) -> Dict[str, Any]:
        """Build the failure counterpart of :meth:`history_payload`."""
        return {
            "answer": None,
            "citations": [],
            "success": False,
            "error": error_message,
        }

    @staticmethod
    def stream_delta_event(text: str) -> Dict[str, Any]:
        """Build one incremental ``delta`` SSE event carrying an answer text chunk."""
        return {"type": "delta", "answer": {"text": text}}

    def stream_final_event(
        self,
        response_text: str,
        confidence,
        search_results: Optional[List[Dict[str, Any]]],
        cached: bool,
    ) -> Dict[str, Any]:
        """
        Build the terminal ``final`` SSE event.

        Carries confidence and citations for the turn; ``answer.text`` is left
        blank since the full text was already delivered via ``delta`` events.
        """
        payload = self.answer_payload(response_text, confidence, cached)
        payload["text"] = ""
        return {"type": "final", "answer": payload, "citations": self.citations(search_results)}

    @staticmethod
    def stream_error_event(message: str) -> Dict[str, Any]:
        """Build the ``error`` SSE event for a failed turn."""
        return {"type": "error", "message": message}
