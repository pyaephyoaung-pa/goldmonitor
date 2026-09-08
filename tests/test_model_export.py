"""ML models are stored as arithmetic, not as pickles.

Unpickling executes code. The models live in a Gist, so the old `model_b64`
format made a data store into a remote-code-execution path into the Actions
runner — which holds the Telegram bot token. These tests pin the replacement:
the exported trees must score IDENTICALLY to sklearn, and a leftover pickle
must never be loaded.
"""
import json
import pathlib
import random
from datetime import datetime, timedelta

import numpy as np
import pytest
import pytz

import predictor

BKK = pytz.timezone("Asia/Bangkok")


def _history(n=200, seed=7):
    random.seed(seed)
    now = datetime.now(BKK)
    price, out = 4000.0, []
    for i in range(n, 0, -1):
        ts = now - timedelta(hours=i)
        price *= 1 + random.gauss(0, 0.0015)
        out.append({"ts": ts.isoformat(), "thb_gram": round(price, 2),
                    "usd_oz": round(price / 1.4, 2),
                    "hour": ts.hour, "weekday": ts.weekday()})
    return out


@pytest.fixture(scope="module")
def trained():
    hist = _history()
    model_data = predictor.train_model(hist)
    assert model_data, "training produced no models"
    return hist, model_data


# ── No pickle anywhere on the inference path ────────────────────

def test_predictor_does_not_import_pickle():
    """Checked on the imported module, not the source text — the comments in
    predictor.py still mention pickle, on purpose, to explain why it is gone."""
    assert not hasattr(predictor, "pickle")
    assert not hasattr(predictor, "base64")
    src = pathlib.Path(predictor.__file__).read_text()
    code = "\n".join(line for line in src.splitlines()
                     if not line.lstrip().startswith("#"))
    # A function-local `import pickle` would not show up as a module attribute.
    assert "import pickle" not in code
    assert "pickle.load" not in code


def test_stored_model_is_plain_json(trained):
    _, model_data = trained
    for name, minfo in model_data["models"].items():
        assert "model_b64" not in minfo, name
        assert minfo["trees"]["format"] == predictor.MODEL_FORMAT
        # Round-trips through JSON with no custom encoder: it is only numbers.
        json.loads(json.dumps(minfo["trees"]))


def test_legacy_pickle_is_reported_stale_never_loaded(trained):
    """A pre-switchover payload degrades to TA only until the 3am retrain."""
    hist, _ = trained
    # Valid base64 of a real pickle; if anything tried to load it we would see
    # an unpickling error rather than the stale marker.
    n_features = len(predictor._extract_features(hist, len(hist) - 1))
    legacy = {"models": {"24h": {"model_b64": "gASVCgAAAAAAAACMBmFiY2RlZpQu",
                                 "n_features": n_features}}}
    result = predictor.predict(hist, legacy)

    pred = result["predictions"]["24h"]
    assert pred["stale"] is True
    assert "old pickle format" in pred["error"]
    assert "direction" not in pred


# ── The export reproduces sklearn exactly ───────────────────────

def test_export_matches_sklearn_probabilities(trained):
    """The whole point: our arithmetic and sklearn's must not diverge."""
    from sklearn.ensemble import GradientBoostingClassifier

    hist, model_data = trained
    X, y = [], []
    for i in range(26, len(hist) - 24):
        f = predictor._extract_features(hist, i)
        lab = predictor._build_labels(hist, i, 24)
        if f is not None and lab is not None:
            X.append(f)
            y.append(lab)
    X, y = np.array(X), np.array(y)

    sk = GradientBoostingClassifier(n_estimators=50, max_depth=3,
                                    learning_rate=0.1, random_state=42).fit(X, y)
    bundle = model_data["models"]["24h"]["trees"]
    mine = np.array([predictor._score_bundle(bundle, list(row)) for row in X])

    assert np.abs(mine - sk.predict_proba(X)[:, 1]).max() < 1e-12
    assert ((mine >= 0.5).astype(int) == sk.predict(X)).all()


def test_predict_returns_a_direction(trained):
    hist, model_data = trained
    result = predictor.predict(hist, model_data)

    assert result["ml_available"] is True
    for name, p in result["predictions"].items():
        assert p.get("error") is None, (name, p)
        assert p["direction"] in ("UP", "DOWN")
        assert 50.0 <= p["confidence"] <= 100.0


def test_export_is_refused_when_it_disagrees(monkeypatch):
    """A future sklearn changing its internals must fail loudly at TRAINING
    time, not score differently in production."""
    monkeypatch.setattr(predictor, "_tree_value", lambda tree, features: 0.0)
    assert predictor.train_model(_history()) is None


# ── Scoring is robust to a corrupted store ──────────────────────

def test_tree_walk_terminates_on_a_cycle():
    cyclic = {"left": [1, 0], "right": [1, 0], "feature": [0, 0],
              "threshold": [0.0, 0.0], "value": [1.0, 2.0]}
    with pytest.raises(ValueError):
        predictor._tree_value(cyclic, [1.0])


def test_score_bundle_saturates_instead_of_overflowing():
    leaf = {"left": [-1], "right": [-1], "feature": [-2],
            "threshold": [-2.0], "value": [1.0]}
    huge = {"intercept": 0.0, "learning_rate": 1e6, "trees": [leaf]}
    assert predictor._score_bundle(huge, [0.0]) == 1.0
    huge["learning_rate"] = -1e6
    assert predictor._score_bundle(huge, [0.0]) == 0.0


# ── A one-sided market must not crash the 3am training job ──────

def test_single_class_history_skips_instead_of_raising():
    """A steady climb labels every sample UP; sklearn refuses to fit one class.

    Unguarded that is a ValueError out of train_model, which the monitor turns
    into a crash alert and a red run at 3am every day until the shape changes.
    """
    now = datetime.now(BKK)
    climbing = [{"ts": (now - timedelta(hours=200 - i)).isoformat(),
                 "thb_gram": 4000.0 + i, "usd_oz": 2400.0 + i,
                 "hour": i % 24, "weekday": i % 7} for i in range(200)]

    assert predictor.train_model(climbing) is None
