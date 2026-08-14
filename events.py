"""
High-impact economic event calendar for Gold Monitor.

Gold's biggest moves are usually NOT surprises — they cluster around scheduled
US releases (FOMC decisions, CPI, Non-Farm Payrolls, PCE). Those are published
on a calendar well in advance, so knowing them needs no news feed, no NLP and
no API key: just a date table and correct timezone maths.

What this module is for:
  * warn BEFORE a release ("FOMC in 2h — expect volatility")
  * mark the window AFTER one, when a price move is event-driven rather than
    technical
  * let the monitor flag its own TA signal as unreliable inside that window

What it is deliberately NOT for: predicting the direction of the reaction.
Nothing here forecasts anything — it says "something scheduled is happening",
which is a fact, not an opinion.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️  THE DATES IN `CALENDAR` BELOW MUST BE KEPT UP TO DATE.
    They are the one part of this feature that cannot be derived or tested
    into correctness — a wrong date makes the warnings worse than useless.

    STATUS: FOMC verified against federalreserve.gov on 2026-08-14, covering
    the rest of 2026 and all of 2027. CPI and PCE are NOT in the table —
    bls.gov and bea.gov return 403 to automated clients, so those have to be
    added by hand.

    FOMC : https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
    CPI  : https://www.bls.gov/schedule/news_release/cpi.htm
    NFP  : https://www.bls.gov/schedule/news_release/empsit.htm
    PCE  : https://www.bea.gov/news/schedule

    `calendar_status()` reports how much future calendar is left, and /events
    surfaces a warning to the owner when it is running out. Top it up once a
    year when the Fed publishes the next schedule.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytz

# Release times are quoted in US Eastern, which shifts with US DST — hence a
# real timezone rather than a fixed offset.
EASTERN = pytz.timezone("US/Eastern")
BANGKOK_TZ = pytz.timezone("Asia/Bangkok")

# How long before / after a release we treat the market as event-driven.
PRE_WINDOW_HOURS = 2.0
POST_WINDOW_HOURS = 1.0

# Warn about anything landing within this horizon in the daily messages.
LOOKAHEAD_HOURS = 24.0

# Below this many days of remaining calendar, /events nags the owner to refresh.
STALE_AFTER_DAYS = 45


# Event types: local release time (US Eastern) and an i18n key for the label.
EVENT_TYPES = {
    "fomc": {"time": "14:00", "emoji": "🏛", "key": "event.type.fomc"},
    "cpi":  {"time": "08:30", "emoji": "📈", "key": "event.type.cpi"},
    "nfp":  {"time": "08:30", "emoji": "👷", "key": "event.type.nfp"},
    "pce":  {"time": "08:30", "emoji": "🧾", "key": "event.type.pce"},
}

# ── The calendar ────────────────────────────────────────────────────────────
# (date in US Eastern, event type). Times come from EVENT_TYPES.
#
# SEEDED FROM THE FED'S REGULAR 8-MEETING-A-YEAR PATTERN AND THE USUAL BLS/BEA
# RELEASE RHYTHM. Treat every line as UNVERIFIED until you have checked it
# against the official source above and moved it into the verified block.
#
# FOMC statements land 14:00 ET on the SECOND day of a two-day meeting; the
# date below is that second day.
CALENDAR = [
    # ── FOMC 2026 — VERIFIED against federalreserve.gov on 2026-08-14 ──
    ("2026-09-16", "fomc"),
    ("2026-10-28", "fomc"),
    ("2026-12-09", "fomc"),

    # ── FOMC 2027 — published on the same page, but the Fed states that
    #    "each meeting date is tentative until confirmed at the meeting
    #    immediately preceding it", so treat these as provisional.
    ("2027-01-27", "fomc"),
    ("2027-03-17", "fomc"),
    ("2027-04-28", "fomc"),
    ("2027-06-09", "fomc"),
    ("2027-07-28", "fomc"),
    ("2027-09-15", "fomc"),
    ("2027-10-27", "fomc"),
    ("2027-12-08", "fomc"),

    # ── CPI / PCE — STILL MISSING ──
    # bls.gov and bea.gov block automated fetches (HTTP 403), so these could
    # not be verified programmatically. Add them by hand from the schedules
    # linked above; until then the calendar covers FOMC only, and CPI/PCE
    # releases will pass without a warning.
]

# Some releases follow a published rule rather than an ad-hoc date, so they can
# be generated instead of listed. Non-Farm Payrolls is the reliable one: BLS
# releases the Employment Situation at 08:30 ET on the first Friday of the
# month in the large majority of months. It is not a guarantee — BLS can and
# does shift it — so it is generated separately and labelled as estimated.
GENERATE_NFP = True


class Event:
    """One scheduled release, with its instant fixed in real time."""

    __slots__ = ("type", "when_utc", "estimated")

    def __init__(self, type_: str, when_utc: datetime, estimated: bool = False):
        self.type = type_
        self.when_utc = when_utc
        self.estimated = estimated

    @property
    def emoji(self) -> str:
        return EVENT_TYPES.get(self.type, {}).get("emoji", "📅")

    @property
    def label_key(self) -> str:
        return EVENT_TYPES.get(self.type, {}).get("key", "event.type.other")

    def when(self, tz=BANGKOK_TZ) -> datetime:
        return self.when_utc.astimezone(tz)

    def hours_until(self, now: datetime) -> float:
        return (self.when_utc - now).total_seconds() / 3600.0

    def __repr__(self) -> str:
        return f"<Event {self.type} {self.when_utc.isoformat()}>"

    def __eq__(self, other) -> bool:
        return (isinstance(other, Event) and self.type == other.type
                and self.when_utc == other.when_utc)


def _to_utc(date_str: str, hhmm: str) -> datetime | None:
    """Combine a US-Eastern date + time into an absolute UTC instant.

    localize() rather than replace(tzinfo=...) so the correct EST/EDT offset is
    applied for that date — a naive offset would put every release an hour out
    for roughly half the year.
    """
    try:
        y, m, d = (int(p) for p in date_str.split("-"))
        hh, mm = (int(p) for p in hhmm.split(":"))
        return EASTERN.localize(datetime(y, m, d, hh, mm)).astimezone(pytz.UTC)
    except (ValueError, TypeError) as e:
        print(f"[events] bad calendar entry {date_str!r} {hhmm!r}: {e}")
        return None


def _first_friday(year: int, month: int) -> datetime | None:
    """08:30 ET on the first Friday of the month, as UTC."""
    d = datetime(year, month, 1)
    # weekday(): Monday=0 … Friday=4
    d += timedelta(days=(4 - d.weekday()) % 7)
    return _to_utc(d.strftime("%Y-%m-%d"), EVENT_TYPES["nfp"]["time"])


# Only ever generate a couple of months of NFP. They are estimates, and a long
# tail of them would crowd the hand-verified FOMC/CPI entries out of /events.
NFP_MONTHS_AHEAD = 2


def _generated_nfp(now: datetime, months: int = NFP_MONTHS_AHEAD) -> list:
    """First-Friday NFP estimates for the next few months."""
    out = []
    year, month = now.year, now.month
    for _ in range(months + 1):
        when = _first_friday(year, month)
        if when is not None:
            out.append(Event("nfp", when, estimated=True))
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return out


def all_events() -> list:
    """Every known event, chronological. Includes past ones."""
    events = []
    for date_str, type_ in CALENDAR:
        spec = EVENT_TYPES.get(type_)
        if spec is None:
            print(f"[events] unknown event type {type_!r} — skipped")
            continue
        when = _to_utc(date_str, spec["time"])
        if when is not None:
            events.append(Event(type_, when))
    return sorted(events, key=lambda e: e.when_utc)


def _now_utc(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(pytz.UTC)
    if now.tzinfo is None:  # tolerate a naive clock rather than crashing
        return pytz.UTC.localize(now)
    return now.astimezone(pytz.UTC)


def upcoming(now: datetime | None = None, within_hours: float | None = None,
             limit: int | None = None) -> list:
    """Future events, soonest first."""
    now = _now_utc(now)
    events = all_events()
    if GENERATE_NFP:
        events += _generated_nfp(now)
    events = [e for e in events if e.when_utc > now]
    if within_hours is not None:
        events = [e for e in events if e.hours_until(now) <= within_hours]
    events.sort(key=lambda e: e.when_utc)
    return events[:limit] if limit else events


def next_event(now: datetime | None = None) -> Event | None:
    events = upcoming(now, limit=1)
    return events[0] if events else None


def active_window(now: datetime | None = None) -> tuple:
    """The event whose volatility window we are inside, and which side.

    Returns (event, phase) where phase is "pre" or "post", or (None, None).
    Prefers the nearest event so overlapping windows resolve sensibly.
    """
    now = _now_utc(now)
    events = all_events()
    if GENERATE_NFP:
        events += _generated_nfp(now - timedelta(days=40))

    best, best_phase, best_gap = None, None, None
    for e in events:
        hours = e.hours_until(now)
        if 0 <= hours <= PRE_WINDOW_HOURS:
            phase, gap = "pre", hours
        elif -POST_WINDOW_HOURS <= hours < 0:
            phase, gap = "post", -hours
        else:
            continue
        if best_gap is None or gap < best_gap:
            best, best_phase, best_gap = e, phase, gap
    return best, best_phase


def in_event_window(now: datetime | None = None) -> bool:
    """True when a scheduled release makes TA signals unreliable."""
    return active_window(now)[0] is not None


def hours_to_next(now: datetime | None = None, cap: float = 999.0) -> float:
    """Hours until the next event — an ML feature, capped so it stays bounded."""
    now = _now_utc(now)
    nxt = next_event(now)
    if nxt is None:
        return cap
    return min(nxt.hours_until(now), cap)


def calendar_status(now: datetime | None = None) -> dict:
    """How much hand-maintained calendar is left.

    The generated NFP estimates are excluded on purpose: they never run out,
    so counting them would hide the fact that the FOMC/CPI table needs a
    top-up.
    """
    now = _now_utc(now)
    future = [e for e in all_events() if e.when_utc > now]
    days_left = (future[-1].when_utc - now).days if future else 0
    return {
        "future_events": len(future),
        "days_left": days_left,
        "stale": days_left < STALE_AFTER_DAYS,
        "last": future[-1] if future else None,
    }
