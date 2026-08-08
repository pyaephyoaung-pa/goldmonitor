"""Tests for the scheduled economic-event calendar.

These pin the MECHANISM (timezone maths, windows, staleness detection) against
a fixed calendar, so they never depend on the real dates in events.CALENDAR
being current — that data is maintained by hand and verified against the
official sources, not by the suite.
"""

from datetime import datetime, timedelta

import pytest
import pytz

import bot_core
import events
import i18n
import predictor
import storage

UTC = pytz.UTC
EASTERN = pytz.timezone("US/Eastern")
BKK = pytz.timezone("Asia/Bangkok")


@pytest.fixture
def fixed_calendar(monkeypatch):
    """A tiny, deterministic calendar: one FOMC in winter, one in summer."""
    monkeypatch.setattr(events, "CALENDAR", [
        ("2026-01-28", "fomc"),   # EST (UTC-5)
        ("2026-06-17", "fomc"),   # EDT (UTC-4)
    ])
    monkeypatch.setattr(events, "GENERATE_NFP", False)


# ── Timezone maths ──────────────────────────────────────────────

def test_release_time_respects_us_dst(fixed_calendar):
    """14:00 ET is 19:00 UTC in winter but 18:00 UTC in summer."""
    winter, summer = events.all_events()
    assert winter.when_utc == UTC.localize(datetime(2026, 1, 28, 19, 0))
    assert summer.when_utc == UTC.localize(datetime(2026, 6, 17, 18, 0))


def test_when_converts_to_bangkok(fixed_calendar):
    winter = events.all_events()[0]
    bkk = winter.when(BKK)
    assert bkk.hour == 2 and bkk.day == 29, "19:00 UTC is 02:00 BKK next day"


def test_bad_calendar_entry_is_skipped(monkeypatch, capsys):
    monkeypatch.setattr(events, "CALENDAR", [
        ("not-a-date", "fomc"), ("2026-06-17", "fomc"), ("2026-07-01", "bogus"),
    ])
    monkeypatch.setattr(events, "GENERATE_NFP", False)
    got = events.all_events()
    assert len(got) == 1, "one good entry survives"
    out = capsys.readouterr().out
    assert "bad calendar entry" in out and "unknown event type" in out


def test_events_are_sorted(monkeypatch):
    monkeypatch.setattr(events, "CALENDAR", [
        ("2026-06-17", "fomc"), ("2026-01-28", "fomc"), ("2026-03-18", "fomc"),
    ])
    monkeypatch.setattr(events, "GENERATE_NFP", False)
    whens = [e.when_utc for e in events.all_events()]
    assert whens == sorted(whens)


# ── upcoming / next ─────────────────────────────────────────────

def test_upcoming_excludes_past(fixed_calendar):
    now = UTC.localize(datetime(2026, 3, 1, 12, 0))
    up = events.upcoming(now)
    assert len(up) == 1 and up[0].when_utc.month == 6


def test_upcoming_respects_within_hours(fixed_calendar):
    now = UTC.localize(datetime(2026, 6, 16, 18, 0))  # 24h before
    assert len(events.upcoming(now, within_hours=25)) == 1
    assert events.upcoming(now, within_hours=23) == []


def test_next_event_none_when_calendar_exhausted(fixed_calendar):
    assert events.next_event(UTC.localize(datetime(2027, 1, 1))) is None


def test_naive_now_is_tolerated(fixed_calendar):
    """A naive clock must not raise — it is treated as UTC."""
    assert events.upcoming(datetime(2026, 3, 1, 12, 0)) != []


# ── Event windows ───────────────────────────────────────────────

@pytest.mark.parametrize("minutes_before,expected", [
    (180, None),     # 3h before — outside the 2h pre-window
    (119, "pre"),    # just inside
    (5, "pre"),
])
def test_pre_window(fixed_calendar, minutes_before, expected):
    release = UTC.localize(datetime(2026, 6, 17, 18, 0))
    now = release - timedelta(minutes=minutes_before)
    _, phase = events.active_window(now)
    assert phase == expected


@pytest.mark.parametrize("minutes_after,expected", [
    (5, "post"),
    (59, "post"),
    (90, None),      # past the 1h post-window
])
def test_post_window(fixed_calendar, minutes_after, expected):
    release = UTC.localize(datetime(2026, 6, 17, 18, 0))
    now = release + timedelta(minutes=minutes_after)
    _, phase = events.active_window(now)
    assert phase == expected


