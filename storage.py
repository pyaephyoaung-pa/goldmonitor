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


# ── Buy Log / Portfolio ─────────────────────────────────────────
def log_buy(amount_thb: float, price_per_gram: float):
    """Log a gold purchase."""
    buys = _read_file(BUY_LOG_FILE)
    now = datetime.now(BANGKOK_TZ)
    grams = round(amount_thb / price_per_gram, 4)
    entry = {
        "ts": now.isoformat(),
        "amount_thb": amount_thb,
        "price_per_gram": price_per_gram,
        "grams": grams,
    }
    buys.append(entry)
    _write_file(BUY_LOG_FILE, buys)
    return entry


def get_portfolio() -> dict:
    """Calculate portfolio summary from buy log."""
    buys = _read_file(BUY_LOG_FILE)
    if not buys:
        return {
            "total_invested": 0,
            "total_grams": 0,
            "avg_cost": 0,
            "num_buys": 0,
            "buys": [],
        }
    total_invested = sum(b["amount_thb"] for b in buys)
    total_grams = sum(b["grams"] for b in buys)
    avg_cost = round(total_invested / total_grams, 2) if total_grams > 0 else 0
    return {
        "total_invested": round(total_invested, 2),
        "total_grams": round(total_grams, 4),
        "avg_cost": avg_cost,
        "num_buys": len(buys),
        "buys": buys[-10:],  # last 10 buys
    }


def get_portfolio_pnl(current_price: float) -> dict:
    """Calculate P&L at current market price."""
    portfolio = get_portfolio()
    if portfolio["total_grams"] == 0:
        return {**portfolio, "current_value": 0, "pnl_thb": 0, "pnl_pct": 0}
    current_value = round(portfolio["total_grams"] * current_price, 2)
    pnl_thb = round(current_value - portfolio["total_invested"], 2)
    pnl_pct = round((pnl_thb / portfolio["total_invested"]) * 100, 2)
    return {
        **portfolio,
        "current_price": current_price,
        "current_value": current_value,
        "pnl_thb": pnl_thb,
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
