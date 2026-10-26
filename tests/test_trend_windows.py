"""Trend windows are wall-clock hours, not list positions.

"24h change" was prices[-24]: 24 POINTS back. On a perfect hourly series that
is 23 hours — every window was off by one. While GitHub ran the monitor 4–8
times a day, points sat ~4 hours apart, so "24h" spanned about four days and
"30d" about three months; on 2026-10-26 the 720-point history still held ~400
of those points, so "30d" still meant roughly three months.
"""
from datetime import datetime, timedelta, timezone

import predictor

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _rows(points):
    """[(hours after T0, price), ...] as stored history rows."""
    return [{"ts": (T0 + timedelta(hours=h)).isoformat(), "thb_gram": p}
            for h, p in points]


def _pct(old, new):
    return round((new - old) / old * 100, 3)


def test_each_window_is_exactly_its_hours():
    history = _rows((h, 1000.0 + h) for h in range(200))
    t = predictor.get_trend_summary(history)
    now = 1199.0
    assert t["change_1h"] == _pct(1198.0, now)
    assert t["change_4h"] == _pct(1195.0, now)     # was prices[-4]: 3 hours
    assert t["change_24h"] == _pct(1175.0, now)    # was prices[-24]: 23 hours
    assert t["high_24h"] == now and t["low_24h"] == 1175.0


def test_four_hourly_points_do_not_stretch_the_windows():
    """The shape the history had before the schedule fix: 720 points, 4h apart."""
    history = _rows((4 * i, 1000.0 + i) for i in range(720))
    t = predictor.get_trend_summary(history)
    now = 1719.0
    assert "change_1h" not in t, "no point anywhere near an hour ago"
    assert t["change_24h"] == _pct(now - 6, now)   # 6 steps of 4h, not 24 points
    assert t["change_30d"] == _pct(now - 180, now)  # 720h, not 720 points (~4 months)


def test_a_gap_hides_the_window_instead_of_stretching_it():
    """Nothing within 2.4h of 24h ago: say nothing rather than a 31h change."""
    points = [(h, 1000.0 + h) for h in range(60) if not 30 <= h <= 41]
    t = predictor.get_trend_summary(_rows(points))
    assert "change_24h" not in t and "high_24h" not in t
    assert "change_1h" in t and "change_4h" in t


def test_a_point_near_the_window_start_still_counts():
    """Appends land every 55–65 minutes, so the start rarely hits a point."""
    points = [(h + 0.3, 1000.0 + h) for h in range(30)] + [(30.0, 1100.0)]
    t = predictor.get_trend_summary(_rows(points))
    assert t["change_24h"] == _pct(1006.0, 1100.0)  # 6.3h, 18 min from 6.0h


def test_a_streak_stops_at_a_gap():
    """One step across five hours is not a five-hour run of rises."""
    points = [(0, 1000.0), (1, 1001.0), (2, 1002.0), (7, 1003.0), (8, 1004.0), (9, 1005.0)]
    t = predictor.get_trend_summary(_rows(points))
    assert t["streak"] == 2 and t["streak_direction"] == "up"


def test_a_streak_stops_at_a_reversal_or_a_flat_hour():
    up_then_down = _rows([(0, 1000.0), (1, 1003.0), (2, 1002.0), (3, 1001.0)])
    assert predictor.get_trend_summary(up_then_down)["streak"] == 2
    flat = _rows([(0, 1000.0), (1, 1000.0)])
    t = predictor.get_trend_summary(flat)
    assert t["streak"] == 0 and t["streak_direction"] == "flat"


def test_rows_without_a_usable_time_still_give_the_price():
    history = [{"thb_gram": 4000.0}, {"thb_gram": 4010.0}]
    assert predictor.get_trend_summary(history) == {"current": 4010.0}
