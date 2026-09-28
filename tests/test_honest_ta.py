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

  5. So the reading now faces the test the models do, every night, and
     /predict shows what followed it.
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


# ── 5. The reading gets the models' test ────────────────────────

def _crash_and_recover(seed, n=720, every=48):
    """Noise, plus a sharp fall every two days that always recovers within a
    day. A reading that fires on the fall really does have an edge here."""
    rnd, t0 = random.Random(seed), BKK.localize(datetime(2026, 1, 1))
    price, out = 4000.0, []
    for i in range(n):
        phase = i % every
        step = (-0.005 if phase < 6 else 0.003 if phase < 24
                else rnd.gauss(0, 0.0015))
        price *= 1 + step + rnd.gauss(0, 0.0003)
        ts = t0 + timedelta(hours=i)
        out.append({"ts": ts.isoformat(), "thb_gram": round(price, 2),
                    "hour": ts.hour, "weekday": ts.weekday()})
    return out


def test_noise_does_not_earn_a_reading_an_edge():
    """Measured: 4 false edges in 200 walks of 720h (2%), across all four
    directional readings together. None in these."""
    for seed in range(40):
        rec = predictor.ta_track_record(_walk(seed, 400))
        assert not any(r["has_edge"] for r in rec["readings"].values()), seed


def test_a_reading_that_works_is_found():
    """A test that never fires would also pass the noise check. Measured:
    found in 20 of 20 of these series."""
    for seed in range(3):
        oversold = predictor.ta_track_record(
            _crash_and_recover(seed))["readings"]["OVERSOLD"]
        assert oversold["has_edge"] is True, (seed, oversold)
        assert oversold["ups"] == oversold["n"] >= 10


def test_a_run_of_one_reading_counts_once(monkeypatch):
    """Ten OVERSOLD hours in a row share almost all of one outcome. Counted
    one by one, a single bounce would look like ten."""
    runs = set(range(100, 110)) | {115} | set(range(140, 146))
    monkeypatch.setattr(predictor, "analyze", lambda h: {
        "overall_signal": "OVERSOLD" if len(h) - 1 in runs else "NEUTRAL"})
    rec = predictor.ta_track_record(_walk(5, 220))
    # 100 counts; 101-109 and 115 fall inside its 24h window; 140 does not.
    assert rec["readings"]["OVERSOLD"]["n"] == 2


def _falling():
    return _hist([4000 - 12 * i for i in range(120)])


def _record(**readings):
    return {"version": predictor.TA_TRACK_VERSION, "horizon": 24,
            "base_up": 0.54, "days": 30, "readings": readings}


def test_predict_shows_what_followed_the_reading():
    assert predictor.analyze(_falling())["overall_signal"] == "OVERSOLD"
    model_data = {"ta_track": _record(
        OVERSOLD={"n": 9, "ups": 5, "p_value": 0.5, "has_edge": False})}
    msg = predictor.format_prediction_message(
        predictor.predict(_falling(), model_data), "en")
    assert "after OVERSOLD: higher 24h later in 5/9 cases (56%) vs 54%" in msg
    assert "⚠️no-edge" in msg


def test_a_falling_side_reading_is_graded_on_falls():
    rising = _hist([round(4000 * 1.003 ** i, 2) for i in range(120)])
    model_data = {"ta_track": _record(
        OVERBOUGHT={"n": 8, "ups": 2, "p_value": 0.03, "has_edge": True})}
    msg = predictor.format_prediction_message(
        predictor.predict(rising, model_data), "en")
    assert "lower 24h later in 6/8 cases (75%) vs 46%" in msg
    assert "✅edge" in msg


def test_a_reading_with_no_past_cases_says_so():
    model_data = {"ta_track": _record(OVERSOLD={"n": 0, "ups": 0, "has_edge": False})}
    msg = predictor.format_prediction_message(
        predictor.predict(_falling(), model_data), "en")
    assert "no OVERSOLD readings to check yet" in msg


def test_a_stale_or_mangled_record_is_not_shown():
    """It is read back from a shared store: /predict must not crash on it."""
    good = _record(OVERSOLD={"n": 4, "ups": 2, "has_edge": False})
    assert "ta_track" in predictor.predict(_falling(), {"ta_track": good})
    for bad in (dict(good, version="older"), dict(good, readings=[]),
                _record(OVERSOLD={"n": "4", "ups": 2}),
                _record(OVERSOLD={"n": 4, "ups": 9}),
                dict(good, base_up=None), dict(good, days="30"), "junk", None):
        out = predictor.predict(_falling(), {"ta_track": bad})
        assert "ta_track" not in out, bad
        predictor.format_prediction_message(out, "en")


def test_a_closed_market_is_not_graded(monkeypatch):
    """A weekend freezes both the reading and the price. Graded, it would
    count Friday's reading again every 24h and score each flat outcome UP."""
    history = _walk(6, 220)
    for row in history[101:161]:  # 60 closed hours after Friday's close at 100
        row["thb_gram"] = history[100]["thb_gram"]
    monkeypatch.setattr(predictor, "analyze", lambda h: {
        "overall_signal": "OVERSOLD" if 100 <= len(h) - 1 <= 160 else "NEUTRAL"})
    assert predictor.ta_track_record(history)["readings"]["OVERSOLD"]["n"] == 1
