"""
GitHub Gist-based persistent storage for Gold Monitor.
Stores: price history, buy logs, model state, bot update offset.
"""

from __future__ import annotations

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
SUBSCRIBERS_FILE = "subscribers.json"
LEVEL_ALERTS_FILE = "level_alerts.json"

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

# The analytics layer (trend windows, ML horizons, the 720-point/30-day cap)
# assumes ONE price point per HOUR. The monitor cron fires every 5 minutes for
# alert responsiveness, so appends must be throttled to hourly here — otherwise
# "24h change" would really be a 2-hour change and the history cap ~2.5 days.
MIN_APPEND_INTERVAL_MIN = 55


def _minutes_since_last(history: list, now: datetime) -> float | None:
    """Minutes since the newest stored point (None if empty/unparseable)."""
    if not history:
        return None
    try:
        last_ts = datetime.fromisoformat(history[-1]["ts"])
        return (now - last_ts).total_seconds() / 60.0
    except (KeyError, ValueError, TypeError):
        return None


def append_price(thb_gram: float, usd_oz: float, thb_rate: float):
    """Append a price data point at most once per hour. Keep last 720 entries
    (~30 days hourly).

    Best-effort concurrency guard: the Gist is a shared store with no locking,
    so two overlapping runs could each read, append, and overwrite each other —
    losing a point. To narrow that window we re-read the freshest copy right
    before writing and merge by timestamp (deduping). This does not fully
    eliminate the race (a proper fix needs a real datastore), but it makes
    concurrent appends far less likely to clobber data.
    """
    now = datetime.now(BANGKOK_TZ)
    entry = {
        "ts": now.isoformat(),
        "thb_gram": thb_gram,
        "usd_oz": usd_oz,
        "thb_rate": thb_rate,
        "hour": now.hour,
        "weekday": now.weekday(),
    }

    # Re-read immediately before writing to pick up any concurrent appends.
    history = _read_file(PRICE_HISTORY_FILE)

    # Hourly throttle: skip the append (but still return current history) if
    # the newest point is fresher than MIN_APPEND_INTERVAL_MIN.
    mins = _minutes_since_last(history, now)
    if mins is not None and 0 <= mins < MIN_APPEND_INTERVAL_MIN:
        return history

    seen_ts = {h.get("ts") for h in history}
    if entry["ts"] not in seen_ts:
        history.append(entry)

    # Stable de-dup by timestamp, then keep the most recent 720 points.
    deduped = {}
    for h in history:
        deduped[h.get("ts")] = h
    history = sorted(deduped.values(), key=lambda h: h.get("ts", ""))[-720:]

    _write_file(PRICE_HISTORY_FILE, history)
    return history


def get_price_history(limit: int = 720) -> list:
    """Get recent price history."""
    history = _read_file(PRICE_HISTORY_FILE)
    return history[-limit:]


