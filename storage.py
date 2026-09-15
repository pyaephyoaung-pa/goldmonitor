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

import i18n

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
RATE_LIMIT_FILE = "rate_limit.json"

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


def _file_content(entry: dict) -> str | None:
    """Content of one Gist file entry, refetching if the API truncated it.

    GitHub inlines file content only up to 1 MB and sets `truncated: true`
    beyond that. model_data.json (three exported models + the prediction log)
    is the file most likely to cross that line. Parsing a truncated body
    raises, which used to be swallowed into an empty container — and the next
    write then persisted that emptiness over real data. Follow `raw_url`
    instead so a large file still reads correctly.
    """
    if not entry.get("truncated"):
        return entry.get("content")
    raw_url = entry.get("raw_url")
    if not raw_url:
        print("[storage] File truncated by the Gist API and no raw_url given")
        return None
    try:
        r = requests.get(raw_url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"[storage] Truncated-file refetch failed: {e}")
        return None


# ── Per-run cache ───────────────────────────────────────────────
#
# _get_gist downloads EVERY file in the Gist — the price history, the buy log
# and the exported models all ride along on a read of bot_state.json. A single
# monitor run did that 3-6 times, every five minutes, and a single /price does
# it twice (once to resolve the user's language, once for the history).
#
# So the fetched files are cached for the length of one logical run. Three
# rules keep that honest:
#
#   1. A failed or empty fetch is never cached. Caching it would make every
#      later read in the run see "no data", and a caller that then wrote would
#      persist that emptiness over real data — the exact failure _read_file's
#      docstring warns about.
#   2. Writes update the cache in place, and only when they actually landed,
#      so a read after a write sees what was written and never resurrects the
#      pre-write copy.
#   3. append_price re-reads with fresh=True. That pre-write re-read exists to
#      pick up a CONCURRENT run's appends; serving it from our own cache would
#      quietly remove the guard.
#
# The cron entrypoints are fresh processes, but a warm Vercel container is not
# — so dispatch_update calls reset_cache() per update, scoping the cache to one
# command rather than to the container's lifetime.

_gist_cache: dict | None = None


def reset_cache():
    """Forget the cached Gist. Call at the start of a logical run."""
    global _gist_cache
    _gist_cache = None


def _gist_files(fresh: bool = False) -> dict:
    """The Gist's files, from cache unless `fresh` or nothing is cached yet."""
    global _gist_cache
    if fresh or _gist_cache is None:
        files = _get_gist()
        if not files:
            return files  # rule 1: never cache a failed or empty fetch
        _gist_cache = files
    return _gist_cache


def _cache_put(contents: dict):
    """Put resolved file text into the cache. No-op if nothing is cached yet.

    Used for two things: reflecting a landed write (rule 2), and storing the
    body of a file the Gist API truncated, so the raw_url refetch below happens
    once per run rather than on every read of the largest file we have.
    """
    if _gist_cache is None:
        return
    for name, content in contents.items():
        _gist_cache[name] = {"content": content, "truncated": False}


def _read_file(filename: str, fresh: bool = False) -> dict | list:
    """Read a single JSON file from the Gist.

    Returns an empty container when the file is absent or unreadable. Callers
    that go on to WRITE the same file must treat an empty result as "no data
    yet", never as "data was deleted" — see save_model_data.

    `fresh` bypasses the per-run cache; see the note above it.
    """
    files = _gist_files(fresh)
    if filename in files:
        try:
            entry = files[filename]
            content = _file_content(entry)
            if content is not None:
                if entry.get("truncated"):
                    _cache_put({filename: content})
                return json.loads(content)
        except (json.JSONDecodeError, KeyError) as e:
            print(f"[storage] Could not parse {filename}: {e}")
    # Return appropriate empty container
    if filename in (PRICE_HISTORY_FILE, BUY_LOG_FILE):
        return []
    return {}


