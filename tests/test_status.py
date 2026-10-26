"""/status: the bot's own health on one screen, for the owner.

Each watchdog speaks only when something is wrong. This answers "is it all
fine right now?" — last run, hourly history, a moving price, the models, the
calendar — from the Gist alone.
"""
import datetime as _dt

import pytest
import pytz

import bot_core
import storage

BKK = pytz.timezone("Asia/Bangkok")
NOW = BKK.localize(_dt.datetime(2026, 10, 14, 12, 0))   # Wednesday, market open


class _Clock(_dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz is None else NOW.astimezone(tz)


def _history(frozen=False):
    rows = []
    for i in range(30, 0, -1):
        t = NOW - _dt.timedelta(hours=i, minutes=-55)
        usd = 2400.0 if frozen and i <= 6 else 2400.0 + i
        rows.append({"ts": t.isoformat(), "thb_gram": usd * 1.1, "usd_oz": usd})
    return rows


@pytest.fixture
def run_status(monkeypatch):
    def run(files):
        monkeypatch.setattr(storage, "_read_file", lambda f, fresh=False: files.get(
            f, [] if f in (storage.PRICE_HISTORY_FILE, storage.BUY_LOG_FILE) else {}))
        monkeypatch.setattr(storage, "datetime", _Clock)
        monkeypatch.setattr(bot_core, "datetime", _Clock)
        sent = []
        monkeypatch.setattr(bot_core, "send_message",
                            lambda text, chat_id="", **kw: sent.append(text))
        bot_core.cmd_status("OWNER", "en")
        return sent[-1]
    return run


FULL = {
    storage.DAY_STATE_FILE: {"date": "2026-10-14",
                             "last_run_at": (NOW - _dt.timedelta(minutes=4)).isoformat(),
                             "run_gap_warned_at": "2026-10-12T19:23:00+00:00"},
    storage.MODEL_DATA_FILE: {
        "last_trained": "2026-10-14T03:00:12+07:00",
        "models": {"24h": {"has_edge": False}, "4h": {"has_edge": False},
                   "12h": {"has_edge": True}},
        "predictions": [{"horizon": "24h", "resolved": True, "correct": True},
                        {"horizon": "24h", "resolved": True, "correct": False}]},
}


def test_the_owner_sees_every_check(run_status):
    msg = run_status({**FULL, storage.PRICE_HISTORY_FILE: _history()})
    assert "Last monitor run: 0h 4m ago (10-14 11:56 BKK)" in msg
    assert "History: 30 points · 24 in the last 24h" in msg
    assert "Spot $2,401.00/oz — moving" in msg
    assert "ML trained 10-14 03:00 · edge: 4h ✗ · 12h ✅ · 24h ✗" in msg
    assert "Live hit-rate: 24h 50.0% (n=2)" in msg
    assert "Calendar left: FOMC" in msg and "PCE" in msg
    assert "run gap 10-13 02:23" in msg


def test_a_frozen_price_is_called_out(run_status):
    msg = run_status({**FULL, storage.PRICE_HISTORY_FILE: _history(frozen=True)})
    assert "unchanged for 5h of trading ⚠️" in msg   # frozen since 5h05m ago


def test_an_empty_gist_does_not_break_it(run_status):
    msg = run_status({})
    assert "not recorded yet" in msg and "ML: not trained yet" in msg
    assert "History: 0 points" in msg


def test_status_is_owner_only():
    assert "/status" in bot_core.OWNER_COMMANDS
    assert "/status" not in bot_core.PUBLIC_COMMANDS