# ── Day State (replaces gold_state.json) ────────────────────────
def load_day_state() -> dict:
    """Load today's state, reset if date changed.

    On a new day, carry yesterday's last observed price into `prev_close` so the
    monitor can detect overnight / day-boundary gap-down moves that the intraday
    open-based alerts would otherwise miss.
    """
    today = datetime.now(BANGKOK_TZ).strftime("%Y-%m-%d")
    state = _read_file(DAY_STATE_FILE)
    if isinstance(state, dict) and state.get("date") == today:
        return state
    prev_close = state.get("last_price") if isinstance(state, dict) else None
    return {
        "date": today,
        "open_price": None,
        "day_low": None,
        "day_high": None,
        "prev_close": prev_close,
        "last_price": prev_close,
        "notified_drop_1": False,
        "notified_drop_2": False,
        "notified_drop_3": False,
        "notified_drop_4": False,
        "notified_drop_5": False,
        "notified_rise_1": False,
        "notified_rise_2": False,
        "notified_rise_3": False,
        "notified_rise_4": False,
        "notified_rise_5": False,
        "notified_gap": False,
        "morning_sent": False,
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


# ── Subscribers ────────────────────────────────────────────────
def get_subscribers() -> list:
    """Get list of subscriber chat IDs."""
    data = _read_file(SUBSCRIBERS_FILE)
    if isinstance(data, list):
        return data
    return data.get("chat_ids", [])


def add_subscriber(chat_id: str) -> bool:
    """Add a subscriber. Returns True if newly added, False if already exists."""
    subs = get_subscribers()
    if chat_id in subs:
        return False
    subs.append(chat_id)
    _write_file(SUBSCRIBERS_FILE, {"chat_ids": subs})
    return True


def remove_subscriber(chat_id: str) -> bool:
    """Remove a subscriber. Returns True if removed, False if not found."""
    data = _read_file(SUBSCRIBERS_FILE)
    subs = get_subscribers()
    if chat_id not in subs:
        return False
    subs.remove(chat_id)
    prefs = data.get("prefs", {}) if isinstance(data, dict) else {}
    prefs.pop(str(chat_id), None)
    _write_file(SUBSCRIBERS_FILE, {"chat_ids": subs, "prefs": prefs})
    return True


# ── Per-user notification preferences ───────────────────────────
# Stored alongside subscribers: {"chat_ids": [...], "prefs": {chat_id: {...}}}
# Categories: "morning", "evening", "alerts" (drop/rise broadcasts).
# "quiet" is "HH-HH" (BKK hours, suppress from first up to second) or None.

PREF_DEFAULTS = {"morning": True, "evening": True, "alerts": True, "quiet": None}
PREF_CATEGORIES = ("morning", "evening", "alerts")


def get_user_prefs(chat_id: str) -> dict:
    data = _read_file(SUBSCRIBERS_FILE)
    prefs = data.get("prefs", {}) if isinstance(data, dict) else {}
    return {**PREF_DEFAULTS, **prefs.get(str(chat_id), {})}


def set_user_pref(chat_id: str, key: str, value) -> dict:
    """Set one preference key for a user; returns their full prefs."""
    data = _read_file(SUBSCRIBERS_FILE)
    if not isinstance(data, dict):
        data = {"chat_ids": data if isinstance(data, list) else []}
    prefs = data.setdefault("prefs", {})
    user = prefs.setdefault(str(chat_id), {})
    user[key] = value
    _write_file(SUBSCRIBERS_FILE, data)
    return {**PREF_DEFAULTS, **user}


def parse_quiet_hours(spec: str) -> tuple | None:
    """Parse 'HH-HH' (e.g. '22-7') into (start, end) hours, or None if invalid."""
    m = spec.strip().split("-")
    if len(m) != 2:
        return None
    try:
        start, end = int(m[0]), int(m[1])
    except ValueError:
        return None
    if not (0 <= start <= 23 and 0 <= end <= 23) or start == end:
        return None
    return start, end


def in_quiet_hours(quiet: str | None, hour: int) -> bool:
    """True if `hour` falls inside the user's quiet window (handles wrap)."""
    if not quiet:
        return False
    parsed = parse_quiet_hours(quiet)
    if parsed is None:
        return False
    start, end = parsed
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end  # wraps midnight, e.g. 22-7


def get_all_prefs() -> dict:
    """All users' prefs in one read (avoid per-recipient Gist round-trips)."""
    data = _read_file(SUBSCRIBERS_FILE)
    return data.get("prefs", {}) if isinstance(data, dict) else {}


def prefs_allow(user_prefs: dict, category: str, hour: int) -> bool:
    """Pure check: do these prefs allow a `category` broadcast at BKK `hour`?"""
    merged = {**PREF_DEFAULTS, **(user_prefs or {})}
    if category in PREF_CATEGORIES and not merged.get(category, True):
        return False
    return not in_quiet_hours(merged.get("quiet"), hour)


# ── Price-level Alerts (per-user, one-shot) ────────────────────
MAX_ALERTS_PER_USER = 5


def get_level_alerts() -> dict:
    """All level alerts: {chat_id: [{"dir", "price", "created"}, ...]}."""
    data = _read_file(LEVEL_ALERTS_FILE)
    return data if isinstance(data, dict) else {}


def get_user_alerts(chat_id: str) -> list:
    return get_level_alerts().get(str(chat_id), [])


def add_level_alert(chat_id: str, direction: str, price: float) -> bool:
    """Add a one-shot level alert. Returns False if user hit the limit."""
    alerts = get_level_alerts()
    user_alerts = alerts.get(str(chat_id), [])
    if len(user_alerts) >= MAX_ALERTS_PER_USER:
        return False
    user_alerts.append({
        "dir": direction,
        "price": round(price, 2),
        "created": datetime.now(BANGKOK_TZ).isoformat(),
    })
    alerts[str(chat_id)] = user_alerts
    _write_file(LEVEL_ALERTS_FILE, alerts)
    return True


def remove_level_alert(chat_id: str, index: int) -> dict | None:
    """Remove a user's alert by 1-based index. Returns removed alert or None."""
    alerts = get_level_alerts()
    user_alerts = alerts.get(str(chat_id), [])
    if index < 1 or index > len(user_alerts):
        return None
    removed = user_alerts.pop(index - 1)
    if user_alerts:
        alerts[str(chat_id)] = user_alerts
    else:
        alerts.pop(str(chat_id), None)
    _write_file(LEVEL_ALERTS_FILE, alerts)
    return removed


def pop_triggered_alerts(current_price: float) -> list:
    """Return [(chat_id, alert), ...] whose level was crossed; remove them.

    One-shot semantics: a triggered alert fires once and is deleted.
    """
    alerts = get_level_alerts()
    triggered, remaining = [], {}
    for chat_id, user_alerts in alerts.items():
        keep = []
        for a in user_alerts:
            crossed = (
                (a.get("dir") == "above" and current_price >= a.get("price", 0)) or
                (a.get("dir") == "below" and current_price <= a.get("price", 0))
            )
            if crossed:
                triggered.append((chat_id, a))
            else:
                keep.append(a)
        if keep:
            remaining[chat_id] = keep
    if triggered:
        _write_file(LEVEL_ALERTS_FILE, remaining)
    return triggered


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