def _write_file(filename: str, data) -> bool:
    """Write a single JSON file to the Gist. True if it actually landed.

    Callers that persist "this already happened" state MUST check the result.
    A silently dropped write means the next run re-reads the old state and
    repeats the side effect — a duplicate /bought entry, or the same drop
    alert every five minutes.
    """
    if not GITHUB_TOKEN or not GIST_ID:
        print(f"[storage] No Gist credentials — skipping write for {filename}")
        return False
    content = json.dumps(data, indent=2)
    try:
        r = requests.patch(
            f"https://api.github.com/gists/{GIST_ID}",
            headers=HEADERS, timeout=15,
            json={"files": {filename: {"content": content}}},
        )
        r.raise_for_status()
        _cache_put({filename: content})
        return True
    except Exception as e:
        print(f"[storage] Gist write error ({filename}): {e}")
        return False


def _write_files(file_dict: dict) -> bool:
    """Write multiple files to the Gist in one API call. True if it landed."""
    if not GITHUB_TOKEN or not GIST_ID:
        return False
    contents = {name: json.dumps(data, indent=2)
                for name, data in file_dict.items()}
    try:
        r = requests.patch(
            f"https://api.github.com/gists/{GIST_ID}",
            headers=HEADERS, timeout=15,
            json={"files": {n: {"content": c} for n, c in contents.items()}},
        )
        r.raise_for_status()
        _cache_put(contents)
        return True
    except Exception as e:
        print(f"[storage] Gist batch write error: {e}")
        return False


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
    # fresh=True on purpose: this is the guard, and our own cache cannot see
    # what another run wrote.
    history = _read_file(PRICE_HISTORY_FILE, fresh=True)

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


def save_day_state(state: dict) -> bool:
    return _write_file(DAY_STATE_FILE, state)


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


class InsufficientGold(Exception):
    """An edit or delete would leave the ledger selling gold never held."""


# Rounding slack, in grams, when comparing a sale against holdings.
GRAM_TOLERANCE = 0.0001


def _replay(entries: list) -> dict:
    """Walk the ledger in order, carrying a moving-average cost pool.

    Every sale takes its cost basis from the average cost of the gold held AT
    THAT MOMENT. That is the whole point of replaying rather than averaging
    over the finished ledger: the old code divided TOTAL buy value by TOTAL
    grams bought, including buys made AFTER a sale, so buying more gold today
    silently rewrote the profit reported for a sale last month.

    Entries are in append order, which is chronological — nothing reorders
    them, and /edit only changes an amount in place.

    `oversold` is grams a sale claimed beyond what the pool held; it is only
    ever non-zero for a ledger that /edit or /delete would have corrupted, and
    is what those two check before saving.
    """
    grams = cost = realized = 0.0
    bought_thb = bought_grams = sold_thb = oversold = 0.0
    buys = sells = 0

    for e in entries:
        e_grams = e.get("grams") or 0.0
        amount = e.get("amount_thb") or 0.0
        if e.get("type", "buy") == "buy":
            buys += 1
            bought_thb += amount
            bought_grams += e_grams
            grams += e_grams
            cost += amount
            continue

        sells += 1
        sold_thb += amount
        avg = cost / grams if grams > 0 else 0.0
        taken = min(e_grams, grams)
        oversold += e_grams - taken
        basis = taken * avg
        realized += amount - basis
        grams -= taken
        cost -= basis

    # Average cost of what is still HELD. With nothing held there is no such
    # thing, so fall back to the lifetime average buy price, which is what
    # /portfolio showed before and still reads sensibly next to a realized P&L.
    if grams > 0:
        avg_cost = cost / grams
    elif bought_grams > 0:
        avg_cost = bought_thb / bought_grams
    else:
        avg_cost = 0.0

    return {
        "grams": round(grams, 4),
        "cost": round(cost, 2),
        "avg_cost": round(avg_cost, 2),
        "realized": round(realized, 2),
        "bought_thb": round(bought_thb, 2),
        "sold_thb": round(sold_thb, 2),
        "buys": buys,
        "sells": sells,
        "oversold": round(oversold, 4),
    }


