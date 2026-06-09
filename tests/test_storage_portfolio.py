import storage


class FakeStore:
    """In-memory replacement for the Gist-backed _read_file/_write_file."""
    def __init__(self):
        self.data = {}

    def read(self, filename):
        if filename in self.data:
            return self.data[filename]
        return [] if filename in (storage.PRICE_HISTORY_FILE, storage.BUY_LOG_FILE) else {}

    def write(self, filename, data):
        self.data[filename] = data


def _patch(monkeypatch):
    fake = FakeStore()
    monkeypatch.setattr(storage, "_read_file", fake.read)
    monkeypatch.setattr(storage, "_write_file", fake.write)
    return fake


def test_log_buy_then_pnl(monkeypatch):
    _patch(monkeypatch)
    storage.log_buy(10000, 1000.0)   # 10 grams @ 1000
    pnl = storage.get_portfolio_pnl(1200.0)  # price up 20%
    assert pnl["num_buys"] == 1
    assert abs(pnl["total_grams"] - 10.0) < 1e-6
    assert pnl["unrealized_pnl"] > 0
    assert pnl["pnl_pct"] > 0


def test_sell_more_than_held_is_rejected(monkeypatch):
    _patch(monkeypatch)
    storage.log_buy(1000, 1000.0)  # 1 gram
    assert storage.log_sell(5000, 1000.0) is None  # 5 grams — too much


def test_realized_pnl_after_sell(monkeypatch):
    _patch(monkeypatch)
    storage.log_buy(10000, 1000.0)   # 10g cost basis 1000
    storage.log_sell(6000, 1200.0)   # sell 5g @ 1200
    pnl = storage.get_portfolio_pnl(1200.0)
    assert pnl["num_sells"] == 1
    # sold 5g, cost basis 5*1000=5000, revenue 6000 -> realized +1000
    assert abs(pnl["realized_pnl"] - 1000.0) < 1.0


def test_edit_and_delete(monkeypatch):
    _patch(monkeypatch)
    storage.log_buy(1000, 1000.0)
    storage.edit_entry(1, 2000)
    p = storage.get_portfolio()
    assert abs(p["total_grams"] - 2.0) < 1e-6
    storage.delete_entry(1)
    assert storage.get_portfolio()["num_buys"] == 0


def test_append_price_dedups_by_timestamp(monkeypatch):
    fake = _patch(monkeypatch)
    # Seed with two entries sharing a timestamp (simulating a clobber/dup).
    fake.data[storage.PRICE_HISTORY_FILE] = [
        {"ts": "2026-01-01T00:00:00", "thb_gram": 1000},
        {"ts": "2026-01-01T00:00:00", "thb_gram": 1000},
    ]
    out = storage.append_price(1010.0, 2000.0, 32.0)
    timestamps = [h["ts"] for h in out]
    # duplicate collapsed to one, plus the freshly appended point
    assert len(timestamps) == len(set(timestamps))
    assert len(out) == 2


def test_append_price_trims_to_720(monkeypatch):
    fake = _patch(monkeypatch)
    fake.data[storage.PRICE_HISTORY_FILE] = [
        {"ts": f"2026-01-01T00:{i:02d}:00", "thb_gram": 1000 + i} for i in range(60)
    ] + [{"ts": f"2026-02-{d:02d}T00:00:00", "thb_gram": 1000} for d in range(1, 29)]
    # pad up to >720
    fake.data[storage.PRICE_HISTORY_FILE] = [
        {"ts": f"2026-{(i // 1440) % 12 + 1:02d}-{(i // 60) % 28 + 1:02d}T{i % 24:02d}:{i % 60:02d}:{i % 60:02d}.{i:06d}", "thb_gram": 1000 + i}
        for i in range(800)
    ]
    out = storage.append_price(1010.0, 2000.0, 32.0)
    assert len(out) == 720
