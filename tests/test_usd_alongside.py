"""Every live THB/gram price is shown next to the USD/oz spot it came from.

Without the spot alongside, a THB move is ambiguous: gold could have moved, or
the baht could have. These tests pin the pairing at each display site.
"""
import datetime as _dt

import pytz

import bot_core
import goldapi
import gold_monitor
import i18n
import storage
from gold_format import usd_oz_suffix

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


# ── The suffix helper ───────────────────────────────────────────

def test_usd_oz_suffix_renders_and_degrades():
    assert usd_oz_suffix(2400.5) == " | $2,400.50/oz"
    # Pre-v2 history rows carry no spot — print nothing rather than "$0/oz".
    assert usd_oz_suffix(None) == ""
    assert usd_oz_suffix(0) == ""


# ── Catalogue invariant ─────────────────────────────────────────

def test_price_templates_pair_gram_with_oz():
    """A template quoting a THB/gram price must also quote USD/oz."""
    offenders = []
    for key, entry in i18n.STRINGS.items():
        if not key.startswith(("monitor.", "price.", "chart.", "predict.")):
            continue
        for code, text in entry.items():
            if "/g" in text and "/oz" not in text and "{usd}" not in text:
                offenders.append(f"{key}/{code}")
    # price.per_gram / price.baht_weight are single lines of the /price block,
    # which carries its own price.spot line — assert that pairing separately.
    offenders = [o for o in offenders
                 if not o.startswith(("price.per_gram", "price.baht_weight"))]
    assert not offenders, offenders


def test_price_command_shows_spot(monkeypatch):
    _MemStore(monkeypatch)
    monkeypatch.setattr(goldapi, "get_gold_price", lambda *a, **k: (4500.0, 2400.0, 34.0))
    sent = []
    monkeypatch.setattr(bot_core, "send_message", lambda text, cid="", **k: sent.append(text))

    bot_core.cmd_price("111", "my")

    assert "1g: ฿4,500" in sent[0]
    assert "$2,400.00/oz" in sent[0]


# ── /portfolio ──────────────────────────────────────────────────

def test_portfolio_current_price_shows_spot(monkeypatch):
    store = _MemStore(monkeypatch)
    store.files[storage.BUY_LOG_FILE] = [
        {"type": "buy", "ts": "2026-01-01T10:00:00+07:00",
         "amount_thb": 5000, "price_per_gram": 5000.0, "grams": 1.0},
    ]
    monkeypatch.setattr(bot_core.goldapi, "get_gold_price",
                        lambda *a, **k: (5300.0, 2400.0, 34.0))
    sent = []
    monkeypatch.setattr(bot_core, "send_message", lambda text, cid="", **k: sent.append(text))

    bot_core.cmd_portfolio("111", "my")

    assert "💰 Current price: ฿5,300/gram | $2,400.00/oz" in sent[0]


# ── /history ────────────────────────────────────────────────────

def test_history_rows_show_daily_spot(monkeypatch):
    store = _MemStore(monkeypatch)
    store.files[storage.PRICE_HISTORY_FILE] = [
        {"ts": "2026-01-01T10:00:00+07:00", "thb_gram": 4000.0, "usd_oz": 2350.0},
        {"ts": "2026-01-01T11:00:00+07:00", "thb_gram": 4010.0, "usd_oz": 2360.0},
        {"ts": "2026-01-02T10:00:00+07:00", "thb_gram": 4020.0, "usd_oz": 2370.0},
    ]
    sent = []
    monkeypatch.setattr(bot_core, "send_message", lambda text, cid="", **k: sent.append(text))

    bot_core.cmd_history("111", "7", "my")

    # Each daily row closes on that day's last spot, not the latest one.
    assert "2026-01-01: ฿4,010 | $2,360.00/oz" in sent[0]
    assert "2026-01-02: ฿4,020 | $2,370.00/oz" in sent[0]


def test_history_row_omits_spot_for_legacy_entries(monkeypatch):
    store = _MemStore(monkeypatch)
    store.files[storage.PRICE_HISTORY_FILE] = [
        {"ts": "2026-01-01T10:00:00+07:00", "thb_gram": 4000.0},
        {"ts": "2026-01-02T10:00:00+07:00", "thb_gram": 4020.0},
    ]
    sent = []
    monkeypatch.setattr(bot_core, "send_message", lambda text, cid="", **k: sent.append(text))

    bot_core.cmd_history("111", "7", "my")

    assert "/oz" not in sent[0]
    assert "2026-01-01: ฿4,000 (" in sent[0]


# ── /chart caption ──────────────────────────────────────────────

def test_chart_caption_shows_spot(monkeypatch):
    store = _MemStore(monkeypatch)
    store.files[storage.PRICE_HISTORY_FILE] = [
        {"ts": f"2026-01-01T{i:02d}:00:00+07:00", "thb_gram": 4000.0 + i,
         "usd_oz": 2400.0 + i}
        for i in range(24)
    ]
    monkeypatch.setattr(bot_core, "_quickchart_short_url",
                        lambda cfg: "https://quickchart.io/chart/abc")
    captions = []
    monkeypatch.setattr(
        bot_core, "send_photo",
        lambda url, caption, cid="": captions.append(caption) or {"ok": True})

    bot_core.cmd_chart("111", "1", "my")

    assert "$2,423.00/oz" in captions[0]


# ── Level alert fired by the monitor ────────────────────────────

def test_level_alert_shows_spot(monkeypatch):
    store = _MemStore(monkeypatch)
    store.files[storage.DAY_STATE_FILE] = {
        "date": "2026-06-18", "open_price": 4500.0, "day_low": 4400.0,
        "day_high": 4520.0, "prev_close": 4500.0, "last_price": 4500.0,
        "morning_sent": True, "evening_sent": True, "notified_gap": True,
    }
    monkeypatch.setattr(storage, "get_subscribers_and_prefs", lambda: ([], {}))
    monkeypatch.setattr(storage, "get_user_lang", lambda cid: "my")
    monkeypatch.setattr(
        storage, "pop_triggered_alerts",
        lambda *prices: [("111", {"dir": "above", "price": 2350.0, "unit": "usd"})])
    monkeypatch.setattr(goldapi, "get_gold_price", lambda retries=2: (4550.0, 2400.0, 34.0))
    monkeypatch.setattr(gold_monitor, "TG_BOT_TOKEN", "x")
    monkeypatch.setattr(gold_monitor, "TG_CHAT_ID", "123")

    class FakeDateTime(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            at = BKK.localize(_dt.datetime(2026, 6, 18, 10, 0))
            return at if tz is None else at.astimezone(tz)

    monkeypatch.setattr(storage, "datetime", FakeDateTime)
    monkeypatch.setattr(gold_monitor, "datetime", FakeDateTime)

    sent = []
    monkeypatch.setattr(bot_core, "send_message",
                        lambda text, chat_id="": (sent.append(text), {"ok": True})[1])

    gold_monitor.main()

    alert = next(m for m in sent if "Price Alert" in m)
    assert "💰 လက်ရှိဈေး : ฿4,550/g" in alert
    assert "🌐 Spot      : $2,400.00/oz" in alert