def test_in_event_window_matches_active_window(fixed_calendar):
    release = UTC.localize(datetime(2026, 6, 17, 18, 0))
    assert events.in_event_window(release - timedelta(minutes=30)) is True
    assert events.in_event_window(release - timedelta(days=3)) is False


def test_nearest_event_wins_when_windows_overlap(monkeypatch):
    """Two releases an hour apart: the closer one is reported."""
    monkeypatch.setattr(events, "CALENDAR", [("2026-06-17", "cpi"),
                                             ("2026-06-17", "fomc")])
    monkeypatch.setattr(events, "GENERATE_NFP", False)
    # CPI 08:30 ET, FOMC 14:00 ET. At 13:30 ET the FOMC is 30m away.
    now = EASTERN.localize(datetime(2026, 6, 17, 13, 30)).astimezone(UTC)
    ev, phase = events.active_window(now)
    assert ev.type == "fomc" and phase == "pre"


# ── Generated NFP ───────────────────────────────────────────────

def test_nfp_lands_on_first_friday(monkeypatch):
    monkeypatch.setattr(events, "CALENDAR", [])
    monkeypatch.setattr(events, "GENERATE_NFP", True)
    now = UTC.localize(datetime(2026, 6, 1, 0, 0))
    nfp = [e for e in events.upcoming(now) if e.type == "nfp"]
    assert nfp, "expected generated NFP events"
    for e in nfp[:3]:
        assert e.when(EASTERN).weekday() == 4, "must be a Friday"
        assert e.when(EASTERN).day <= 7, "must be the FIRST Friday"
        assert e.estimated is True, "generated dates must be flagged estimated"


# ── Staleness ───────────────────────────────────────────────────

def test_calendar_status_reports_stale_when_running_out(fixed_calendar):
    just_before = UTC.localize(datetime(2026, 6, 10, 0, 0))  # ~7 days left
    status = events.calendar_status(just_before)
    assert status["future_events"] == 1
    assert status["stale"] is True


def test_calendar_status_not_stale_with_runway(fixed_calendar):
    early = UTC.localize(datetime(2026, 1, 1, 0, 0))
    assert events.calendar_status(early)["stale"] is False


def test_calendar_status_ignores_generated_nfp(monkeypatch):
    """Generated NFP never runs out, so it must not mask an empty table."""
    monkeypatch.setattr(events, "CALENDAR", [])
    monkeypatch.setattr(events, "GENERATE_NFP", True)
    status = events.calendar_status(UTC.localize(datetime(2026, 6, 1)))
    assert status["future_events"] == 0 and status["stale"] is True


def test_shipped_calendar_entries_are_wellformed():
    """The real table must parse, even though its dates are not asserted."""
    for date_str, type_ in events.CALENDAR:
        assert type_ in events.EVENT_TYPES, f"unknown type {type_}"
        assert events._to_utc(date_str, "12:00") is not None, date_str


# ── ML features ─────────────────────────────────────────────────

def test_feature_vector_matches_declared_names(monkeypatch):
    monkeypatch.setattr(events, "CALENDAR", [])
    monkeypatch.setattr(events, "GENERATE_NFP", False)
    now = datetime.now(BKK)
    hist = []
    price = 4000.0
    for i in range(60, 0, -1):
        ts = now - timedelta(hours=i)
        price *= 1.0004
        hist.append({"ts": ts.isoformat(), "thb_gram": round(price, 2),
                     "hour": ts.hour, "weekday": ts.weekday()})
    vector = predictor._extract_features(hist, len(hist) - 1)
    names = ["rsi", "price_vs_sma5", "price_vs_sma20", "sma_crossover", "macd",
             "macd_histogram", "bb_position", "momentum", "volatility", "hour",
             "weekday", "hours_to_event", "in_event_window", "change_1h",
             "change_4h"]
    assert len(vector) == len(names), "vector and feature_names disagree"


