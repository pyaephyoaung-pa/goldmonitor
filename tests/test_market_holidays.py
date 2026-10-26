"""The frozen-price check now knows the days spot gold does not trade at all.

Without them, Christmas Day or Good Friday — a still price on a weekday —
would have read as a stuck source.
"""
import datetime as _dt

import pytest
import pytz

import goldapi

ET = pytz.timezone("US/Eastern")


def _et(y, m, d, h=10):
    return ET.localize(_dt.datetime(y, m, d, h))


@pytest.mark.parametrize("when", [
    _et(2026, 12, 25),   # Christmas, a Friday
    _et(2027, 1, 1),     # New Year, a Friday
    _et(2027, 3, 26),    # Good Friday 2027 (Easter is 28 March)
    _et(2026, 4, 3),     # Good Friday 2026 (Easter is 5 April)
])
def test_spot_does_not_trade(when):
    assert goldapi.market_should_be_open(when) is False


def test_thanksgiving_is_a_trading_day():
    """New York is shut, London is not: spot still moves."""
    assert goldapi.market_should_be_open(_et(2026, 11, 26)) is True


def test_easter_dates():
    assert goldapi._easter(2026) == _dt.date(2026, 4, 5)
    assert goldapi._easter(2027) == _dt.date(2027, 3, 28)
    assert goldapi._easter(2028) == _dt.date(2028, 4, 16)


def test_a_holiday_is_not_counted_as_frozen_trading_time():
    start = _et(2026, 12, 25, 0)
    history = [{"ts": (start + _dt.timedelta(hours=h)).isoformat(), "usd_oz": 4150.0}
               for h in range(12)]
    assert goldapi.hours_frozen(history, 4150.0, _et(2026, 12, 25, 12)) == 0.0
