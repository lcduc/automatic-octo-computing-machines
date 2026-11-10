"""
Pick a relevance threshold that separates answerable from unanswerable questions.

A chat turn is answered only when some chunk clears the threshold, so a good
threshold lets the right document through for questions the knowledge base
covers and lets nothing through for questions it does not.
"""

import math
from dataclasses import dataclass
from typing import List, Sequence


@dataclass(frozen=True)
class ThresholdRates:
    """How one threshold treats a labelled question set."""

    threshold: float
    #: Share of answerable questions whose expected document clears the threshold.
    answered: float
    #: Share of unanswerable questions where no chunk clears the threshold.
    refused: float

    @property
    def balanced_accuracy(self) -> float:
        """Mean of the two rates, so neither group dominates by its size."""
        return (self.answered + self.refused) / 2


class ThresholdCalibrator:
    """Scores thresholds against best-match scores of answerable and unanswerable questions."""

    def __init__(self, answerable: Sequence[float], unanswerable: Sequence[float]):
        """
        Args:
            answerable: Per answerable question, the best score of a chunk from
                its expected document (``-inf`` when that document was not retrieved).
            unanswerable: Per unanswerable question, the best score of any chunk
                (``-inf`` when nothing was retrieved).

        Raises:
            ValueError: When either group is empty; one group alone cannot place a boundary.
        """
        if not answerable or not unanswerable:
            raise ValueError("Calibration needs both answerable and unanswerable questions")
        self._answerable = list(answerable)
        self._unanswerable = list(unanswerable)

    def rates(self, threshold: float) -> ThresholdRates:
        """Answered / refused shares at ``threshold`` (a score equal to it passes, as in the retriever)."""
        answered = sum(score >= threshold for score in self._answerable) / len(self._answerable)
        refused = sum(score < threshold for score in self._unanswerable) / len(self._unanswerable)
        return ThresholdRates(threshold, answered, refused)

    def best(self) -> ThresholdRates:
        """
        The threshold with the highest balanced accuracy.

        Candidates are the midpoints between neighbouring observed scores, so a
        cleanly separated set gets the threshold halfway across the gap. Ties
        go to the lowest threshold: answering is preferred over refusing.
        """
        return max(
            (self.rates(threshold) for threshold in self._candidates()),
            key=lambda rates: (rates.balanced_accuracy, -rates.threshold),
        )

    def _candidates(self) -> List[float]:
        """Midpoints between distinct finite scores, plus one below and one above them all."""
        scores = sorted({s for s in self._answerable + self._unanswerable if math.isfinite(s)})
        if not scores:
            return [0.0]
        midpoints = [(low + high) / 2 for low, high in zip(scores, scores[1:])]
        return [scores[0], *midpoints, math.nextafter(scores[-1], math.inf)]