def _reject_if_oversold(entries: list):
    """Guard for /edit and /delete — log_sell checks before appending."""
    if _replay(entries)["oversold"] > GRAM_TOLERANCE:
        raise InsufficientGold()


def log_sell(amount_thb: float, price_per_gram: float):
    """Log a gold sale. Returns entry dict or None if not enough gold."""
    entries = _get_entries()
    total_grams = _replay(entries)["grams"]
    grams_to_sell = round(amount_thb / price_per_gram, 4)
    if grams_to_sell > total_grams + GRAM_TOLERANCE:
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
    """Edit an entry's THB amount by 1-based index. Recalculates grams.

    None if the index does not exist; raises InsufficientGold if the change
    would leave the ledger selling gold that was never held. log_sell refuses
    an oversell on the way in, but editing a sale upwards (or deleting the buy
    that funded it) reached the same broken state from the side — and a
    negative pool then reported a portfolio worth nothing, silently.
    """
    entries = _get_entries()
    if index < 1 or index > len(entries):
        return None
    e = entries[index - 1]
    updated = {**e, "amount_thb": new_amount_thb,
               "grams": round(new_amount_thb / e["price_per_gram"], 4)}

    # Validate the prospective ledger BEFORE touching the stored one.
    _reject_if_oversold(entries[:index - 1] + [updated] + entries[index:])

    entries[index - 1] = updated
    _save_entries(entries)
    return updated


def delete_entry(index: int) -> dict | None:
    """Delete an entry by 1-based index. Returns the removed entry.

    None if the index does not exist; raises InsufficientGold if removing it
    would leave a later sale unfunded — see edit_entry.
    """
    entries = _get_entries()
    if index < 1 or index > len(entries):
        return None

    _reject_if_oversold(entries[:index - 1] + entries[index:])

    removed = entries.pop(index - 1)
    _save_entries(entries)
    return removed


def get_portfolio() -> dict:
    """Calculate portfolio summary from buy/sell log.

    `avg_cost` is the average cost of the gold STILL HELD (the lifetime average
    buy price once everything is sold), and `total_invested` is what that gold
    cost. Both come from replaying the ledger — see _replay.
    """
    entries = _get_entries()
    if not entries:
        return {
            "total_invested": 0, "total_grams": 0, "avg_cost": 0,
            "num_buys": 0, "num_sells": 0,
            "total_sold": 0, "realized_pnl": 0,
            "entries": [],
        }

    book = _replay(entries)
    return {
        # What is still in the portfolio, at the cost it was actually bought
        # for — not total spend minus a retrospectively averaged cost of sales.
        "total_invested": book["cost"],
        "total_grams": book["grams"],
        "avg_cost": book["avg_cost"],
        "num_buys": book["buys"],
        "num_sells": book["sells"],
        "total_bought_thb": book["bought_thb"],
        "total_sold_thb": book["sold_thb"],
        "realized_pnl": book["realized"],
        "entries": entries[-10:],
    }


def get_portfolio_pnl(current_price: float) -> dict:
    """Calculate P&L at current market price."""
    portfolio = get_portfolio()
    if portfolio["total_grams"] <= 0:
        # Fully sold (or nothing bought). Callers still format current_price, so
        # this branch must carry the same keys as the normal one below.
        return {**portfolio, "current_price": current_price, "current_value": 0,
                "pnl_thb": portfolio["realized_pnl"], "pnl_pct": 0,
                "unrealized_pnl": 0}
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


def save_bot_state(state: dict) -> bool:
    return _write_file(BOT_STATE_FILE, state)


# ── Model Data (stored predictions + training metadata) ────────
def load_model_data() -> dict:
    return _read_file(MODEL_DATA_FILE) or {"predictions": [], "last_trained": None}


