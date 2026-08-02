"""Overnight / gap-down alert + prev_close carry-over across the day boundary."""
import datetime as _dt
import pytz
import pytest

import storage
import gold_monitor
import bot_core
import goldapi

BKK = pytz.timezone("Asia/Bangkok")


def _fake_dt(dtobj):
    class FakeDateTime(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return dtobj if tz is None else dtobj.astimezone(tz)
    return FakeDateTime


def test_load_day_state_carries_prev_close(monkeypatch):
    store = {storage.DAY_STATE_FILE: {"date": "2026-06-17", "last_price": 4490.0}}
    monkeypatch.setattr(storage, "_read_file", lambda f: store.get(f, {}))
    monkeypatch.setattr(storage, "_write_file", lambda f, d: store.__setitem__(f, d))
    monkeypatch.setattr(storage, "datetime", _fake_dt(BKK.localize(_dt.datetime(2026, 6, 18, 3, 0))))

    state = storage.load_day_state()
    assert state["date"] == "2026-06-18"
    assert state["open_price"] is None
    assert state["prev_close"] == 4490.0
    assert state["notified_gap"] is False


@pytest.fixture
def harness(monkeypatch):
    store = {}
    monkeypatch.setattr(storage, "_read_file",
                        lambda f: store.get(f, [] if f in (storage.PRICE_HISTORY_FILE, storage.BUY_LOG_FILE) else {}))
    monkeypatch.setattr(storage, "_write_file", lambda f, d: store.__setitem__(f, d))
    # notify() reads subscribers and prefs together in one Gist round-trip.
    monkeypatch.setattr(storage, "get_subscribers_and_prefs", lambda: ([], {}))
    monkeypatch.setattr(storage, "prefs_allow", lambda prefs, cat, hour: True)
    monkeypatch.setattr(storage, "pop_triggered_alerts", lambda price: [])

    sent = []
    monkeypatch.setattr(bot_core, "send_message",
                        lambda text, chat_id="": (sent.append(text), {"ok": True})[1])
    monkeypatch.setattr(gold_monitor, "TG_BOT_TOKEN", "x")
    monkeypatch.setattr(gold_monitor, "TG_CHAT_ID", "123")
    monkeypatch.setattr(signals_omit := gold_monitor.signals, "format_macro_block", lambda *a, **k: "")

    def run(price, day_state, hour=10, gap_threshold=1.0):
        store.clear()
        store[storage.DAY_STATE_FILE] = day_state
        monkeypatch.setattr(gold_monitor, "GAP_THRESHOLD", gap_threshold)
        monkeypatch.setattr(goldapi, "get_gold_price", lambda retries=2: (price, price / 32.0, 32.0))
        fdt = _fake_dt(BKK.localize(_dt.datetime(2026, 6, 18, hour, 0)))
        monkeypatch.setattr(storage, "datetime", fdt)
        monkeypatch.setattr(gold_monitor, "datetime", fdt)
        sent.clear()
        gold_monitor.main()
        return sent, store[storage.DAY_STATE_FILE]

    return run


def _today_state(**over):
    base = {
        "date": "2026-06-18", "open_price": 4500.0, "day_low": 4400.0, "day_high": 4520.0,
        "prev_close": 4500.0, "last_price": 4500.0,
        "morning_sent": True, "evening_sent": True, "notified_gap": False,
    }
    for i in range(1, 6):
        base[f"notified_drop_{i}"] = False
        base[f"notified_rise_{i}"] = False
    base.update(over)
    return base


def _has_gap(msgs):
    return any("Gap Down" in m for m in msgs)


def test_gap_alert_fires_on_overnight_drop(harness):
    sent, state = harness(price=4400.0, day_state=_today_state())  # -2.2% vs prev_close
    assert _has_gap(sent)
    assert state["notified_gap"] is True


def test_gap_alert_not_fired_within_threshold(harness):
    sent, state = harness(price=4480.0, day_state=_today_state())  # -0.44% < 1.0%
    assert not _has_gap(sent)
    assert state["notified_gap"] is False


def test_gap_alert_not_duplicated(harness):
    sent, _ = harness(price=4400.0, day_state=_today_state(notified_gap=True))
    assert not _has_gap(sent)


def test_last_price_recorded(harness):
    _, state = harness(price=4480.0, day_state=_today_state())
    assert state["last_price"] == 4480.0
