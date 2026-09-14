"""Portfolio figures come from replaying the ledger in order.

Two bugs live here, both in the money-tracking path:

  * cost basis was averaged over the FINISHED ledger, so a buy made after a
    sale silently rewrote the profit reported for that sale; and
  * /edit and /delete could leave a sale with no gold behind it, which then
    reported a portfolio worth nothing rather than an error.
"""
import pytest

import bot_core
import storage


class _FakeStore:
    def __init__(self, monkeypatch):
        self.data = {}
        monkeypatch.setattr(
            storage, "_read_file",
            lambda f, fresh=False: self.data.get(
                f, [] if f in (storage.PRICE_HISTORY_FILE, storage.BUY_LOG_FILE) else {}))
        monkeypatch.setattr(storage, "_write_file",
                            lambda f, d: self.data.__setitem__(f, d))


def _capture(monkeypatch):
    sent = []
    monkeypatch.setattr(bot_core, "send_message", lambda text, cid="", **k: sent.append(text))
    return sent


# ── A later buy must not rewrite an earlier sale ────────────────

def test_later_buy_does_not_change_past_realized_pnl(monkeypatch):
    """The bug: averaging over the whole ledger let today's purchase change
    the profit already reported for last month's sale."""
    store = _FakeStore(monkeypatch)

    storage.log_buy(10000, 1000.0)        # 10g @ 1,000
    storage.log_sell(6000, 1200.0)        # sell 5g @ 1,200 -> basis 5,000, +1,000
    before = storage.get_portfolio()["realized_pnl"]
    assert before == 1000.0

    storage.log_buy(20000, 4000.0)        # 5g @ 4,000, long after the sale
    after = storage.get_portfolio()["realized_pnl"]

    assert after == before, "a later buy rewrote a past sale's realized P&L"
    assert len(store.data[storage.BUY_LOG_FILE]) == 3


def test_cost_basis_is_the_average_at_the_time_of_sale(monkeypatch):
    _FakeStore(monkeypatch)

    storage.log_buy(1000, 1000.0)         # 1g @ 1,000
    storage.log_buy(3000, 3000.0)         # 1g @ 3,000  -> pool 2g, avg 2,000
    storage.log_sell(2500, 2500.0)        # sell 1g @ 2,500 -> basis 2,000, +500

    book = storage.get_portfolio()
    assert book["realized_pnl"] == 500.0
    assert book["total_grams"] == 1.0
    assert book["avg_cost"] == 2000.0     # the remaining gram keeps that cost
    assert book["total_invested"] == 2000.0


def test_unrealized_pnl_uses_the_cost_of_what_is_held(monkeypatch):
    _FakeStore(monkeypatch)

    storage.log_buy(10000, 1000.0)        # 10g @ 1,000
    storage.log_sell(6000, 1200.0)        # 5g out, 5,000 of cost leaves with it

    pnl = storage.get_portfolio_pnl(1500.0)
    assert pnl["total_grams"] == 5.0
    assert pnl["total_invested"] == 5000.0
    assert pnl["current_value"] == 7500.0
    assert pnl["unrealized_pnl"] == 2500.0
    assert pnl["pnl_thb"] == 3500.0       # 2,500 unrealized + 1,000 realized


def test_avg_cost_falls_back_to_lifetime_once_fully_sold(monkeypatch):
    _FakeStore(monkeypatch)

    storage.log_buy(10000, 1000.0)
    storage.log_sell(12000, 1200.0)       # all 10g out @ 1,200

    book = storage.get_portfolio()
    assert book["total_grams"] == 0.0
    assert book["avg_cost"] == 1000.0     # not ฿0
    assert book["realized_pnl"] == 2000.0


# ── /edit and /delete cannot strand a sale ──────────────────────

def test_edit_cannot_raise_a_sale_above_holdings(monkeypatch):
    store = _FakeStore(monkeypatch)
    storage.log_buy(10000, 1000.0)        # 10g
    storage.log_sell(1000, 1000.0)        # 1g out

    with pytest.raises(storage.InsufficientGold):
        storage.edit_entry(2, 50000)      # would sell 50g

    # The stored ledger is untouched — validation happens before the write.
    assert store.data[storage.BUY_LOG_FILE][1]["amount_thb"] == 1000
    assert storage.get_portfolio()["total_grams"] == 9.0


def test_delete_cannot_strand_a_later_sale(monkeypatch):
    _FakeStore(monkeypatch)
    storage.log_buy(10000, 1000.0)
    storage.log_sell(9000, 1000.0)        # 9g out, 1g left

    with pytest.raises(storage.InsufficientGold):
        storage.delete_entry(1)           # removing the buy strands the sale

    assert storage.get_portfolio()["num_buys"] == 1


def test_valid_edit_and_delete_still_work(monkeypatch):
    _FakeStore(monkeypatch)
    storage.log_buy(10000, 1000.0)
    storage.log_sell(1000, 1000.0)

    assert storage.edit_entry(2, 2000)["grams"] == 2.0
    assert storage.get_portfolio()["total_grams"] == 8.0
    assert storage.delete_entry(2)["type"] == "sell"
    assert storage.get_portfolio()["total_grams"] == 10.0


def test_edit_missing_index_still_returns_none(monkeypatch):
    _FakeStore(monkeypatch)
    storage.log_buy(1000, 1000.0)
    assert storage.edit_entry(99, 2000) is None
    assert storage.delete_entry(99) is None


# ── The user sees a real message, not a generic error ───────────

def test_commands_report_the_oversell(monkeypatch):
    _FakeStore(monkeypatch)
    storage.log_buy(10000, 1000.0)
    storage.log_sell(1000, 1000.0)
    sent = _capture(monkeypatch)

    bot_core.cmd_edit("111", "2 50000", "en")
    assert "no gold behind it" in sent[0]

    sent.clear()
    storage.log_sell(9000, 1000.0)
    bot_core.cmd_delete("111", "1", "en")
    assert "no gold behind it" in sent[0]


# ── A ledger already corrupted must not report nonsense ─────────

def test_oversold_legacy_ledger_is_clamped_not_negative(monkeypatch):
    """Entries written before the guard could already be inconsistent."""
    store = _FakeStore(monkeypatch)
    store.data[storage.BUY_LOG_FILE] = [
        {"type": "buy", "ts": "2026-01-01T10:00:00+07:00",
         "amount_thb": 1000, "price_per_gram": 1000.0, "grams": 1.0},
        {"type": "sell", "ts": "2026-01-02T10:00:00+07:00",
         "amount_thb": 5000, "price_per_gram": 1000.0, "grams": 5.0},
    ]

    book = storage.get_portfolio()
    assert book["total_grams"] == 0.0     # clamped, never negative
    assert book["realized_pnl"] == 4000.0  # 5,000 revenue less the 1,000 basis
