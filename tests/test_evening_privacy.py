"""The evening summary must not broadcast the owner's portfolio.

/portfolio and /bought are owner-only, but the evening summary carried the
owner's holdings and P&L — and went through notify() to every subscriber.
Anyone can /subscribe, so anyone received the owner's grams and profit.
"""
import datetime as _dt

import pytz

import bot_core
import gold_monitor
import goldapi
import storage

BKK = pytz.timezone("Asia/Bangkok")
PORTFOLIO_MARK = "Portfolio:"          # the heading of the monitor.portfolio block


def _evening(monkeypatch, *, owner="owner", subscribers=("alice", "bob"), langs=None):
    """Run the monitor at 20:00 BKK and return {chat_id: message}."""
    at = BKK.localize(_dt.datetime(2026, 9, 25, 20, 0))

    class _Clock(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return at if tz is None else at.astimezone(tz)

    files = {
        storage.DAY_STATE_FILE: {
            "date": "2026-09-25", "open_price": 4500.0, "day_low": 4480.0,
            "day_high": 4520.0, "prev_close": 4500.0, "last_price": 4500.0,
            "morning_sent": True, "evening_sent": False, "notified_gap": True},
        storage.BUY_LOG_FILE: [{"type": "buy", "ts": "2026-09-01T10:00:00+07:00",
                                "amount_thb": 45000, "price_per_gram": 4500.0,
                                "grams": 10.0}],
    }
    monkeypatch.setattr(storage, "_read_file", lambda f, fresh=False: files.get(
        f, [] if f in (storage.PRICE_HISTORY_FILE, storage.BUY_LOG_FILE) else {}))
    monkeypatch.setattr(storage, "_write_file", lambda f, d: files.__setitem__(f, d) or True)
    prefs = {cid: {"lang": lang} for cid, lang in (langs or {}).items()}
    monkeypatch.setattr(storage, "get_subscribers_and_prefs",
                        lambda: (list(subscribers), prefs))
    monkeypatch.setattr(storage, "pop_triggered_alerts", lambda *p: [])
    monkeypatch.setattr(goldapi, "get_gold_price", lambda retries=2: (4600.0, 2450.0, 34.0))
    monkeypatch.setattr(storage, "datetime", _Clock)
    monkeypatch.setattr(gold_monitor, "datetime", _Clock)
    monkeypatch.setattr(gold_monitor, "TG_BOT_TOKEN", "x")
    monkeypatch.setattr(gold_monitor, "TG_CHAT_ID", owner)
    monkeypatch.setattr(gold_monitor.time, "sleep", lambda s: None)
    monkeypatch.setattr(gold_monitor.signals, "format_macro_block", lambda *a, **k: "")
    monkeypatch.setattr(bot_core, "warn_owner_if_webhook_broken", lambda st: False)

    received = {}
    monkeypatch.setattr(bot_core, "send_message",
                        lambda text, chat_id="": (received.setdefault(chat_id, []).append(text),
                                                  {"ok": True})[1])
    gold_monitor.main()
    return {cid: next(m for m in msgs if "Evening" in m or "ညနေ" in m or "ตอนเย็น" in m)
            for cid, msgs in received.items()}


def test_subscribers_do_not_get_the_owners_portfolio(monkeypatch):
    got = _evening(monkeypatch)
    for sub in ("alice", "bob"):
        assert PORTFOLIO_MARK not in got[sub], f"{sub} received the owner's portfolio"


def test_the_owner_still_gets_it(monkeypatch):
    got = _evening(monkeypatch)
    assert PORTFOLIO_MARK in got["owner"]
    assert "10.0000g" in got["owner"]          # the owner's actual holding


def test_a_subscriber_sharing_the_owners_language_is_not_handed_it(monkeypatch):
    """The render cache was keyed by language alone, and the owner is always
    rendered first — so a naive owner-only body would be cached under "en" and
    served straight to the next English-speaking subscriber."""
    got = _evening(monkeypatch, langs={"owner": "en", "alice": "en", "bob": "en"})
    assert PORTFOLIO_MARK in got["owner"]
    assert PORTFOLIO_MARK not in got["alice"]
    assert PORTFOLIO_MARK not in got["bob"]


def test_everything_else_in_the_summary_still_reaches_subscribers(monkeypatch):
    """Only the portfolio block is private — the market summary is the point."""
    got = _evening(monkeypatch)
    for field in ("฿4,600/g", "$2,450.00/oz"):
        assert field in got["alice"], field


def test_no_owner_configured_means_nobody_gets_it(monkeypatch):
    got = _evening(monkeypatch, owner="")
    assert got and all(PORTFOLIO_MARK not in m for m in got.values())


def test_an_owner_who_also_subscribed_gets_one_message_with_it(monkeypatch):
    got = _evening(monkeypatch, subscribers=("owner", "alice"))
    assert set(got) == {"owner", "alice"}
    assert PORTFOLIO_MARK in got["owner"]
    assert PORTFOLIO_MARK not in got["alice"]


def test_notify_without_owner_msg_sends_everyone_the_same(monkeypatch):
    """Every other broadcast is unchanged."""
    monkeypatch.setattr(gold_monitor, "TG_BOT_TOKEN", "x")
    monkeypatch.setattr(gold_monitor, "TG_CHAT_ID", "owner")
    monkeypatch.setattr(gold_monitor.time, "sleep", lambda s: None)
    monkeypatch.setattr(storage, "get_subscribers_and_prefs", lambda: (["alice"], {}))
    sent = {}
    monkeypatch.setattr(bot_core, "send_message",
                        lambda text, chat_id="": (sent.__setitem__(chat_id, text), {"ok": True})[1])

    gold_monitor.notify(lambda lang: f"alert in {lang}", "alerts")

    assert sent["owner"] == sent["alice"]
