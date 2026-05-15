"""
GitHub Gist-based persistent storage for Gold Monitor.
Stores: price history, buy logs, model state, bot update offset.
"""

import requests
import json
import os
from datetime import datetime
import pytz

BANGKOK_TZ = pytz.timezone("Asia/Bangkok")
GITHUB_TOKEN = os.environ.get("GIST_GITHUB_TOKEN", "")
GIST_ID = os.environ.get("GIST_ID", "")

# ── File names inside the Gist ──────────────────────────────────
PRICE_HISTORY_FILE = "price_history.json"
BUY_LOG_FILE = "buy_log.json"
DAY_STATE_FILE = "day_state.json"
BOT_STATE_FILE = "bot_state.json"
MODEL_DATA_FILE = "model_data.json"

HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}


# ── Low-level Gist I/O ─────────────────────────────────────────
def _get_gist() -> dict:
    """Fetch the entire Gist."""
    if not GITHUB_TOKEN or not GIST_ID:
        return {}
    try:
        r = requests.get(
            f"https://api.github.com/gists/{GIST_ID}",
            headers=HEADERS, timeout=15,
        )
        r.raise_for_status()
        return r.json().get("files", {})
    except Exception as e:
        print(f"[storage] Gist read error: {e}")
        return {}


def _read_file(filename: str) -> dict | list:
    """Read a single JSON file from the Gist."""
    files = _get_gist()
    if filename in files:
        try:
            return json.loads(files[filename]["content"])
        except (json.JSONDecodeError, KeyError):
            pass
    # Return appropriate empty container
    if filename in (PRICE_HISTORY_FILE, BUY_LOG_FILE):
        return []
    return {}


def _write_file(filename: str, data):
    """Write a single JSON file to the Gist."""
    if not GITHUB_TOKEN or not GIST_ID:
        print(f"[storage] No Gist credentials — skipping write for {filename}")
        return
    try:
        r = requests.patch(
            f"https://api.github.com/gists/{GIST_ID}",
            headers=HEADERS, timeout=15,
            json={"files": {filename: {"content": json.dumps(data, indent=2)}}},
        )
        r.raise_for_status()
    except Exception as e:
        print(f"[storage] Gist write error ({filename}): {e}")


def _write_files(file_dict: dict):
    """Write multiple files to the Gist in one API call."""
    if not GITHUB_TOKEN or not GIST_ID:
        return
    try:
        files_payload = {
            name: {"content": json.dumps(data, indent=2)}
            for name, data in file_dict.items()
        }
        r = requests.patch(
            f"https://api.github.com/gists/{GIST_ID}",
            headers=HEADERS, timeout=15,
            json={"files": files_payload},
        )
        r.raise_for_status()
    except Exception as e:
        print(f"[storage] Gist batch write error: {e}")


# ── Price History ───────────────────────────────────────────────
def append_price(thb_gram: float, usd_oz: float, thb_rate: float):
    """Append a price data point. Keep last 720 entries (~30 days hourly)."""
    history = _read_file(PRICE_HISTORY_FILE)
    now = datetime.now(BANGKOK_TZ)
    entry = {
        "ts": now.isoformat(),
        "thb_gram": thb_gram,
        "usd_oz": usd_oz,
        "thb_rate": thb_rate,
        "hour": now.hour,
        "weekday": now.weekday(),
    }
    history.append(entry)
    # Keep last 720 data points (~30 days of hourly data)
    history = history[-720:]
    _write_file(PRICE_HISTORY_FILE, history)
    return history


def get_price_history(limit: int = 720) -> list:
    """Get recent price history."""
    history = _read_file(PRICE_HISTORY_FILE)
    return history[-limit:]


# ── Day State (replaces gold_state.json) ────────────────────────
def load_day_state() -> dict:
    """Load today's state, reset if date changed."""
    today = datetime.now(BANGKOK_TZ).strftime("%Y-%m-%d")
    state = _read_file(DAY_STATE_FILE)
    if state.get("date") == today:
        return state
    return {
        "date": today,
        "open_price": None,
        "day_low": None,
        "day_high": None,
        "notified_buy": False,
        "notified_strong": False,
        "notified_rise": False,
        "notified_strong_rise": False,
        "evening_sent": False,
    }


def save_day_state(state: dict):
    _write_file(DAY_STATE_FILE, state)


# ── Buy/Sell Log & Portfolio ───────────────────────────────────
def _get_entries() -> list:
    """Get all buy/sell entries. Backward-compatible with old buy-only logs."""
    entries = _read_file(BUY_LOG_FILE)
    # Migrate old entries that lack a "type" field
    for e in entries:
        if "type" not in e:
            e["type"] = "buy"
    return entries


def _save_entries(entries: list):
    _write_file(BUY_LOG_FILE, entries)


def log_buy(amount_thb: float, price_per_gram: float):
    """Log a gold purchase."""
    entries = _get_entries()
    now = datetime.now(BANGKOK_TZ)
    grams = round(amount_thb / price_per_gram, 4)
    entry = {
        "type": "buy",
        "ts": now.isoformat(),
        "amount_thb": amount_thb,
        "price_per_gram": price_per_gram,
        "grams": grams,
    }
    entries.append(entry)
    _save_entries(entries)
    return entry


