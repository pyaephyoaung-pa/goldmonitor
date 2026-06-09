import math
import copy
import predictor


def _series(n=220, seed=7):
    # Deterministic pseudo-random walk (no real signal) for honest-metric tests.
    prices, p, x = [], 1000.0, seed
    for _ in range(n):
        x = (1103515245 * x + 12345) % (2 ** 31)
        step = (x / (2 ** 31)) - 0.5  # roughly [-0.5, 0.5]
        p = max(1.0, p + step)
        prices.append(round(p, 2))
    return [{"thb_gram": pr, "hour": i % 24, "weekday": i % 7, "usd_oz": pr / 1000}
            for i, pr in enumerate(prices)]


def test_train_model_reports_honest_metrics():
    md = predictor.train_model(_series())
    assert md is not None and md["models"], "expected at least one horizon model"
    for name, info in md["models"].items():
        # New honest fields must be present...
        for key in ("oos_accuracy", "baseline_accuracy", "train_accuracy",
                    "has_edge", "samples", "test_samples"):
            assert key in info, f"{name} missing {key}"
        assert isinstance(info["has_edge"], bool)
        # back-compat 'accuracy' now equals the out-of-sample number, not train
        assert info["accuracy"] == info["oos_accuracy"]


def test_predict_flags_no_edge_honestly():
    history = _series()
    md = predictor.train_model(history)
    # Force the "no edge" condition regardless of the synthetic data.
    no_edge = copy.deepcopy(md)
    for info in no_edge["models"].values():
        info["has_edge"] = False
    res = predictor.predict(history, no_edge)
    assert res.get("ml_has_edge") is False
    assert "no historical edge" in res["combined_outlook"]


def test_predict_uses_edged_votes_when_available():
    history = _series()
    md = predictor.train_model(history)
    edged = copy.deepcopy(md)
    for info in edged["models"].values():
        info["has_edge"] = True
    res = predictor.predict(history, edged)
    assert res.get("ml_has_edge") is True
    assert "with edge" in res["combined_outlook"]


def test_predict_without_models_is_ta_only():
    history = _series(120)
    res = predictor.predict(history, {"models": {}})
    assert res["ml_available"] is False
    assert "ta_outlook" in res  # TA always available
