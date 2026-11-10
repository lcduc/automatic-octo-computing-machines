import math

import pytest

from scripts.threshold_calibrator import ThresholdCalibrator


def test_separated_groups_get_the_midpoint_of_the_gap():
    best = ThresholdCalibrator(answerable=[0.9, 0.7, 0.6], unanswerable=[0.1, 0.3, -math.inf]).best()
    assert best.threshold == pytest.approx(0.45)
    assert (best.answered, best.refused) == (1.0, 1.0)


def test_overlap_maximizes_balanced_accuracy_and_ties_prefer_answering():
    calibrator = ThresholdCalibrator(answerable=[0.8, 0.4], unanswerable=[0.5, 0.2])
    best = calibrator.best()
    # 0.3 (answers 2/2, refuses 1/2) ties 0.65 (answers 1/2, refuses 2/2); the lower one wins.
    assert best.threshold == pytest.approx(0.3)
    assert best.balanced_accuracy == pytest.approx(0.75)


def test_a_score_equal_to_the_threshold_passes():
    rates = ThresholdCalibrator(answerable=[0.5], unanswerable=[0.5]).rates(0.5)
    assert (rates.answered, rates.refused) == (1.0, 0.0)


def test_one_group_alone_cannot_be_calibrated():
    with pytest.raises(ValueError):
        ThresholdCalibrator(answerable=[0.9], unanswerable=[])
