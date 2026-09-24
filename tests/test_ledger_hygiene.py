"""Unusable ledger rows are left out of the portfolio — and SAID to be.

_replay used to count every row, however malformed, and get it silently wrong:

    null grams          the buy's cost counted, with no gold behind it
    type "gift"         fell into the SELL branch and took gold out
    Infinity            written by `/bought inf` before #14 — every figure inf

Rows it cannot use are now skipped and named on /portfolio, by the number that
/edit and /delete take to fix them.
"""
import contextlib
import io

import pytest

import bot_core
import goldapi
import storage


def _row(n, **over):
    base = {"type": "buy", "ts": f"2026-09-{n:02d}T10:00:00+07:00",
            "amount_thb": 4000, "price_per_gram": 4000.0, "grams": 1.0}
    base.update(over)
    return base


class _Ledger:
    def __init__(self, monkeypatch, rows):
        self.rows = list(rows)
        monkeypatch.setattr(storage, "_read_file", lambda f, fresh=False:
                            list(self.rows) if f == storage.BUY_LOG_FILE else {})

        def _write(f, d):
            if f == storage.BUY_LOG_FILE:
                self.rows = list(d)
            return True

        monkeypatch.setattr(storage, "_write_file", _write)


def _portfolio(monkeypatch):
    monkeypatch.setattr(goldapi, "get_gold_price", lambda *a, **k: (4000.0, 2400.0, 34.0))
    sent = []
    monkeypatch.setattr(bot_core, "send_message", lambda text, cid="", **k: sent.append(text))
    with contextlib.redirect_stdout(io.StringIO()):
        bot_core.cmd_portfolio("owner", "en")
    return sent[0]


BAD = {
    "null grams":       _row(2, grams=None),
    "missing grams":    {k: v for k, v in _row(2).items() if k != "grams"},
    "unknown type":     _row(2, type="gift"),
    "Infinity":         _row(2, amount_thb=float("inf"), grams=float("inf")),
    "NaN":              _row(2, grams=float("nan")),
    "string amount":    _row(2, amount_thb="4000"),
    "bool grams":       _row(2, grams=True),
    "negative amount":  _row(2, amount_thb=-4000),
    "not a dict":       "junk",
}


@pytest.mark.parametrize("kind", BAD)
def test_an_unusable_row_is_left_out_not_miscounted(kind):
    book = storage._replay([_row(1, amount_thb=40000, grams=10.0), BAD[kind]])
    assert (book["grams"], book["cost"], book["realized"]) == (10.0, 40000.0, 0.0), kind
    assert book["skipped_rows"] == [2]


@pytest.mark.parametrize("kind", BAD)
def test_portfolio_names_the_row_and_does_not_crash(monkeypatch, kind):
    _Ledger(monkeypatch, [_row(1), BAD[kind]])
    out = _portfolio(monkeypatch)
    assert "cannot be read: #2" in out
    assert "⚠️ #2 unreadable entry" in out


def test_a_ledger_of_only_bad_rows_is_not_called_empty(monkeypatch):
    """"Empty" would hide exactly the entries the owner needs to fix."""
    _Ledger(monkeypatch, [_row(1, grams=None)])
    out = _portfolio(monkeypatch)
    assert "cannot be read: #1" in out


def test_a_tiny_buy_that_rounds_to_zero_grams_still_counts():
    """0.1 THB at 4,000/g is 0.0000 g after rounding — legitimate, not broken."""
    book = storage._replay([_row(1, amount_thb=0.1, grams=0.0)])
    assert book["skipped_rows"] == [] and book["buys"] == 1


def test_row_numbers_match_the_ledger_past_the_first_ten(monkeypatch):
    """The numbers /portfolio shows are what /edit and /delete take. They were
    computed as num_buys + num_sells, which only equals the ledger length while
    every row is counted — so once a bad row is left out, every number after
    it is off by one. The listing shows the last ten rows, so this only bites
    on a ledger longer than ten."""
    rows = [_row(n) for n in range(1, 16)]
    rows[2] = _row(3, grams=None)                  # a bad row early on
    rows[-1] = _row(15, amount_thb=9999)           # the row we will target
    ledger = _Ledger(monkeypatch, rows)

    out = _portfolio(monkeypatch)
    last = [ln for ln in out.splitlines() if "฿9,999" in ln][0]
    assert "#15 " in last, last                    # was "#14" before the fix

    removed = storage.delete_entry(15)             # what the owner would type
    assert removed["amount_thb"] == 9999
    assert all(r["amount_thb"] != 9999 for r in ledger.rows)


def test_a_bad_buy_does_not_count_as_gold_you_can_sell(monkeypatch):
    """Holdings for /sold come from _replay too: a buy with no grams must not
    fund a sale."""
    _Ledger(monkeypatch, [_row(1, grams=None, amount_thb=40000)])
    assert storage.log_sell(4000, 4000.0) is None      # nothing usable held


def test_edit_repairs_a_null_grams_row(monkeypatch):
    """The warning says "/edit or /delete" — /edit recomputes grams from the
    stored price, so a row that lost its grams becomes usable again."""
    ledger = _Ledger(monkeypatch, [_row(1, grams=None, amount_thb=8000)])
    storage.edit_entry(1, 8000)
    assert ledger.rows[0]["grams"] == 2.0
    assert storage._replay(ledger.rows)["skipped_rows"] == []
