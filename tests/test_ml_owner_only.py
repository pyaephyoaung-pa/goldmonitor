"""ML forecasts go to the owner, and to everyone else only once a model has an
edge.

Every nightly model has failed the edge test. So did the same model trained
on two years of hourly gold (28x the data the bot keeps), and two pretrained
forecasters, Chronos-Bolt and Chronos-2, scored on months they had never seen:
none beat always guessing the more common direction. Shown to every
subscriber, the ML lines were noise with a confidence bar on it.
"""
import copy
import datetime as _dt

import pytz

import bot_core
import predictor
import storage
from test_evening_privacy import _evening

BKK = pytz.timezone("Asia/Bangkok")

NO_EDGE = {
    "technical_analysis": {"current_price": 4500.0, "overall_signal": "NEUTRAL",
                           "buy_score": 0.0},
    "ta_outlook": "➡️ NEUTRAL — no clear move on the 1h chart",
    "ml_available": True,
    "ml_has_edge": False,
    "combined_outlook_key": "ta.no_edge",
    "combined_outlook": "⚠️ ML models show no historical edge over a coin-flip — treat their calls as noise",
    "predictions": {"24h": {"direction": "UP", "confidence": 62.0, "oos_accuracy": 50.0,
                            "baseline_accuracy": 55.0, "has_edge": False}},
    "hit_rates": {"24h": {"n": 10, "correct": 4, "hit_pct": 40.0}},
}

WITH_EDGE = copy.deepcopy(NO_EDGE)
WITH_EDGE.update(ml_has_edge=True, combined_outlook_key="ta.bullish",
                 combined_outlook="ML models (with edge) lean BULLISH")
WITH_EDGE["predictions"]["24h"]["has_edge"] = True

ML_MARKS = ("ML Predictions", "OOS 50.0%", "Live hit-rate", "no historical edge")


# ── /predict ────────────────────────────────────────────────────

def test_subscribers_do_not_see_models_without_an_edge():
    msg = predictor.format_prediction_message(NO_EDGE, "en")
    assert not any(mark in msg for mark in ML_MARKS), msg
    assert "ML forecasts are hidden" in msg
    assert "NEUTRAL" in msg, "the TA reading stays"


def test_the_owner_still_sees_the_diagnostics():
    msg = predictor.format_prediction_message(NO_EDGE, "en", show_ml=True)
    assert all(mark in msg for mark in ML_MARKS), msg
    assert "hidden" not in msg


def test_a_model_with_an_edge_is_shown_to_everyone():
    msg = predictor.format_prediction_message(WITH_EDGE, "en")
    assert "ML Predictions" in msg and "lean BULLISH" in msg
    assert "hidden" not in msg


def test_cmd_predict_shows_ml_to_the_owner_only(monkeypatch):
    sent = {}
    monkeypatch.setattr(bot_core, "TG_CHAT_ID", "OWNER")
    monkeypatch.setattr(storage, "get_price_history", lambda: [{"thb_gram": 1.0}] * 20)
    monkeypatch.setattr(storage, "load_model_data", lambda: {})
    monkeypatch.setattr(predictor, "resolve_predictions", lambda md, h: False)
    monkeypatch.setattr(predictor, "predict", lambda h, md, lang=None: copy.deepcopy(NO_EDGE))
    monkeypatch.setattr(predictor, "prediction_hit_rates", lambda md: NO_EDGE["hit_rates"])
    monkeypatch.setattr(bot_core, "send_message",
                        lambda text, chat_id="": sent.__setitem__(chat_id, text))

    bot_core.cmd_predict("OWNER", "en")
    bot_core.cmd_predict("SOMEONE", "en")

    assert "ML Predictions" in sent["OWNER"]
    assert "ML Predictions" not in sent["SOMEONE"]


# ── The evening summary ─────────────────────────────────────────

def _history():
    t0 = BKK.localize(_dt.datetime(2026, 9, 25, 0, 0))
    return [{"ts": (t0 + _dt.timedelta(hours=h)).isoformat(), "thb_gram": 4500.0 + h,
             "usd_oz": 2400.0 + h} for h in range(19)]


def _evening_with(monkeypatch, prediction, **kw):
    monkeypatch.setattr(predictor, "predict", lambda h, md, lang=None: copy.deepcopy(prediction))
    monkeypatch.setattr(predictor, "prediction_hit_rates", lambda md: prediction["hit_rates"])
    return _evening(monkeypatch, extra_files={storage.PRICE_HISTORY_FILE: _history()}, **kw)


def test_evening_ml_lines_reach_the_owner_only_without_an_edge(monkeypatch):
    got = _evening_with(monkeypatch, NO_EDGE)
    assert "Tomorrow" in got["owner"] and "ML live hit-rate" in got["owner"]
    for sub in ("alice", "bob"):
        assert "Tomorrow" not in got[sub] and "hit-rate" not in got[sub], got[sub]


def test_evening_ml_lines_reach_everyone_with_an_edge(monkeypatch):
    got = _evening_with(monkeypatch, WITH_EDGE)
    for chat in ("owner", "alice", "bob"):
        assert "lean BULLISH" in got[chat], got[chat]


def test_the_evening_outlook_is_in_each_readers_language(monkeypatch):
    """It was rendered once, in the default language, for every recipient."""
    got = _evening_with(monkeypatch, WITH_EDGE,
                        langs={"owner": "en", "alice": "th", "bob": "en"})
    assert "พรุ่งนี้" in got["alice"] and "เอนไปทาง BULLISH" in got["alice"]
    assert "lean BULLISH" in got["bob"]


def test_no_models_no_tomorrow_line(monkeypatch):
    """Without models the TA reading stood in as "Tomorrow:" — a description
    of the last day presented as a forecast."""
    no_models = copy.deepcopy(NO_EDGE)
    no_models.update(predictions={}, ml_available=False, combined_outlook_key=None,
                     ml_has_edge=False, hit_rates={})
    got = _evening_with(monkeypatch, no_models)
    for chat in ("owner", "alice"):
        assert "Tomorrow" not in got[chat], got[chat]
