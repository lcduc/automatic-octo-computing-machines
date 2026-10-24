import numpy as np

from core.retrieval.query_adapter import compute_query_adapter


def test_fits_fp16_embeddings_from_the_gpu_embedder():
    # The live embedder returns float16 on GPU; numpy's solver used to reject it.
    rng = np.random.default_rng(0)
    queries = rng.standard_normal((40, 8)).astype(np.float16)
    target_map = rng.standard_normal((8, 8))
    positives = (queries.astype(np.float64) @ target_map).astype(np.float16)

    adapter = compute_query_adapter(queries, positives, regularization_lambda=1e-6)

    assert adapter.dtype == np.float32 and adapter.shape == (8, 8)
    np.testing.assert_allclose(adapter, target_map, atol=0.05)


def test_build_refuses_an_adapter_that_loses_to_the_unadapted_model(monkeypatch):
    # The app and the router load QUERY_ADAPTER_PATH at start-up, so writing a
    # worse adapter there would silently degrade both.
    from scripts import build_query_adapter

    written = []
    monkeypatch.setattr(
        build_query_adapter.QueryAdapterBuilder, "select_lambda",
        lambda self, *args: (0.1, {"none": 0.630, "0.1": 0.528}),
    )
    monkeypatch.setattr(
        build_query_adapter.QueryAdapterBuilder, "build",
        lambda self, *args: written.append(args) or "adapter.npy",
    )

    assert build_query_adapter.main(["--output", "adapter.npy"]) == 1
    assert written == []
    assert build_query_adapter.main(["--output", "adapter.npy", "--force"]) == 0
    assert len(written) == 1
