"""Two one-off notices: a heads-up before each scheduled release, and the
owner's average-cost crossing.

The calendar reached people only as a banner on an alert or a line in the
daily messages, so a CPI print at 19:30 BKK went unmentioned unless the price
had already moved. And /portfolio showed the P&L only when asked; what changes
the owner's position is the price crossing their average cost.
"""
import datetime as _dt

import pytest
import pytz

import bot_core
import events
import gold_monitor
import storage

BKK = pytz.timezone("Asia/Bangkok")


def _at(day, hour, minute=0):
    return BKK.localize(_dt.datetime(2026, 10, day, hour, minute))


@pytest.fixture
def broadcasts(monkeypatch):
    sent = []
    monkeypatch.setattr(gold_monitor, "_bot_state", {})
    monkeypatch.setattr(gold_monitor, "notify",
                        lambda msg, category="alerts", owner_msg=None:
                        sent.append((category, msg("en"))))
    monkeypatch.setattr(events, "GENERATE_NFP", False)
    return sent


# ── Heads-up before a release ───────────────────────────────────

def test_a_release_is_announced_once_shortly_before(broadcasts, monkeypatch):
    monkeypatch.setattr(events, "CALENDAR", [("2026-10-14", "cpi")])  # 19:30 BKK
    assert gold_monitor.announce_upcoming_events(_at(14, 17, 0)) is False   # 2.5h out
    assert gold_monitor.announce_upcoming_events(_at(14, 18, 0)) is True    # 1.5h out
    category, text = broadcasts[0]
    assert category == "alerts"
    assert "Coming up: US CPI inflation" in text and "19:30 BKK — in 1h 30m" in text
    assert gold_monitor.announce_upcoming_events(_at(14, 18, 30)) is False
    assert len(broadcasts) == 1


def test_a_release_just_after_midnight_is_not_announced_twice(broadcasts, monkeypatch):
    """The day state resets at midnight; what was announced must survive it."""
    monkeypatch.setattr(events, "CALENDAR", [("2026-10-28", "fomc")])     # 01:00 BKK on the 29th
    gold_monitor.announce_upcoming_events(_at(28, 23, 30))
    gold_monitor.announce_upcoming_events(_at(29, 0, 5))
    assert len(broadcasts) == 1


def test_two_releases_in_the_window_are_both_announced(broadcasts, monkeypatch):
    monkeypatch.setattr(events, "CALENDAR", [("2026-10-14", "cpi"), ("2026-10-14", "pce")])
    gold_monitor.announce_upcoming_events(_at(14, 18, 0))
    assert len(broadcasts) == 2


def test_an_estimated_date_says_so(broadcasts, monkeypatch):
    monkeypatch.setattr(events, "CALENDAR", [])
    monkeypatch.setattr(events, "GENERATE_NFP", True)
    nfp = next(e for e in events.upcoming(_at(1, 0)) if e.type == "nfp")
    gold_monitor.announce_upcoming_events(nfp.when() - _dt.timedelta(hours=1))
    assert "(estimated)" in broadcasts[0][1]


# ── The owner's average cost ────────────────────────────────────

@pytest.fixture
def owner(monkeypatch):
    sent = []
    book = {"avg_cost": 4000.0, "total_grams": 10.0}
    monkeypatch.setattr(gold_monitor, "_bot_state", {})
    monkeypatch.setattr(gold_monitor, "TG_CHAT_ID", "OWNER")
    monkeypatch.setattr(storage, "get_portfolio", lambda: dict(book))
    monkeypatch.setattr(storage, "get_user_lang", lambda cid: "en")
    monkeypatch.setattr(bot_core, "send_message",
                        lambda text, chat_id="", **kw: sent.append((chat_id, text)))
    return sent, book


def test_crossing_the_average_cost_tells_the_owner(owner):
    sent, _ = owner
    cross = gold_monitor.alert_owner_on_cost_cross
    assert cross(4100.0) is True and sent == []            # first look: baseline only
    assert cross(4005.0) is False                          # inside the ±0.25% band
    assert cross(3980.0) is True
    assert sent[-1][0] == "OWNER" and "crossed below your average cost" in sent[-1][1]
    assert "฿3,980/g vs your average ฿4,000/g" in sent[-1][1]
    assert cross(3995.0) is False and len(sent) == 1       # back inside the band
    assert cross(4020.0) is True and "crossed above" in sent[-1][1]


def test_a_new_average_rebaselines_quietly(owner):
    """A buy moves the line; the price did not cross it."""
    sent, book = owner
    cross = gold_monitor.alert_owner_on_cost_cross
    cross(4100.0)
    book["avg_cost"] = 4200.0                              # bought higher
    assert cross(4100.0) is True and sent == []
    assert gold_monitor._bot_state["cost_side"] == "below"


def test_no_holdings_no_alerts(owner):
    sent, book = owner
    book["total_grams"] = 0
    gold_monitor._bot_state["cost_side"] = "above"
    assert gold_monitor.alert_owner_on_cost_cross(3000.0) is True   # state cleared
    assert "cost_side" not in gold_monitor._bot_state and sent == []
