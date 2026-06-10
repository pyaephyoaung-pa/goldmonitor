"""Tests for v2.2: per-user notification prefs (mute/quiet hours),
Sunday weekly summary block, inline keyboard callback dispatch."""

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


# ── Preferences storage ─────────────────────────────────────────

def test_prefs_defaults(monkeypatch):
    _MemStore(monkeypatch)
    prefs = storage.get_user_prefs("111")
    assert prefs == storage.PREF_DEFAULTS


def test_set_and_get_pref(monkeypatch):
    _MemStore(monkeypatch)
    storage.set_user_pref("111", "morning", False)
    prefs = storage.get_user_prefs("111")
    assert prefs["morning"] is False
    assert prefs["evening"] is True  # untouched defaults survive


def test_unsubscribe_clears_prefs(monkeypatch):
    _MemStore(monkeypatch)
    storage.add_subscriber("111")
    storage.set_user_pref("111", "quiet", "22-7")
    assert storage.remove_subscriber("111") is True
    assert storage.get_user_prefs("111") == storage.PREF_DEFAULTS


# ── Quiet hours ─────────────────────────────────────────────────

def test_parse_quiet_hours():
    assert storage.parse_quiet_hours("22-7") == (22, 7)
    assert storage.parse_quiet_hours("9-17") == (9, 17)
    assert storage.parse_quiet_hours("25-7") is None
    assert storage.parse_quiet_hours("7-7") is None
    assert storage.parse_quiet_hours("junk") is None


def test_in_quiet_hours_wrapping():
    assert storage.in_quiet_hours("22-7", 23) is True
    assert storage.in_quiet_hours("22-7", 3) is True
    assert storage.in_quiet_hours("22-7", 7) is False
    assert storage.in_quiet_hours("22-7", 12) is False
    assert storage.in_quiet_hours("9-17", 12) is True
    assert storage.in_quiet_hours(None, 12) is False


def test_prefs_allow():
    assert storage.prefs_allow({}, "morning", 8) is True
    assert storage.prefs_allow({"morning": False}, "morning", 8) is False
    assert storage.prefs_allow({"morning": False}, "evening", 8) is True
    assert storage.prefs_allow({"quiet": "22-7"}, "alerts", 23) is False
    assert storage.prefs_allow({"quiet": "22-7"}, "alerts", 12) is True


# ── notify() respects prefs ─────────────────────────────────────

def test_notify_skips_muted_subscriber(monkeypatch):
    _MemStore(monkeypatch)
    storage.add_subscriber("222")
    storage.add_subscriber("333")
    storage.set_user_pref("333", "alerts", False)

    sent = []
    monkeypatch.setattr(bot_core, "send_message",
                        lambda text, chat_id="", **kw: (sent.append(chat_id), {"ok": True})[1])
    monkeypatch.setattr(gold_monitor, "TG_BOT_TOKEN", "x")
    monkeypatch.setattr(gold_monitor, "TG_CHAT_ID", "111")
    monkeypatch.setattr(gold_monitor.time, "sleep", lambda s: None)

    gold_monitor.notify("test", "alerts")
    assert "111" in sent and "222" in sent
    assert "333" not in sent  # muted alerts


# ── Mute/quiet commands ─────────────────────────────────────────

def test_cmd_mute_and_quiet(monkeypatch):
    _MemStore(monkeypatch)
    sent = []
    monkeypatch.setattr(bot_core, "send_message",
                        lambda text, chat_id="", **kw: sent.append(text))

    bot_core.cmd_mute("111", "evening")
    assert storage.get_user_prefs("111")["evening"] is False
    bot_core.cmd_unmute("111", "evening")
    assert storage.get_user_prefs("111")["evening"] is True
    bot_core.cmd_mute("111", "bogus")
    assert any("Usage" in t for t in sent)

    bot_core.cmd_quiet("111", "22-7")
    assert storage.get_user_prefs("111")["quiet"] == "22-7"
    bot_core.cmd_quiet("111", "off")
    assert storage.get_user_prefs("111")["quiet"] is None


# ── Weekly summary block ────────────────────────────────────────

def _week_history():
    now = datetime.now(BKK)
    pts = []
    for i in range(168):
        t = now - timedelta(hours=167 - i)
        pts.append({"ts": t.isoformat(), "thb_gram": 4000.0 + i * 0.5})
    return pts


def test_weekly_block_contents():
    block = gold_monitor.build_weekly_block(_week_history())
    assert "သီတင်းပတ်" in block
    assert "Week: +" in block       # rising series -> positive change
    assert "Best day" in block and "Worst day" in block


def test_weekly_block_needs_data():
    assert gold_monitor.build_weekly_block([]) == ""
    one_day = [{"ts": "2026-06-10T0%d:00:00+07:00" % i, "thb_gram": 4000.0}
               for i in range(10)]
    assert gold_monitor.build_weekly_block(one_day) == ""


# ── Inline keyboard callbacks ───────────────────────────────────

def test_callback_query_dispatches_command(monkeypatch):
    monkeypatch.setattr(bot_core, "send_message",
                        lambda text, chat_id="", **kw: None)
    acked = []
    monkeypatch.setattr(bot_core, "answer_callback_query",
                        lambda cb_id: acked.append(cb_id))
    called = {}
    monkeypatch.setattr(bot_core, "cmd_price", lambda cid: called.setdefault("cid", cid))

    update = {"callback_query": {
        "id": "cb1",
        "data": "/price",
        "message": {"chat": {"id": "555"}},
    }}
    assert bot_core.dispatch_update(update) is True
    assert called.get("cid") == "555"
    assert acked == ["cb1"]


def test_callback_query_ignores_bad_data(monkeypatch):
    monkeypatch.setattr(bot_core, "answer_callback_query", lambda cb_id: None)
    assert bot_core.dispatch_update(
        {"callback_query": {"id": "x", "data": "not-a-command",
                            "message": {"chat": {"id": "555"}}}}) is False


def test_help_includes_keyboard(monkeypatch):
    captured = {}

    def fake_send(text, chat_id="", reply_markup=None):
        captured["markup"] = reply_markup

    monkeypatch.setattr(bot_core, "send_message", fake_send)
    bot_core.cmd_help("111")
    assert captured["markup"] == bot_core.MAIN_KEYBOARD
    assert any("/price" in str(b) for row in captured["markup"]["inline_keyboard"] for b in row)
