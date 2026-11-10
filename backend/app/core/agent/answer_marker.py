"""
Spots the "no answer" marker at the start of a streamed reply, before any of it reaches the visitor.

The model is told to write only ``[NO_ANSWER]`` when the documents do not answer the question. The
first few characters of the stream are held back until they can no longer become the marker; a real
answer is then released unchanged, a marker is swallowed and the turn becomes a handoff.
"""

# Local imports
from .prompts import SystemPrompts


class NoAnswerFilter:
    """Feeds streamed text through and says whether the reply turned out to be the marker."""

    def __init__(self, marker: str = SystemPrompts.NO_ANSWER_MARKER):
        """
        Args:
            marker: The text a reply consists of when the model has no answer.
        """
        self._marker = marker
        self._held = ""
        self._decided = False
        #: True once the reply is known to start with the marker.
        self.no_answer = False

    def feed(self, text: str) -> str:
        """
        Take the next piece of the stream.

        Returns:
            The text to show now: nothing while undecided or after a marker, else the held text and this piece.
        """
        if self._decided:
            return "" if self.no_answer else text
        self._held += text
        start = self._held.lstrip()
        if len(start) < len(self._marker) and self._marker.startswith(start):
            return ""  # could still become the marker
        self._decided = True
        self.no_answer = start.startswith(self._marker)
        released, self._held = ("" if self.no_answer else self._held), ""
        return released

    def finish(self) -> str:
        """Release what is still held when the stream ends (a short reply that began like the marker)."""
        released, self._held = self._held, ""
        self._decided = True
        return released
