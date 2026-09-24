"""The ML "edge" claim has to survive pure noise, and grade what it trains on.

Two defects lived here. They were measured, not guessed:

  1. has_edge was `OOS accuracy >= baseline + 2 points`. On 60 independent
     random walks — where nothing is predictable, so every "edge" is false — it
     fired on ~20% of horizons, and 38% of retrains showed "✅edge" on at least
     one. That flag decides the ✅/⚠️ tag users see and which horizons vote in
     the evening outlook.

  2. Training labelled UP as "the biggest swing was upward"; live grading
     scored UP as "it closed higher". They disagreed on 13-15% of samples, so
     training accuracy and the live hit-rate measured different things.
"""
import contextlib
import io
import math
import random
from datetime import datetime, timedelta

import pytz

import predictor

BKK = pytz.timezone("Asia/Bangkok")


def _walk(seed, n, seasonal=0.0, skip=0.0):
    """Hourly random walk. `seasonal` adds a real, learnable daily cycle;
    `skip` drops that share of hours, the way a delayed cron run does."""
    rnd, t0 = random.Random(seed), BKK.localize(datetime(2026, 1, 1))
    price, out = 4000.0, []
    for i in range(n):
        ts = t0 + timedelta(hours=i)
        price *= 1 + rnd.gauss(0, 0.0015)
        if skip and rnd.random() < skip:
            continue
        shown = price * (1 + seasonal * math.sin(2 * math.pi * ts.hour / 24))
        out.append({"ts": ts.isoformat(), "thb_gram": round(shown, 2),
                    "hour": ts.hour, "weekday": ts.weekday()})
    return out


def _train(history):
    with contextlib.redirect_stdout(io.StringIO()):
        return predictor.train_model(history)


# ── 1. No edge on noise ─────────────────────────────────────────

def test_pure_noise_does_not_show_an_edge():
    """The regression that matters. Fixed seeds keep it deterministic; the old
    rule claimed an edge on roughly one in five of these horizons."""
    false_edges, horizons = 0, 0
    for seed in range(20):
        for m in (_train(_walk(seed, 300)) or {}).get("models", {}).values():
            horizons += 1
            false_edges += m["has_edge"]
    assert horizons >= 40, "too few models trained to judge"
    # A 5% test would allow ~3 here; the test is deliberately conservative.
    assert false_edges <= 1, f"{false_edges}/{horizons} false edges on pure noise"


def test_a_real_edge_still_gets_through():
    """Zero false positives would also be scored by a flag that never fires.
    A strong daily cycle is genuinely predictable at 4h and must be found."""
    found = sum(_train(_walk(seed, 720, seasonal=0.004))["models"]["4h"]["has_edge"]
                for seed in (0, 2, 3))
    assert found >= 2, f"a real 4h edge was detected in only {found}/3 runs"


def test_24h_on_a_daily_cycle_is_not_an_edge():
    """A 24-hour cycle is back where it started 24h later — there is nothing
    to predict at that horizon, and the test must not invent something."""
    md = _train(_walk(0, 720, seasonal=0.004))
    assert md["models"]["24h"]["has_edge"] is False


# ── The test statistic itself ───────────────────────────────────

def test_overlapping_labels_are_counted_as_few_samples():
    """55 hold-out rows at 24h are ~2 independent outcomes. Even a perfect
    score on 2 coin-flips is not evidence."""
    p_value, n_eff = predictor.edge_significance(1.0, 0.55, n_test=55, horizon=24)
    assert n_eff == 2
    assert p_value > predictor.EDGE_P_VALUE


def test_strong_accuracy_on_enough_samples_is_significant():
    p_value, n_eff = predictor.edge_significance(0.90, 0.55, n_test=144, horizon=4)
    assert n_eff == 36
    assert p_value < predictor.EDGE_P_VALUE


def test_a_baseline_of_one_can_never_be_beaten():
    assert predictor.edge_significance(1.0, 1.0, 100, 4)[0] == 1.0


def test_binomial_tail_matches_the_closed_form():
    # P(X >= 2) for Binomial(3, 0.5) = (3 + 1) / 8
    assert math.isclose(predictor._binomial_tail(2, 3, 0.5), 0.5)
    assert predictor._binomial_tail(0, 5, 0.3) == 1.0
    assert predictor._binomial_tail(6, 5, 0.3) == 0.0


def test_models_record_how_the_edge_was_judged():
    md = _train(_walk(0, 300))
    for m in md["models"].values():
        assert m["edge_test"] == predictor.EDGE_TEST
        assert 0.0 <= m["edge_p_value"] <= 1.0
        assert m["effective_test_samples"] >= 1


def test_an_edge_judged_by_the_old_rule_is_not_trusted():
    """Stored models carry the flag from when they were trained. One stamped
    by the flat 2-point rule must stop showing ✅edge now, not after the next
    3am retrain replaces it."""
    hist = _walk(0, 300)
    md = _train(hist)
    for m in md["models"].values():
        m["has_edge"] = True
        m.pop("edge_test")            # as a model trained before this change

    out = predictor.predict(hist, md)

    assert all(p.get("has_edge") is False
               for p in out["predictions"].values() if "direction" in p)


# ── 2. Train on exactly what is graded ──────────────────────────

def _graded(history, i, hours):
    """What resolve_predictions concludes for a call made at row i."""
    md = {"predictions": [{"ts": history[i]["ts"], "horizon": f"{hours}h",
                           "hours": hours, "direction": "UP",
                           "price_at": history[i]["thb_gram"], "resolved": False}]}
    predictor.resolve_predictions(md, history)
    p = md["predictions"][0]
    if not p["resolved"] or p.get("void"):
        return None
    return 1 if p["actual"] == "UP" else 0


def test_training_labels_equal_live_grading():
    """They used to disagree on 13-15% of rows. Now they share one function."""
    for skip in (0.0, 0.10):              # with and without missed cron runs
        hist = _walk(5, 400, skip=skip)
        timeline = predictor._timeline(hist)
        for hours in (4, 12, 24):
            for i in range(len(hist)):
                assert predictor._build_labels(hist, i, hours, timeline) == \
                    _graded(hist, i, hours), (skip, hours, i)


def test_horizon_is_wall_clock_hours_not_rows():
    """A missed cron run used to stretch a "24h" label to however many hours
    the next 24 rows happened to span."""
    t0 = BKK.localize(datetime(2026, 1, 1))
    hist = [{"ts": (t0 + timedelta(hours=h)).isoformat(), "thb_gram": p}
            for h, p in [(0, 100.0), (1, 50.0), (4, 150.0)]]   # hours 2-3 missing
    # 4 hours after hour 0 is hour 4 (150, UP) — not the 4th row, which
    # does not exist, and not row 1 (50, DOWN).
    assert predictor._build_labels(hist, 0, 4) == 1


def test_a_label_across_a_long_gap_is_void():
    t0 = BKK.localize(datetime(2026, 1, 1))
    hist = [{"ts": (t0 + timedelta(hours=h)).isoformat(), "thb_gram": 100.0}
            for h in (0, 20)]                                  # 20h hole
    assert predictor._build_labels(hist, 0, 4) is None
