"""Two inputs that fail without raising an error, and the owner warnings that
now cover them.

  1. The event calendar. calendar_status() judged it by its LAST event. FOMC is
     listed through December 2027 while CPI and PCE stopped in December 2026,
     so on 2026-10-12 it reported 422 days of runway, not stale. From January,
     CPI and PCE would have stopped appearing with no warning. And the warning
     only ever showed in /events, to an owner who happened to run it.

  2. The price source. A source can fail by answering with a frozen quote,
     which fetch_spot_usd accepts. Since a repeated price now reads as a
     closed market (predictor.trading_prices), a source stuck on a weekday
     would freeze the TA reading and every alert, silently.
"""
from datetime import datetime, timedelta

import pytest
import pytz

import bot_core
import events
import gold_monitor
import goldapi
import predictor
import storage
from test_ml_dependencies import _store_with_history, _training_run

UTC = pytz.UTC
ET = pytz.timezone("US/Eastern")
BKK = pytz.timezone("Asia/Bangkok")


@pytest.fixture
def owner(monkeypatch):
    sent = []
    monkeypatch.setattr(bot_core, "TG_BOT_TOKEN", "x")
    monkeypatch.setattr(bot_core, "TG_CHAT_ID", "999")
    monkeypatch.setattr(storage, "get_user_lang", lambda cid: "en")
    monkeypatch.setattr(bot_core, "send_message",
                        lambda text, chat_id="": sent.append((chat_id, text)))
    return sent


# ── 1. The calendar ─────────────────────────────────────────────

@pytest.fixture
def cpi_ends_first(monkeypatch):
    """FOMC with a long runway, CPI about to run out — the real shape."""
    monkeypatch.setattr(events, "CALENDAR", [
        ("2026-12-10", "cpi"), ("2027-12-08", "fomc")])
    monkeypatch.setattr(events, "GENERATE_NFP", False)


NOV_1 = UTC.localize(datetime(2026, 11, 1, 12, 0))


def test_one_type_running_out_makes_the_calendar_stale(cpi_ends_first):
    status = events.calendar_status(NOV_1)
    assert status["short"] == ["cpi"]
    assert status["stale"] is True
    assert status["days_left"] == status["runway"]["cpi"] < events.STALE_AFTER_DAYS
    assert status["runway"]["fomc"] > 365


def test_types_the_table_never_lists_are_not_judged(cpi_ends_first):
    """PCE has no entries here at all: nothing is running out, it is unused."""
    assert set(events.calendar_status(NOV_1)["runway"]) == {"cpi", "fomc"}


def test_the_warning_names_what_runs_out(cpi_ends_first):
    text = bot_core.stale_calendar_text(events.calendar_status(NOV_1), "en")
    assert "US CPI inflation" in text and "FOMC" not in text
    assert "only 39d of dates left" in text   # Nov 1 -> Dec 10


def test_the_owner_is_warned_without_running_events(owner, cpi_ends_first):
    state = {}
    assert bot_core.warn_owner_if_calendar_stale(state, NOV_1) is True
    assert len(owner) == 1 and owner[0][0] == "999"
    assert "Calendar needs updating" in owner[0][1]

    # Once a week, not on every five-minute run.
    assert bot_core.warn_owner_if_calendar_stale(state, NOV_1 + timedelta(days=6)) is False
    assert bot_core.warn_owner_if_calendar_stale(state, NOV_1 + timedelta(days=8)) is True
    assert len(owner) == 2


def test_a_topped_up_calendar_rearms_the_warning(owner, monkeypatch):
    monkeypatch.setattr(events, "CALENDAR", [("2027-12-10", "cpi")])
    monkeypatch.setattr(events, "GENERATE_NFP", False)
    state = {"calendar_warned_at": NOV_1.isoformat()}
    assert bot_core.warn_owner_if_calendar_stale(state, NOV_1) is True  # save it
    assert "calendar_warned_at" not in state and owner == []


def test_every_release_type_is_listed_through_2027():
    """The data, not the mechanism. CPI and NFP for 2027 went in on
    2026-10-12 from BLS; PCE on 2026-10-26, once BEA published 2027."""
    status = events.calendar_status(UTC.localize(datetime(2026, 10, 26)))
    assert not status["stale"]
    assert all(days > 365 for days in status["runway"].values()), status["runway"]


# ── 2. The price source ─────────────────────────────────────────

def _et(y, m, d, h, minute=0):
    return ET.localize(datetime(y, m, d, h, minute))


