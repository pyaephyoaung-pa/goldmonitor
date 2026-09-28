"""The TA reading has to describe the market it measures, and admit what it
cannot predict.

Checked against real gold on 2026-09-28, when the bot said "RSI 0.98 — STRONG
BUY":

  1. RSI averaged only its last 14 hourly deltas and scored a window with no
     movement as 0, "oversold". A standard 1h RSI(14) read about 20 that day,
     and every weekend the bot read "RSI 0.0" on a market that was shut.

  2. The other indicators ran over the weekend's repeated prices too, so the
     reading kept changing on a market that was not trading. Replayed over two
     years, 75% of closed-market hours were labelled BUY or STRONG BUY.

  3. The composite was lopsided: the falling side reached +1.2, the rising
     side only -0.9, so OVERBOUGHT (-1 or lower) could never fire — and did
     not, once, in two years — while BUY or STRONG BUY covered 45% of hours.

  4. The top reading told every subscriber "STRONG BUY — the best time to
     buy". Replayed with the test the ML models must pass, the price was no
     likelier to be higher 24h later than after any other hour (55% vs 54%,
     p=0.43). And when the ML had no edge, its note sent users to that
     reading: "rely on the TA signal below".
"""
import contextlib
import io
import random
from datetime import datetime, timedelta

import pytz

import i18n
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


# ── 2. Closed-market hours ──────────────────────────────────────

def _with_weekend(history, hours=48):
    """The cron keeps storing a point every hour while spot sits still."""
    last = history[-1]
    t = datetime.fromisoformat(last["ts"])
    return history + [dict(last, ts=(t + timedelta(hours=i)).isoformat())
                      for i in range(1, hours + 1)]


def test_a_weekend_does_not_change_the_reading():
    for seed in range(5):
        friday = _walk(seed, 200)
        assert predictor.analyze(_with_weekend(friday)) == predictor.analyze(friday)


def test_trading_prices_keeps_each_run_once():
    assert predictor.trading_prices([1, 1, 2, 2, 2, 1, 3, 3]) == [1, 2, 1, 3]
    assert predictor.trading_prices([]) == []


# ── 3. A symmetric scale ────────────────────────────────────────

def _hist(prices):
    return [{"thb_gram": p} for p in prices]


def test_a_strong_rise_can_read_overbought():
    rise = [round(4000 * 1.003 ** i, 2) for i in range(120)]
    ta = predictor.analyze(_hist(rise))
    assert ta["buy_score"] == -1.2
    assert ta["overall_signal"] == predictor.READINGS[-1]


def test_a_mirrored_series_gets_the_mirrored_score():
    """Reflect a price path about a level: every indicator flips sign, so the
    score must too. The old weights gave +1.2 one way and -0.9 the other."""
    for seed in range(10):
        path = [h["thb_gram"] for h in _walk(seed, 200)]
        mirror = [round(8000 - p, 2) for p in path]
        up, down = predictor.analyze(_hist(path)), predictor.analyze(_hist(mirror))
        assert up["buy_score"] == -down["buy_score"], seed


def test_thresholds_mirror_each_other():
    """+x and -x land the same number of steps from the middle reading,
    including exactly on a boundary (the old code sent -1.0 to OVERBOUGHT but
    +1.0 only to BUY)."""
    readings = predictor.READINGS
    for x in (0.0, 0.3, 0.31, 1.0, 1.01, 1.2):
        step = readings.index(predictor.reading_for(x))
        assert predictor.reading_for(-x) == readings[len(readings) - 1 - step], x


def test_no_reading_without_data():
    """Too little data used to fall back to score 0 and call the price
    "stable" — describing a price it had not measured."""
    out = predictor.predict(_hist([4000.0, 4001.0, 4002.0]), {})
    assert "ta_outlook" not in out


# ── 4. Readings describe; they do not advise ────────────────────

_ADVICE = {"en": ("buy", "sell"), "my": ("ဝယ်", "ရောင်း"), "th": ("ซื้อ", "ขาย")}
_TA_TEXT = [predictor._READING_TEXT[r] for r in predictor.READINGS] + [
    "ta.no_edge", "ta.bullish", "ta.bearish", "ta.mixed"]


def test_no_reading_tells_anyone_to_buy_or_sell():
    for key in _TA_TEXT:
        for lang, words in _ADVICE.items():
            text = i18n.t(key, lang).lower()
            assert not any(w in text for w in words), (key, lang, text)


def test_the_ml_note_does_not_send_users_to_the_ta_reading():
    for lang in _ADVICE:
        text = i18n.t("ta.no_edge", lang)
        assert "TA" not in text and "rely" not in text, (lang, text)


def test_every_reading_the_score_can_produce_has_text():
    for score in (1.2, 0.5, 0.0, -0.5, -1.2):
        key = predictor._READING_TEXT[predictor.reading_for(score)]
        assert key in i18n.STRINGS


def test_the_reading_names_its_timeframe():
    """RSI(14) here is 14 HOURS. Unlabelled, it was read as the daily RSI."""
    prediction = predictor.predict(_walk(4, 200), {})
    msg = predictor.format_prediction_message(prediction, "en")
    assert "RSI (1h)" in msg and "TA (1h)" in msg
