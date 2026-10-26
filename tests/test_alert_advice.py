"""Drop, rise and gap alerts: the facts go to everyone, the DCA prompts to the
owner only.

Every alert closed with a buy or sell line — "Open your gold app and buy!",
"Consider taking profit!" — and the drop and gap alerts with "Log it with
/bought", an owner command. Replayed over two years of hourly gold, the price
did no better after any of these alerts than after an ordinary hour: they were
the owner's own DCA plan, broadcast to every subscriber as advice.
"""
import datetime as _dt

import pytz

import bot_core
import gold_monitor
import goldapi
import storage

BKK = pytz.timezone("Asia/Bangkok")
ADVICE = ("Open your gold app", "DCA", "/bought", "profit", "portfolio value")


def _run(monkeypatch, price, prev_close=4500.0):
    """One monitor run at 10:00 BKK with the day opened at 4,500 THB/g."""
    at = BKK.localize(_dt.datetime(2026, 10, 14, 10, 0))

    class _Clock(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return at if tz is None else at.astimezone(tz)

    files = {storage.DAY_STATE_FILE: {
        "date": "2026-10-14", "open_price": 4500.0, "day_low": 4500.0,
        "day_high": 4500.0, "prev_close": prev_close, "last_price": 4500.0,
        "morning_sent": True, "evening_sent": True,
        "notified_gap": prev_close == 4500.0}}
    monkeypatch.setattr(storage, "_read_file", lambda f, fresh=False: files.get(
        f, [] if f in (storage.PRICE_HISTORY_FILE, storage.BUY_LOG_FILE) else {}))
    monkeypatch.setattr(storage, "_write_file", lambda f, d: files.__setitem__(f, d) or True)
    monkeypatch.setattr(storage, "get_subscribers_and_prefs", lambda: (
        ["alice"], {"owner": {"lang": "en"}, "alice": {"lang": "en"}}))
    monkeypatch.setattr(storage, "pop_triggered_alerts", lambda *p: [])
    monkeypatch.setattr(goldapi, "get_gold_price", lambda retries=2: (price, 2400.0, 34.0))
    monkeypatch.setattr(storage, "datetime", _Clock)
    monkeypatch.setattr(gold_monitor, "datetime", _Clock)
    monkeypatch.setattr(gold_monitor, "TG_BOT_TOKEN", "x")
    monkeypatch.setattr(gold_monitor, "TG_CHAT_ID", "owner")
    monkeypatch.setattr(gold_monitor, "_bot_state", {})
    monkeypatch.setattr(gold_monitor.time, "sleep", lambda s: None)
    monkeypatch.setattr(gold_monitor.signals, "format_macro_block", lambda *a, **k: "")
    monkeypatch.setattr(bot_core, "warn_owner_if_webhook_broken", lambda st: False)
    received = {}
    monkeypatch.setattr(bot_core, "send_message",
                        lambda text, chat_id="", **kw: (received.setdefault(chat_id, []).append(text),
                                                        {"ok": True})[1])
    gold_monitor.main()
    return received


def _alerts(received, chat, mark):
    return [m for m in received.get(chat, []) if mark in m]


def test_drop_alerts_carry_the_dca_prompt_for_the_owner_only(monkeypatch):
    got = _run(monkeypatch, price=4440.0)                 # -1.33%: levels 1 and 2
    mine, theirs = _alerts(got, "owner", "Drop    :"), _alerts(got, "alice", "Drop    :")
    assert len(mine) == len(theirs) == 2
    assert "Open your gold app and buy!" in mine[0] and "/bought" in mine[0]
    for msg in theirs:
        assert "4,440" in msg and "1.33%" in msg, "the facts still go out"
        assert not any(word in msg for word in ADVICE), msg


def test_rise_alerts_carry_the_take_profit_line_for_the_owner_only(monkeypatch):
    got = _run(monkeypatch, price=4560.0)                 # +1.33%: levels 1 and 2
    mine, theirs = _alerts(got, "owner", "📈"), _alerts(got, "alice", "📈")
    assert any("Consider taking profit!" in m for m in mine)
    assert theirs and not any(word in m for m in theirs for word in ADVICE), theirs


def test_the_gap_alert_too(monkeypatch):
    got = _run(monkeypatch, price=4500.0, prev_close=4600.0)   # -2.17% overnight
    mine, theirs = _alerts(got, "owner", "Gap Down"), _alerts(got, "alice", "Gap Down")
    assert "check for a DCA opportunity" in mine[0] and "/bought" in mine[0]
    assert theirs and not any(word in theirs[0] for word in ADVICE), theirs[0]
