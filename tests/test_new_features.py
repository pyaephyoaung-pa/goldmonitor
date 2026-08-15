"""Tests for v2.1: hourly append throttle, fail-closed owner check,
/chart config, price-level alerts, prediction accuracy tracker."""

from datetime import datetime, timedelta

import pytz

import bot_core
import predictor
import storage

BKK = pytz.timezone("Asia/Bangkok")


def _hourly_history(n, start_price=4000.0, step=1.0):
    """n hourly points ending now."""
    now = datetime.now(BKK)
    return [
        {
            "ts": (now - timedelta(hours=n - 1 - i)).isoformat(),
            "thb_gram": start_price + i * step,
            "usd_oz": 2400.0,
            "thb_rate": 34.0,
            "hour": 12,
            "weekday": 1,
        }
        for i in range(n)
    ]


# ── Hourly append throttle ──────────────────────────────────────

def test_append_price_throttled_when_fresh(monkeypatch):
    history = _hourly_history(5)
    monkeypatch.setattr(storage, "_read_file", lambda f: list(history))
    writes = []
    monkeypatch.setattr(storage, "_write_file", lambda f, d: writes.append(d))
    result = storage.append_price(4100.0, 2400.0, 34.0)
    assert len(result) == 5  # newest point is < 55 min old -> no append
    assert writes == []      # and no Gist write at all


def test_append_price_appends_when_stale(monkeypatch):
    now = datetime.now(BKK)
    history = [{
        "ts": (now - timedelta(minutes=61)).isoformat(),
        "thb_gram": 4000.0,
    }]
    monkeypatch.setattr(storage, "_read_file", lambda f: list(history))
    writes = []
    monkeypatch.setattr(storage, "_write_file", lambda f, d: writes.append(d))
    result = storage.append_price(4100.0, 2400.0, 34.0)
    assert len(result) == 2
    assert len(writes) == 1


def test_append_price_appends_to_empty(monkeypatch):
    monkeypatch.setattr(storage, "_read_file", lambda f: [])
    writes = []
    monkeypatch.setattr(storage, "_write_file", lambda f, d: writes.append(d))
    result = storage.append_price(4100.0, 2400.0, 34.0)
    assert len(result) == 1


# ── Fail-closed owner check ─────────────────────────────────────

def test_owner_commands_locked_when_chat_id_unset(monkeypatch):
    sent = []
    monkeypatch.setattr(bot_core, "send_message",
                        lambda text, chat_id="": sent.append((chat_id, text)))
    monkeypatch.setattr(bot_core, "TG_CHAT_ID", "")  # not configured
    handled = bot_core.dispatch_update(
        {"message": {"text": "/portfolio", "chat": {"id": "222"}}})
    assert handled is False
    assert any("🔒" in t for _, t in sent)


# ── /chart config ───────────────────────────────────────────────

def test_build_chart_config_basic():
    cfg = bot_core.build_chart_config(_hourly_history(48), days=2)
    assert cfg["type"] == "line"
    data = cfg["data"]["datasets"][0]["data"]
    assert 2 <= len(data) <= bot_core.CHART_MAX_POINTS
    assert data[-1] == 4047.0  # last price kept


def test_build_chart_config_downsamples():
    cfg = bot_core.build_chart_config(_hourly_history(30 * 24), days=30)
    assert len(cfg["data"]["datasets"][0]["data"]) <= bot_core.CHART_MAX_POINTS


def test_build_chart_config_not_enough_data():
    assert bot_core.build_chart_config(_hourly_history(1), days=7) is None


# ── Price-level alerts ──────────────────────────────────────────

class _MemStore:
    """Patch storage's Gist I/O with an in-memory dict."""

    def __init__(self, monkeypatch):
        self.files = {}
        monkeypatch.setattr(storage, "_read_file",
                            lambda f: self.files.get(f, {} if f != storage.PRICE_HISTORY_FILE else []))
        monkeypatch.setattr(storage, "_write_file",
                            lambda f, d: self.files.__setitem__(f, d))


