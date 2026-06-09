"""Regression test: morning message must send at 7am even if an overnight run
(near midnight BKK) already anchored open_price. See gold_monitor morning block.
"""
import datetime as _dt
import pytz
import pytest

import storage
import gold_monitor
import bot_core
import goldapi

BKK = pytz.timezone("Asia/Bangkok")


@pytest.fixture
def harness(monkeypatch):
    store = {}

    def fake_read(f):
        return store.get(f, [] if f in (storage.PRICE_HISTORY_FILE, storage.BUY_LOG_FILE) else {})

    monkeypatch.setattr(storage, "_read_file", fake_read)
    monkeypatch.setattr(storage, "_write_file", lambda f, d: store.__setitem__(f, d))

    sent = []
    monkeypatch.setattr(bot_core, "send_message",
                        lambda text, chat_id="": (sent.append(text), {"ok": True})[1])
    monkeypatch.setattr(gold_monitor, "TG_BOT_TOKEN", "x")
    monkeypatch.setattr(gold_monitor, "TG_CHAT_ID", "123")
    monkeypatch.setattr(goldapi, "get_gold_price", lambda retries=2: (2000.0, 2000.0, 31.1))

    class Clock:
        val = None

    class FakeDateTime(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return Clock.val if tz is None else Clock.val.astimezone(tz)

    monkeypatch.setattr(storage, "datetime", FakeDateTime)
    monkeypatch.setattr(gold_monitor, "datetime", FakeDateTime)

    def run_at(day, hour, minute=0):
        Clock.val = BKK.localize(_dt.datetime(2026, 6, day, hour, minute))
        sent.clear()
        gold_monitor.main()
        return list(sent)

    return run_at, store


def _is_morning(msgs):
    return any("မနက်ခင်း" in m for m in msgs)


def _is_evening(msgs):
    return any("အနှစ်ချုပ်" in m for m in msgs)


def test_morning_sends_after_overnight_run(harness):
    run_at, store = harness
    # Overnight run (00:30 BKK) anchors open_price but must NOT send morning.
    assert not _is_morning(run_at(10, 0, 30))
    assert store[storage.DAY_STATE_FILE]["morning_sent"] is False
    # The real 7am run must still send the morning message (the bug).
    assert _is_morning(run_at(10, 7, 0))
    assert store[storage.DAY_STATE_FILE]["morning_sent"] is True


def test_morning_not_duplicated(harness):
    run_at, _ = harness
    run_at(10, 7, 0)
    assert not _is_morning(run_at(10, 8, 5))  # already sent today


def test_morning_sends_on_fresh_7am(harness):
    run_at, _ = harness
    assert _is_morning(run_at(11, 7, 0))


def test_evening_sends_at_8pm_not_5pm(harness):
    run_at, _ = harness
    run_at(10, 7, 0)
    # 5pm must NOT trigger the evening summary anymore...
    assert not _is_evening(run_at(10, 17, 0))
    # ...8pm does.
    assert _is_evening(run_at(10, 20, 0))
