"""/alert targets are USD/oz, and the weekly recap is quoted in USD/oz.

Alerts stored before the switch have no "unit" field and stay THB/gram — the
migration cases below are the point of these tests, since reinterpreting an old
฿4,500 target as $4,500 would make every "above" unreachable and every "below"
fire on the next run.
"""
from datetime import datetime, timedelta

import pytz

import bot_core
import gold_monitor
import storage

BKK = pytz.timezone("Asia/Bangkok")


class _MemStore:
    def __init__(self, monkeypatch):
        self.files = {}
        monkeypatch.setattr(
            storage, "_read_file",
            lambda f: self.files.get(
                f, [] if f in (storage.PRICE_HISTORY_FILE, storage.BUY_LOG_FILE) else {}))
        monkeypatch.setattr(storage, "_write_file",
                            lambda f, d: self.files.__setitem__(f, d))


def _capture(monkeypatch):
    sent = []
    monkeypatch.setattr(bot_core, "send_message", lambda text, cid="", **k: sent.append(text))
    return sent


# ── /alert is validated and stored in USD/oz ────────────────────

def test_alert_stored_in_usd(monkeypatch):
    _MemStore(monkeypatch)
    monkeypatch.setattr(bot_core.goldapi, "get_gold_price",
                        lambda *a, **k: (4500.0, 2400.0, 34.0))
    sent = _capture(monkeypatch)

    bot_core.cmd_alert("111", "above 3500", "my")

    stored = storage.get_user_alerts("111")
    assert stored == [{"dir": "above", "price": 3500.0, "unit": "usd",
                       "created": stored[0]["created"]}]
    assert "$3,500.00/oz" in sent[0]


def test_alert_bound_is_spot_not_thb(monkeypatch):
    """3000 sits above spot ($2400) but below the THB gram price (฿4,500)."""
    _MemStore(monkeypatch)
    monkeypatch.setattr(bot_core.goldapi, "get_gold_price",
                        lambda *a, **k: (4500.0, 2400.0, 34.0))
    sent = _capture(monkeypatch)

    bot_core.cmd_alert("111", "above 3000", "my")

    assert len(storage.get_user_alerts("111")) == 1
    assert "Alert သတ်မှတ်ပြီး" in sent[0]


def test_alert_below_spot_is_rejected(monkeypatch):
    _MemStore(monkeypatch)
    monkeypatch.setattr(bot_core.goldapi, "get_gold_price",
                        lambda *a, **k: (4500.0, 2400.0, 34.0))
    sent = _capture(monkeypatch)

    bot_core.cmd_alert("111", "above 2000", "my")

    assert storage.get_user_alerts("111") == []
    assert "$2,400.00/oz" in sent[0]


# ── Listing and deleting show each target's own unit ────────────

def test_alerts_list_shows_unit_per_alert(monkeypatch):
    store = _MemStore(monkeypatch)
    store.files[storage.LEVEL_ALERTS_FILE] = {"111": [
        {"dir": "above", "price": 3500.0, "unit": "usd"},
        {"dir": "below", "price": 4200.0},  # pre-switch record: THB/gram
    ]}
    sent = _capture(monkeypatch)

    bot_core.cmd_alerts("111", "my")

    assert "#1 ⬆️ above $3,500.00/oz" in sent[0]
    assert "#2 ⬇️ below ฿4,200/g" in sent[0]


def test_delalert_shows_unit(monkeypatch):
    store = _MemStore(monkeypatch)
    store.files[storage.LEVEL_ALERTS_FILE] = {"111": [
        {"dir": "above", "price": 3500.0, "unit": "usd"},
    ]}
    sent = _capture(monkeypatch)

    bot_core.cmd_delalert("111", "1", "my")

    assert "$3,500.00/oz" in sent[0]


# ── Triggering compares each alert against its own price ────────

def test_usd_alert_fires_on_spot(monkeypatch):
    _MemStore(monkeypatch)
    storage.add_level_alert("111", "above", 2500)

    assert storage.pop_triggered_alerts(9999.0, 2400.0) == []
    fired = storage.pop_triggered_alerts(1.0, 2500.0)
    assert [cid for cid, _ in fired] == ["111"]


def test_legacy_thb_alert_still_measured_in_thb(monkeypatch):
    store = _MemStore(monkeypatch)
    store.files[storage.LEVEL_ALERTS_FILE] = {"111": [
        {"dir": "above", "price": 4500.0},  # no unit -> THB/gram
    ]}

    # Spot is far past 4500 in dollars, but the THB price is not — no fire.
    assert storage.pop_triggered_alerts(4400.0, 9999.0) == []
    fired = storage.pop_triggered_alerts(4500.0, 1.0)
    assert [cid for cid, _ in fired] == ["111"]


def test_legacy_below_alert_does_not_fire_instantly(monkeypatch):
    """The regression the unit field exists to prevent."""
    store = _MemStore(monkeypatch)
    store.files[storage.LEVEL_ALERTS_FILE] = {"111": [
        {"dir": "below", "price": 4200.0},  # no unit -> THB/gram
    ]}

    assert storage.pop_triggered_alerts(4500.0, 2400.0) == []
    assert len(storage.get_user_alerts("111")) == 1


def test_usd_alert_kept_when_spot_unavailable(monkeypatch):
    _MemStore(monkeypatch)
    storage.add_level_alert("111", "below", 2000)

    assert storage.pop_triggered_alerts(4500.0, None) == []
    assert len(storage.get_user_alerts("111")) == 1


# ── Weekly recap is USD/oz only ─────────────────────────────────

def _week_history(with_usd=True):
    now = datetime.now(BKK)
    pts = []
    for i in range(168):
        p = {"ts": (now - timedelta(hours=167 - i)).isoformat(),
             "thb_gram": 4000.0 + i * 0.5}
        if with_usd:
            p["usd_oz"] = 2400.0 + i * 0.25
        pts.append(p)
    return pts


def test_weekly_recap_is_usd_only():
    block = gold_monitor.build_weekly_block(_week_history(), "en")

    assert "USD/oz" in block
    assert "฿" not in block
    assert "$2,400.00" in block   # week open
    assert "$2,441.75" in block   # week close / high


def test_weekly_recap_skipped_without_spot():
    """Pre-v2 history has no usd_oz — drop the block rather than print $0."""
    assert gold_monitor.build_weekly_block(_week_history(with_usd=False)) == ""