def save_model_data(data: dict) -> bool:
    return _write_file(MODEL_DATA_FILE, data)


def save_day_state_and_model(state: dict, model_data: dict) -> bool:
    """Persist day state + model data in ONE Gist PATCH.

    A monitor run otherwise issues a separate write per file (and per call),
    each a full authenticated round-trip that widens the read-modify-write race
    on the shared Gist.
    """
    return _write_files({DAY_STATE_FILE: state, MODEL_DATA_FILE: model_data})


# ── Subscribers ────────────────────────────────────────────────
def _subs_of(data) -> list:
    """Subscriber ids out of an already-read subscribers file.

    The file is either the modern {"chat_ids": [...], "prefs": {...}} or a
    bare list from before prefs existed.
    """
    if isinstance(data, list):
        return data
    return data.get("chat_ids", [])


def get_subscribers() -> list:
    """Get list of subscriber chat IDs."""
    return _subs_of(_read_file(SUBSCRIBERS_FILE))


def add_subscriber(chat_id: str) -> bool:
    """Add a subscriber. Returns True if newly added, False if already exists.

    Preserves the sibling "prefs" map: this file holds BOTH the subscriber list
    and every user's notification preferences, so writing only "chat_ids" here
    used to reset everyone's /mute and /quiet settings on each new /subscribe.
    """
    data = _read_file(SUBSCRIBERS_FILE)
    subs = _subs_of(data)
    if chat_id in subs:
        return False
    subs.append(chat_id)
    prefs = data.get("prefs", {}) if isinstance(data, dict) else {}
    _write_file(SUBSCRIBERS_FILE, {"chat_ids": subs, "prefs": prefs})
    return True


def remove_subscriber(chat_id: str) -> bool:
    """Remove a subscriber. Returns True if removed, False if not found."""
    data = _read_file(SUBSCRIBERS_FILE)
    subs = _subs_of(data)
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

PREF_DEFAULTS = {"morning": True, "evening": True, "alerts": True, "quiet": None,
                 "lang": i18n.DEFAULT_LANG}
PREF_CATEGORIES = ("morning", "evening", "alerts")


def get_user_lang(chat_id: str) -> str:
    """The user's interface language code, always one we support."""
    return i18n.normalize(get_user_prefs(chat_id).get("lang"))


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


def get_subscribers_and_prefs() -> tuple:
    """(chat_ids, prefs) from a SINGLE Gist read.

    get_subscribers() + get_all_prefs() pull the same file twice, and _get_gist
    downloads every file in the Gist (including the stored models) each time.
    Broadcast paths that need both should use this instead.
    """
    data = _read_file(SUBSCRIBERS_FILE)
    if isinstance(data, list):
        return data, {}
    return _subs_of(data), data.get("prefs", {})


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


def alert_unit(alert: dict) -> str:
    """Which price a level alert is measured against: 'usd' (per oz) or 'thb'.

    /alert now takes USD/oz, but alerts stored before that switch have no
    "unit" field and are still THB/gram. Reading them as USD would turn an
    "above ฿4,500" target into an unreachable $4,500 one, and every "below"
    target into an instant trigger — so an absent unit means THB, forever.
    """
    return alert.get("unit") or "thb"