def log_sell(amount_thb: float, price_per_gram: float):
    """Log a gold sale. Returns entry dict or None if not enough gold."""
    entries = _get_entries()
    # Calculate current holdings
    total_grams = sum(
        e["grams"] if e["type"] == "buy" else -e["grams"]
        for e in entries
    )
    grams_to_sell = round(amount_thb / price_per_gram, 4)
    if grams_to_sell > total_grams + 0.0001:  # small tolerance
        return None  # not enough gold

    now = datetime.now(BANGKOK_TZ)
    entry = {
        "type": "sell",
        "ts": now.isoformat(),
        "amount_thb": amount_thb,
        "price_per_gram": price_per_gram,
        "grams": grams_to_sell,
    }
    entries.append(entry)
    _save_entries(entries)
    return entry


def edit_entry(index: int, new_amount_thb: float) -> dict | None:
    """Edit an entry's THB amount by 1-based index. Recalculates grams."""
    entries = _get_entries()
    if index < 1 or index > len(entries):
        return None
    e = entries[index - 1]
    e["amount_thb"] = new_amount_thb
    e["grams"] = round(new_amount_thb / e["price_per_gram"], 4)
    _save_entries(entries)
    return e


def delete_entry(index: int) -> dict | None:
    """Delete an entry by 1-based index. Returns the removed entry."""
    entries = _get_entries()
    if index < 1 or index > len(entries):
        return None
    removed = entries.pop(index - 1)
    _save_entries(entries)
    return removed


def get_portfolio() -> dict:
    """Calculate portfolio summary from buy/sell log."""
    entries = _get_entries()
    if not entries:
        return {
            "total_invested": 0, "total_grams": 0, "avg_cost": 0,
            "num_buys": 0, "num_sells": 0,
            "total_sold": 0, "realized_pnl": 0,
            "entries": [],
        }

    buys = [e for e in entries if e["type"] == "buy"]
    sells = [e for e in entries if e["type"] == "sell"]

    total_bought_thb = sum(b["amount_thb"] for b in buys)
    total_bought_grams = sum(b["grams"] for b in buys)
    total_sold_thb = sum(s["amount_thb"] for s in sells)
    total_sold_grams = sum(s["grams"] for s in sells)

    net_grams = round(total_bought_grams - total_sold_grams, 4)
    avg_buy_cost = round(total_bought_thb / total_bought_grams, 2) if total_bought_grams > 0 else 0

    # Realized P&L: sell revenue minus cost basis of sold grams
    cost_of_sold = round(total_sold_grams * avg_buy_cost, 2)
    realized_pnl = round(total_sold_thb - cost_of_sold, 2)

    # Net invested = what's still "in" the portfolio
    net_invested = round(total_bought_thb - cost_of_sold, 2)

    return {
        "total_invested": net_invested,
        "total_grams": net_grams,
        "avg_cost": avg_buy_cost,
        "num_buys": len(buys),
        "num_sells": len(sells),
        "total_bought_thb": round(total_bought_thb, 2),
        "total_sold_thb": round(total_sold_thb, 2),
        "realized_pnl": realized_pnl,
        "entries": entries[-10:],
    }


def get_portfolio_pnl(current_price: float) -> dict:
    """Calculate P&L at current market price."""
    portfolio = get_portfolio()
    if portfolio["total_grams"] <= 0:
        return {**portfolio, "current_value": 0, "pnl_thb": portfolio["realized_pnl"],
                "pnl_pct": 0, "unrealized_pnl": 0}
    current_value = round(portfolio["total_grams"] * current_price, 2)
    unrealized_pnl = round(current_value - portfolio["total_invested"], 2)
    total_pnl = round(unrealized_pnl + portfolio["realized_pnl"], 2)
    pnl_pct = round((total_pnl / portfolio["total_bought_thb"]) * 100, 2) if portfolio["total_bought_thb"] > 0 else 0
    return {
        **portfolio,
        "current_price": current_price,
        "current_value": current_value,
        "unrealized_pnl": unrealized_pnl,
        "pnl_thb": total_pnl,
        "pnl_pct": pnl_pct,
    }


# ── Bot State (Telegram update offset, user settings) ──────────
def load_bot_state() -> dict:
    state = _read_file(BOT_STATE_FILE)
    return state or {"update_offset": 0, "drop_threshold": 0.5}


def save_bot_state(state: dict):
    _write_file(BOT_STATE_FILE, state)


# ── Model Data (stored predictions + training metadata) ────────
def load_model_data() -> dict:
    return _read_file(MODEL_DATA_FILE) or {"predictions": [], "last_trained": None}


def save_model_data(data: dict):
    _write_file(MODEL_DATA_FILE, data)


# ── Utility: create Gist if not exists ──────────────────────────
def create_gist_if_needed() -> str:
    """Create a new private Gist and return its ID. Use once during setup."""
    if not GITHUB_TOKEN:
        print("[storage] No GITHUB_TOKEN — cannot create Gist")
        return ""
    try:
        r = requests.post(
            "https://api.github.com/gists",
            headers=HEADERS, timeout=15,
            json={
                "description": "Gold Monitor Data Store",
                "public": False,
                "files": {
                    PRICE_HISTORY_FILE: {"content": "[]"},
                    BUY_LOG_FILE: {"content": "[]"},
                    DAY_STATE_FILE: {"content": "{}"},
                    BOT_STATE_FILE: {"content": json.dumps({"update_offset": 0, "drop_threshold": 0.5})},
                    MODEL_DATA_FILE: {"content": json.dumps({"predictions": [], "last_trained": None})},
                },
            },
        )
        r.raise_for_status()
        gist_id = r.json()["id"]
        print(f"[storage] Created Gist: {gist_id}")
        return gist_id
    except Exception as e:
        print(f"[storage] Gist creation failed: {e}")
        return ""
