"""The eval gate fails on the regressions it is meant to catch and passes on noise (no models needed)."""

import pytest

from scripts.eval_baseline import EvalBaseline


@pytest.fixture
def baseline(tmp_path):
    store = EvalBaseline(tmp_path / "baseline.json")
    store.write("router", {"cases": 200, "accuracy": 0.90})
    store.write("set_a", {"answerable": 40, "recall_at_k": 1.0, "mrr": 0.95})
    return store


def _router_report(accuracy=0.90, cases=200, stolen=()):
    return {
        "cases": cases, "accuracy": accuracy,
        "questions_stolen_by_a_shortcut": [{"text": text, "became": "off_topic", "score": 0.9} for text in stolen],
    }


def _retrieval_report(recall=1.0, mrr=0.95, answerable=40):
    return {"answerable": answerable, "top_k": 4, "recall_at_k": recall, "mrr": mrr}


def test_router_holds_within_the_tolerance(baseline):
    assert baseline.check_router(_router_report()) == []
    # 2 points is the allowance at 200 messages (2 messages would be 1 point).
    assert baseline.check_router(_router_report(accuracy=0.88)) == []
    assert len(baseline.check_router(_router_report(accuracy=0.87))) == 1


def test_two_messages_are_allowed_on_a_small_set_even_below_two_points(tmp_path):
    store = EvalBaseline(tmp_path / "small.json")
    store.write("router", {"cases": 40, "accuracy": 0.90})  # 2 messages = 5 points here
    assert store.check_router(_router_report(accuracy=0.85, cases=40)) == []
    assert len(store.check_router(_router_report(accuracy=0.80, cases=40))) == 1


def test_a_stolen_question_always_fails_however_good_the_accuracy(baseline):
    problems = baseline.check_router(_router_report(accuracy=0.99, stolen=["học phí bao nhiêu"]))
    assert len(problems) == 1 and "học phí bao nhiêu" in problems[0]


def test_a_changed_eval_set_or_a_missing_baseline_must_be_re_recorded(baseline, tmp_path):
    assert "re-record" in baseline.check_router(_router_report(cases=201))[0]
    assert "no router baseline" in EvalBaseline(tmp_path / "none.json").check_router(_router_report())[0]
    assert "no retrieval baseline" in baseline.check_retrieval("other_set", _retrieval_report())[0]


def test_retrieval_recall_may_not_drop_and_mrr_may_drop_by_two_hundredths(baseline):
    assert baseline.check_retrieval("set_a", _retrieval_report()) == []
    assert baseline.check_retrieval("set_a", _retrieval_report(mrr=0.93)) == []
    assert "MRR" in baseline.check_retrieval("set_a", _retrieval_report(mrr=0.92))[0]
    assert "recall" in baseline.check_retrieval("set_a", _retrieval_report(recall=0.975))[0]
    assert "re-record" in baseline.check_retrieval("set_a", _retrieval_report(answerable=41))[0]
