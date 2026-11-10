"""Unit tests for the retrieval config comparison (no database, no models)."""

from scripts.eval_compare_configs import ConfigComparisonRunner, comparison_configs


def test_each_config_adds_one_component_and_the_adapter_only_when_fitted():
    configs = comparison_configs(0.7, reranker_available=True, adapter_path="data/query_adapter.npy")

    assert [c.name for c in configs] == ["dense_only", "hybrid", "hybrid_rerank", "hybrid_rerank_adapter"]
    assert configs[0].semantic_weight == 1.0 and not configs[0].reranking_enabled
    assert configs[1].semantic_weight == 0.7 and not configs[1].reranking_enabled
    assert configs[2].reranking_enabled and configs[2].query_adapter_path is None
    assert configs[3].query_adapter_path == "data/query_adapter.npy"


def test_no_reranker_and_no_adapter_leave_only_the_unranked_configs():
    configs = comparison_configs(0.7, reranker_available=False, adapter_path=None)

    assert [c.name for c in configs] == ["dense_only", "hybrid"]


def test_summary_reports_absolute_and_relative_gain_and_skips_a_zero_baseline():
    summary = ConfigComparisonRunner.summarize(
        {"recall_at_k": 0.0, "mrr": 0.8}, {"recall_at_k": 0.5, "mrr": 1.0},
    )

    assert abs(summary["mrr"]["absolute_delta"] - 0.2) < 1e-9
    assert abs(summary["mrr"]["relative_improvement_pct"] - 25.0) < 1e-9
    assert summary["recall_at_k"]["relative_improvement_pct"] is None