def add_level_alert(chat_id: str, direction: str, price: float,
                    unit: str = "usd") -> bool:
    """Add a one-shot level alert. Returns False if user hit the limit."""
    alerts = get_level_alerts()
    user_alerts = alerts.get(str(chat_id), [])
    if len(user_alerts) >= MAX_ALERTS_PER_USER:
        return False
    user_alerts.append({
        "dir": direction,
        "price": round(price, 2),
        "unit": unit,
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


def pop_triggered_alerts(thb_gram: float, usd_oz: float | None = None) -> list:
    """Return [(chat_id, alert), ...] whose level was crossed; remove them.

    Each alert is compared against the price in its own unit (see alert_unit).
    An alert whose unit has no price this run — or that stored no target — is
    kept rather than fired, so a missing spot quote cannot empty the queue.

    One-shot semantics: a triggered alert fires once and is deleted.
    """
    current = {"thb": thb_gram, "usd": usd_oz}
    alerts = get_level_alerts()
    triggered, remaining = [], {}
    for chat_id, user_alerts in alerts.items():
        keep = []
        for a in user_alerts:
            price, target = current.get(alert_unit(a)), a.get("price")
            crossed = price is not None and target is not None and (
                (a.get("dir") == "above" and price >= target) or
                (a.get("dir") == "below" and price <= target)
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


# ── Per-chat rate limiting ──────────────────────────────────────
#
# Anyone can talk to this bot, and every command costs at least one Gist read.
# The GitHub API allows 5,000 authenticated requests an hour, shared with the
# monitor — so a single chat spamming commands can burn the token's quota and
# take the PRICE ALERTS down with it, which is the part nobody would notice
# until a drop went unreported.
#
# The limits below are generous for a person tapping the /help keyboard and
# hard for a script. A refused command costs one cached read and no write, so
# a flood gets cheaper the longer it lasts rather than more expensive.

RATE_WINDOW_SEC = 600        # rolling 10-minute window
RATE_MAX_COMMANDS = 30       # any command
RATE_MAX_EXTERNAL = 10       # commands that call a third-party service


def _now_ts() -> float:
    """Seconds since the epoch, via the module's clock so tests can fix it."""
    return datetime.now(BANGKOK_TZ).timestamp()


def _prune(record: dict, now: float) -> dict:
    """Drop everything in `record` that has aged out of the window."""
    cutoff = now - RATE_WINDOW_SEC
    hits = [t for t in record.get("hits", []) if t > cutoff]
    external = [t for t in record.get("external", []) if t > cutoff]
    pruned = {"hits": hits, "external": external}
    notified = record.get("notified_at")
    if notified and notified > cutoff:
        pruned["notified_at"] = notified
    return pruned


def allow_command(chat_id: str, external: bool = False) -> dict:
    """May `chat_id` run another command right now? Records it if so.

    Returns {"allowed", "notify", "retry_after"}. `notify` is True only the
    FIRST refusal inside a window, so a flood gets one reply rather than one
    per message — and so the refusal itself cannot be used to generate load.
    """
    now = _now_ts()
    data = _read_file(RATE_LIMIT_FILE)
    if not isinstance(data, dict):
        data = {}

    record = _prune(data.get(str(chat_id), {}), now)
    over = (len(record["hits"]) >= RATE_MAX_COMMANDS
            or (external and len(record["external"]) >= RATE_MAX_EXTERNAL))

    if not over:
        record["hits"].append(now)
        if external:
            record["external"].append(now)
        record.pop("notified_at", None)
        data[str(chat_id)] = record
        _write_file(RATE_LIMIT_FILE, _compact(data, now))
        return {"allowed": True, "notify": False, "retry_after": 0}

    # Oldest relevant hit decides when the window frees up again.
    relevant = record["external"] if external and record["external"] else record["hits"]
    retry_after = max(1, int(RATE_WINDOW_SEC - (now - min(relevant))))

    notify = "notified_at" not in record
    if notify:
        record["notified_at"] = now
        data[str(chat_id)] = record
        _write_file(RATE_LIMIT_FILE, _compact(data, now))
    return {"allowed": False, "notify": notify, "retry_after": retry_after}


def _compact(data: dict, now: float) -> dict:
    """Drop chats with nothing left in the window, so the file stays bounded."""
    out = {}
    for cid, record in data.items():
        pruned = _prune(record, now)
        if pruned["hits"] or pruned["external"] or "notified_at" in pruned:
            out[cid] = pruned
    return out


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