@pytest.mark.parametrize("when, is_open", [
    (_et(2026, 10, 14, 10), True),     # Wednesday morning
    (_et(2026, 10, 14, 17, 30), False),  # the daily 17:00-18:00 pause
    (_et(2026, 10, 16, 16), True),     # Friday before the close
    (_et(2026, 10, 16, 17, 30), False),  # Friday after it
    (_et(2026, 10, 17, 12), False),    # Saturday
    (_et(2026, 10, 18, 17), False),    # Sunday before the open
    (_et(2026, 10, 18, 19), True),     # Sunday after it
])
def test_the_trading_week(when, is_open):
    assert goldapi.market_should_be_open(when) is is_open


def _hourly(start, prices):
    return [{"ts": (start + timedelta(hours=i)).isoformat(), "usd_oz": p,
             "thb_gram": p * 1.1} for i, p in enumerate(prices)]


def test_a_weekday_freeze_is_measured_in_trading_hours():
    start = _et(2026, 10, 14, 8)                     # Wednesday 08:00 ET
    history = _hourly(start, [4150.0, 4151.0] + [4152.0] * 4)
    now = start + timedelta(hours=6)
    # Frozen since the third point (10:00 ET): four open hours to 14:00.
    assert goldapi.hours_frozen(history, 4152.0, now) == 4.0


def test_a_price_that_just_moved_is_not_frozen():
    history = _hourly(_et(2026, 10, 14, 8), [4150.0] * 6)
    assert goldapi.hours_frozen(history, 4151.5, _et(2026, 10, 14, 14)) == 0.0


def test_a_weekend_of_one_price_is_normal():
    friday_close = _et(2026, 10, 16, 16, 59)
    history = _hourly(friday_close, [4150.0] * 40)    # through Sunday
    now = _et(2026, 10, 18, 17, 30)                   # before the Sunday open
    assert goldapi.hours_frozen(history, 4150.0, now) < goldapi.STUCK_AFTER_OPEN_HOURS


def test_a_freeze_across_the_weekend_counts_only_open_hours():
    since = _et(2026, 10, 16, 15)                     # Friday 15:00 ET
    history = _hourly(since, [4150.0] * 54)
    now = _et(2026, 10, 18, 20)                       # Sunday 20:00 ET
    # Friday 15:00-17:00 plus Sunday 18:00-20:00.
    assert goldapi.hours_frozen(history, 4150.0, now) == 4.0


def test_the_owner_hears_about_a_frozen_source_twice_a_day_at_most(owner):
    start = _et(2026, 10, 14, 6)
    history = _hourly(start, [4150.0] * 5)
    now = start + timedelta(hours=5)
    state = {}

    assert bot_core.warn_owner_if_feed_stuck(state, history, 4150.0, now) is True
    assert "Spot has not moved for 5h of trading" in owner[0][1]
    assert "$4,150.00/oz" in owner[0][1]
    assert bot_core.warn_owner_if_feed_stuck(
        state, history, 4150.0, now + timedelta(hours=6)) is False
    assert bot_core.warn_owner_if_feed_stuck(
        state, history, 4150.0, now + timedelta(hours=13)) is True
    assert len(owner) == 2

    # Moving again: re-armed, and the caller is told to save that.
    assert bot_core.warn_owner_if_feed_stuck(state, history, 4153.0, now) is True
    assert "feed_stuck_warned_at" not in state


def test_bad_rows_and_stamps_do_not_break_the_check(owner):
    now = _et(2026, 10, 14, 12)
    history = ["junk", {"usd_oz": 4150.0}, {"ts": "garbage", "usd_oz": 4150.0}]
    assert bot_core.warn_owner_if_feed_stuck({}, history, 4150.0, now) is False
    good = _hourly(now - timedelta(hours=5), [4150.0] * 5)
    state = {"feed_stuck_warned_at": "garbage"}
    assert bot_core.warn_owner_if_feed_stuck(state, good, 4150.0, now) is True


def test_the_monitor_runs_both_checks_and_saves_the_stamp(owner, monkeypatch):
    """Wired into main(): a source frozen through Wednesday afternoon ET."""
    monkeypatch.setattr(predictor, "ml_available", lambda: False)
    store = _store_with_history()
    for row in store[storage.PRICE_HISTORY_FILE][-5:]:
        row["usd_oz"] = 2400.0                        # the price main() fetches

    sent, files = _training_run(monkeypatch, store)

    assert any("Spot has not moved" in text for text in sent), sent
    assert files[storage.BOT_STATE_FILE]["feed_stuck_warned_at"].startswith("2026-06-18T03:00")
