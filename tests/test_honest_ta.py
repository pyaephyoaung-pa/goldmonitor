"""The TA reading has to describe the market it measures, and admit what it
cannot predict.

Checked against real gold on 2026-09-28, when the bot said "RSI 0.98 — STRONG
BUY":

  1. RSI averaged only its last 14 hourly deltas and scored a window with no
     movement as 0, "oversold". A standard 1h RSI(14) read about 20 that day,
     and every weekend the bot read "RSI 0.0" on a market that was shut.
"""
import contextlib
import io
import random
from datetime import datetime, timedelta

import pytz

import predictor

BKK = pytz.timezone("Asia/Bangkok")


def _walk(seed, n):
    """Hourly random walk with timestamps, as append_price writes it."""
    rnd, t0 = random.Random(seed), BKK.localize(datetime(2026, 1, 1))
    price, out = 4000.0, []
    for i in range(n):
        ts = t0 + timedelta(hours=i)
        price *= 1 + rnd.gauss(0, 0.0015)
        out.append({"ts": ts.isoformat(), "thb_gram": round(price, 2),
                    "hour": ts.hour, "weekday": ts.weekday()})
    return out


# ── 1. RSI ──────────────────────────────────────────────────────

def test_a_market_that_did_not_move_is_not_oversold():
    """Every weekend used to read RSI 0.0 — "oversold" — on a closed market."""
    assert predictor.calc_rsi([4000.0] * 30) is None


def test_hours_without_a_move_do_not_change_the_rsi():
    """A weekend of repeated prices leaves RSI where Friday's close left it,
    the way a chart without weekend bars does."""
    prices = [h["thb_gram"] for h in _walk(1, 120)]
    weekend = prices + [prices[-1]] * 48
    assert predictor.calc_rsi(weekend) == predictor.calc_rsi(prices)


def test_rsi_uses_wilders_smoothing():
    # moves +1, -1 seed both averages at 0.5; the +2 then gives
    # gain (0.5*1 + 2)/2 = 1.25, loss (0.5*1 + 0)/2 = 0.25 -> RS 5 -> 83.33
    assert predictor.calc_rsi([10, 11, 10, 12], period=2) == 83.33
    # The same moves with flat hours between them read the same.
    assert predictor.calc_rsi([10, 11, 11, 10, 12, 12], period=2) == 83.33


def test_one_bad_morning_does_not_pin_the_rsi_to_zero():
    """Twelve straight hourly drops after a calm stretch: the old 14-point
    average read 7.1 here — the same shape as the 0.98 seen live — while
    Wilder's RSI keeps its memory of the calm and reads about 20."""
    prices = [4000.0]
    for i in range(200):
        prices.append(prices[-1] + (1 if i % 2 == 0 else -1))
    for _ in range(12):
        prices.append(prices[-1] - 1)
    assert 15 < predictor.calc_rsi(prices) < 30


def test_extremes_still_read_as_extremes():
    assert predictor.calc_rsi(list(range(1, 40))) == 100.0
    assert predictor.calc_rsi(list(range(40, 1, -1))) == 0.0


def test_models_trained_on_the_old_rsi_are_stale_until_retrained():
    """Same vector length, different formula: n_features cannot catch it, and
    trees scoring values they were not trained on return confident nonsense."""
    history = _walk(3, 300)
    with contextlib.redirect_stdout(io.StringIO()):
        model_data = predictor.train_model(history)
    assert all(m["feature_set"] == predictor.FEATURE_SET
               for m in model_data["models"].values())

    fresh = predictor.predict(history, model_data)
    assert all("direction" in p for p in fresh["predictions"].values())

    for m in model_data["models"].values():
        m.pop("feature_set")  # as stored before this change
    stale = predictor.predict(history, model_data)
    for p in stale["predictions"].values():
        assert p["stale"] is True and "direction" not in p
        assert "older feature formulas" in p["error"]