def test_level_alert_add_list_remove(monkeypatch):
    _MemStore(monkeypatch)
    assert storage.add_level_alert("111", "above", 4500) is True
    assert storage.add_level_alert("111", "below", 4200) is True
    alerts = storage.get_user_alerts("111")
    assert len(alerts) == 2
    removed = storage.remove_level_alert("111", 1)
    assert removed["dir"] == "above"
    assert len(storage.get_user_alerts("111")) == 1
    assert storage.remove_level_alert("111", 99) is None


def test_level_alert_limit(monkeypatch):
    _MemStore(monkeypatch)
    for i in range(storage.MAX_ALERTS_PER_USER):
        assert storage.add_level_alert("111", "above", 5000 + i) is True
    assert storage.add_level_alert("111", "above", 9999) is False


def test_level_alert_trigger_one_shot(monkeypatch):
    _MemStore(monkeypatch)
    storage.add_level_alert("111", "above", 2500)
    storage.add_level_alert("222", "below", 2200)
    storage.add_level_alert("333", "above", 9999)

    # Alerts are USD/oz, so the THB price must not decide them.
    fired = storage.pop_triggered_alerts(4600.0, 2600.0)  # crosses 111's above-2500
    assert [(cid, a["price"]) for cid, a in fired] == [("111", 2500)]
    # one-shot: gone after firing; others survive
    assert storage.get_user_alerts("111") == []
    assert len(storage.get_user_alerts("222")) == 1
    assert len(storage.get_user_alerts("333")) == 1

    fired = storage.pop_triggered_alerts(4100.0, 2100.0)  # crosses 222's below-2200
    assert [cid for cid, _ in fired] == ["222"]


# ── Prediction accuracy tracker ─────────────────────────────────

def _fake_prediction():
    return {"predictions": {
        "4h": {"direction": "UP", "confidence": 60.0},
        "24h": {"direction": "DOWN", "confidence": 55.0},
    }}


def test_record_and_resolve_predictions():
    history = _hourly_history(48, step=1.0)  # steadily rising prices
    made_at = history[10]["ts"]              # 37h before the end -> both mature
    model_data = {"predictions": []}
    predictor.record_predictions(model_data, _fake_prediction(),
                                 history[10]["thb_gram"], now_iso=made_at)
    assert len(model_data["predictions"]) == 2

    changed = predictor.resolve_predictions(model_data, history)
    assert changed is True
    by_h = {p["horizon"]: p for p in model_data["predictions"]}
    assert by_h["4h"]["correct"] is True    # predicted UP, price rose
    assert by_h["24h"]["correct"] is False  # predicted DOWN, price rose

    rates = predictor.prediction_hit_rates(model_data)
    assert rates["4h"] == {"n": 1, "correct": 1, "hit_pct": 100.0}
    assert rates["24h"]["hit_pct"] == 0.0


def test_resolve_skips_unmatured():
    history = _hourly_history(48)
    model_data = {"predictions": []}
    predictor.record_predictions(model_data, _fake_prediction(), 4047.0,
                                 now_iso=history[-1]["ts"])  # made "now"
    predictor.resolve_predictions(model_data, history)
    assert all(not p["resolved"] for p in model_data["predictions"])


def test_resolve_voids_on_data_gap():
    history = _hourly_history(48)
    # Prediction made 30 days ago; nearest history point is way past target.
    old_ts = (datetime.now(BKK) - timedelta(days=30)).isoformat()
    model_data = {"predictions": []}
    predictor.record_predictions(model_data, _fake_prediction(), 4000.0,
                                 now_iso=old_ts)
    predictor.resolve_predictions(model_data, history)
    assert all(p.get("void") for p in model_data["predictions"])
    assert predictor.prediction_hit_rates(model_data) == {}


def test_prediction_log_capped():
    model_data = {"predictions": []}
    for _ in range(200):
        predictor.record_predictions(model_data, _fake_prediction(), 4000.0)
    assert len(model_data["predictions"]) <= predictor.PREDICTION_LOG_CAP