def test_event_features_reflect_the_calendar(monkeypatch):
    monkeypatch.setattr(events, "CALENDAR", [("2026-06-17", "fomc")])
    monkeypatch.setattr(events, "GENERATE_NFP", False)
    release = UTC.localize(datetime(2026, 6, 17, 18, 0))

    near = {"ts": (release - timedelta(minutes=30)).astimezone(BKK).isoformat()}
    far = {"ts": (release - timedelta(days=30)).astimezone(BKK).isoformat()}

    assert predictor._in_event_window(near) is True
    assert predictor._in_event_window(far) is False
    assert predictor._hours_to_event(near) < 1
    assert predictor._hours_to_event(far) == predictor.EVENT_HOURS_CAP


def test_event_features_survive_a_bad_timestamp():
    bad = {"thb_gram": 4000.0}  # no "ts" at all
    assert predictor._hours_to_event(bad) == predictor.EVENT_HOURS_CAP
    assert predictor._in_event_window(bad) is False


def test_stale_model_is_skipped_not_crashed(monkeypatch):
    """A model trained on the old 13-feature vector must degrade cleanly."""
    monkeypatch.setattr(events, "CALENDAR", [])
    monkeypatch.setattr(events, "GENERATE_NFP", False)
    now = datetime.now(BKK)
    hist = []
    price = 4000.0
    for i in range(60, 0, -1):
        ts = now - timedelta(hours=i)
        price *= 1.0004
        hist.append({"ts": ts.isoformat(), "thb_gram": round(price, 2),
                     "hour": ts.hour, "weekday": ts.weekday()})

    model_data = {"models": {"24h": {"model_b64": "irrelevant", "n_features": 13}}}
    result = predictor.predict(hist, model_data)
    assert result["predictions"]["24h"]["stale"] is True
    assert "13 features" in result["predictions"]["24h"]["error"]


# ── /events command ─────────────────────────────────────────────

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
    monkeypatch.setattr(bot_core, "send_message",
                        lambda text, chat_id="", **kw: sent.append(text))
    return sent


def test_events_command_lists_upcoming(monkeypatch, fixed_calendar):
    _MemStore(monkeypatch)
    sent = _capture(monkeypatch)
    monkeypatch.setattr(bot_core.events, "upcoming",
                        lambda *a, **k: events.all_events()[1:])

    bot_core.cmd_events("111", "en")

    assert "Upcoming Market Events" in sent[-1]
    assert "FOMC rate decision" in sent[-1]


def test_events_command_localised(monkeypatch, fixed_calendar):
    _MemStore(monkeypatch)
    sent = _capture(monkeypatch)
    monkeypatch.setattr(bot_core.events, "upcoming",
                        lambda *a, **k: events.all_events()[1:])

    bot_core.cmd_events("111", "th")
    assert "เหตุการณ์ตลาด" in sent[-1]

    bot_core.cmd_events("111", "my")
    assert "ဈေးကွက်" in sent[-1]


def test_events_command_handles_empty_calendar(monkeypatch):
    _MemStore(monkeypatch)
    sent = _capture(monkeypatch)
    monkeypatch.setattr(bot_core.events, "upcoming", lambda *a, **k: [])

    bot_core.cmd_events("111", "en")
    assert "No scheduled events" in sent[-1]


def test_stale_warning_only_goes_to_owner(monkeypatch, fixed_calendar):
    _MemStore(monkeypatch)
    sent = _capture(monkeypatch)
    monkeypatch.setattr(bot_core, "TG_CHAT_ID", "OWNER")
    monkeypatch.setattr(bot_core.events, "upcoming",
                        lambda *a, **k: events.all_events()[1:])
    monkeypatch.setattr(bot_core.events, "calendar_status",
                        lambda *a, **k: {"stale": True, "days_left": 3,
                                         "future_events": 1, "last": None})

    bot_core.cmd_events("SOMEONE_ELSE", "en")
    assert "needs updating" not in sent[-1]

    bot_core.cmd_events("OWNER", "en")
    assert "needs updating" in sent[-1]


def test_countdown_formatting():
    assert bot_core.format_countdown(3.5, "en") == "3h 30m"
    assert bot_core.format_countdown(50, "en") == "2d 2h"
    assert bot_core.format_countdown(-5, "en") == "0h 0m", "never negative"


def test_estimated_events_are_marked(monkeypatch):
    monkeypatch.setattr(events, "CALENDAR", [])
    monkeypatch.setattr(events, "GENERATE_NFP", True)
    now = UTC.localize(datetime(2026, 6, 1))
    nfp = events.upcoming(now, limit=1)[0]
    line = bot_core.format_event_line(nfp, now, "en")
    assert "estimated" in line
