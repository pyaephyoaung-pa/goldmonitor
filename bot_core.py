"""
Unified Telegram bot core for Gold Monitor.

This module is the single source of truth for:
  * sending / receiving Telegram messages
  * every /command handler
  * command dispatch (owner checks, prefix matching)

Both entrypoints — bot_commands.py (polling) and api/webhook.py (instant
webhook) — are now thin wrappers around dispatch_update() here. Previously each
held its own ~400-line copy of these handlers, which drifted out of sync.
"""

from __future__ import annotations

import os
import re
import time
import html as html_module
from datetime import datetime

import pytz
import requests

import storage
import predictor
import goldapi
import signals
from gold_format import fmt, gold_breakdown

BANGKOK_TZ = pytz.timezone("Asia/Bangkok")
TG_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


# ── Telegram I/O ────────────────────────────────────────────────

def send_message(text: str, chat_id: str = "", reply_markup: dict | None = None) -> dict | None:
    """Send a Telegram message (HTML), with a plain-text retry on parse errors.

    `reply_markup` optionally attaches an inline keyboard.
    Returns the Telegram API response dict (or None on hard failure) so callers
    can react to error codes (e.g. 403 = bot blocked).
    """
    cid = chat_id or TG_CHAT_ID
    if not TG_BOT_TOKEN or not cid:
        print(f"[bot] No credentials. Message:\n{text}")
        return None
    payload = {"chat_id": cid, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            json=payload,
            timeout=10,
        )
        resp = r.json()
        if resp.get("ok"):
            return resp
        print(f"[bot] Telegram error: {resp.get('description')} (code={resp.get('error_code')})")
        # 429 Too Many Requests — respect Telegram's retry_after and retry once.
        if resp.get("error_code") == 429:
            wait = min(resp.get("parameters", {}).get("retry_after", 1), 30)
            print(f"[bot] Rate limited — retrying after {wait}s")
            time.sleep(wait)
            # Resend the ORIGINAL payload — rebuilding it here used to drop
            # reply_markup, so a rate-limited /help arrived with no buttons.
            r = requests.post(
                f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
                json=payload,
                timeout=10,
            )
            return r.json()
        # Retry without HTML parse_mode in case of a formatting error
        if resp.get("error_code") == 400:
            r2 = requests.post(
                f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
                json={"chat_id": cid, "text": text},
                timeout=10,
            )
            resp2 = r2.json()
            print(f"[bot] Retry without HTML: {'OK' if resp2.get('ok') else 'failed'}")
            return resp2
        return resp
    except Exception as e:
        print(f"[bot] Send error: {e}")
        return None


def answer_callback_query(callback_id: str):
    """Ack a button press so Telegram stops showing the loading spinner."""
    if not TG_BOT_TOKEN:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/answerCallbackQuery",
            json={"callback_query_id": callback_id},
            timeout=10,
        )
    except Exception as e:
        print(f"[bot] answerCallbackQuery error: {e}")


def send_photo(photo_url: str, caption: str, chat_id: str = "") -> dict | None:
    """Send a photo by URL via Telegram sendPhoto."""
    cid = chat_id or TG_CHAT_ID
    if not TG_BOT_TOKEN or not cid:
        print(f"[bot] No credentials. Photo: {photo_url}")
        return None
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendPhoto",
            json={"chat_id": cid, "photo": photo_url,
                  "caption": caption, "parse_mode": "HTML"},
            timeout=15,
        )
        resp = r.json()
        if not resp.get("ok"):
            print(f"[bot] sendPhoto error: {resp.get('description')}")
        return resp
    except Exception as e:
        print(f"[bot] sendPhoto error: {e}")
        return None


def get_updates(offset: int = 0) -> list:
    """Fetch new Telegram messages (long-poll)."""
    if not TG_BOT_TOKEN:
        return []
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getUpdates",
            params={"offset": offset, "timeout": 5, "limit": 20},
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("result", [])
    except Exception as e:
        print(f"[bot] getUpdates error: {e}")
        return []


def webhook_is_configured() -> bool:
    """True if a Telegram webhook URL is set.

    Telegram refuses getUpdates (HTTP 409) while a webhook is active, so the
    poller uses this to self-disable and avoid wasted, conflicting runs.
    """
    if not TG_BOT_TOKEN:
        return False
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getWebhookInfo",
            timeout=10,
        )
        r.raise_for_status()
        return bool(r.json().get("result", {}).get("url"))
    except Exception as e:
        print(f"[bot] getWebhookInfo error: {e}")
        return False


# ── Command Handlers ────────────────────────────────────────────

def cmd_price(chat_id: str):
    thb_gram, usd_oz, thb_rate = goldapi.get_gold_price()
    if thb_gram is None:
        send_message("⚠️ ဈေးနှုန်း ယူမရပါ — API error", chat_id)
        return

    history = storage.get_price_history()
    trend = predictor.get_trend_summary(history) if history else {}
    gb = gold_breakdown(thb_gram)

    lines = [
        "💰 <b>ရွှေဈေး အခုလက်ရှိ</b>",
        "━━━━━━━━━━━━━━━",
        "🥇 <b>99.99% (Pure)</b>",
        f"  ဘတ်သား: {fmt(gb['baht_9999'])}",
        f"  1g: {fmt(gb['gram_9999'])}",
        "🥈 <b>96.50%</b>",
        f"  ဘတ်သား: {fmt(gb['baht_9650'])}",
        f"  1g: {fmt(gb['gram_9650'])}",
        "━━━━━━━━━━━━━━━",
        f"🌐 USD : ${usd_oz}/oz",
        f"💱 Rate: 1 USD = {thb_rate} THB",
    ]

    if trend.get("change_1h") is not None:
        lines.append("\n📊 <b>Changes:</b>")
        for key, label in [("change_1h", "1h"), ("change_4h", "4h"),
                           ("change_24h", "24h"), ("change_7d", "7d")]:
            if key in trend:
                arrow = "📈" if trend[key] > 0 else "📉" if trend[key] < 0 else "➡️"
                lines.append(f"  {arrow} {label}: {trend[key]:+.3f}%")

    if len(history) >= 14:
        ta = predictor.analyze(history)
        if ta.get("overall_signal"):
            lines.append(f"\n🎯 Signal: <b>{ta['overall_signal']}</b>")
        if ta.get("rsi"):
            lines.append(f"📊 RSI: {ta['rsi']}")

    send_message("\n".join(lines), chat_id)


def cmd_predict(chat_id: str):
    history = storage.get_price_history()
    if len(history) < 15:
        send_message(
            f"📊 Data points: {len(history)}/100\n"
            f"TA requires 15+, ML requires 100+.\n"
            f"Keep running — data accumulates every hour!",
            chat_id,
        )
        return

    model_data = storage.load_model_data()
    # Score any matured predictions first so the hit-rate shown is current.
    if predictor.resolve_predictions(model_data, history):
        storage.save_model_data(model_data)
    prediction = predictor.predict(history, model_data)
    prediction["hit_rates"] = predictor.prediction_hit_rates(model_data)
    msg = predictor.format_prediction_message(prediction)
    send_message(msg, chat_id)


# ── /chart — price chart via QuickChart (no matplotlib dependency) ──

QUICKCHART_CREATE_URL = "https://quickchart.io/chart/create"
CHART_MAX_POINTS = 96  # downsample target so the config stays small


def _downsample(items: list, max_points: int) -> list:
    """Evenly thin a list to at most max_points, always keeping the last item."""
    if len(items) <= max_points:
        return items
    step = len(items) / max_points
    sampled = [items[int(i * step)] for i in range(max_points)]
    if sampled[-1] is not items[-1]:
        sampled[-1] = items[-1]
    return sampled


def chart_points(history: list, days: int) -> list:
    """The priced points backing both the chart and its caption.

    Single source of truth on purpose: the caption used to slice the raw
    history and filter afterwards, while the config filtered and then sliced,
    so any entry missing "thb_gram" made the two disagree about the window —
    and could leave the caption with an empty list to index.
    """
    return [h for h in history if "thb_gram" in h][-days * 24:]


def build_chart_config(history: list, days: int) -> dict | None:
    """Build a Chart.js config for the last `days` of price history."""
    points = chart_points(history, days)
    if len(points) < 2:
        return None
    points = _downsample(points, CHART_MAX_POINTS)
    labels = [p["ts"][5:16].replace("T", " ") for p in points]  # "MM-DD HH:MM"
    prices = [p["thb_gram"] for p in points]
    return {
        "type": "line",
        "data": {
            "labels": labels,
            "datasets": [{
                "label": "THB/gram (99.99%)",
                "data": prices,
                "borderColor": "#d4a017",
                "backgroundColor": "rgba(212,160,23,0.15)",
                "fill": True,
                "pointRadius": 0,
                "borderWidth": 2,
                "tension": 0.2,
            }],
        },
        "options": {
            "title": {"display": True, "text": f"Gold Price — last {days}d"},
            "legend": {"display": False},
            "scales": {
                "xAxes": [{"ticks": {"maxTicksLimit": 8, "fontSize": 9}}],
                "yAxes": [{"ticks": {"maxTicksLimit": 8}}],
            },
        },
    }


def _quickchart_short_url(config: dict) -> str | None:
    """Create a short chart URL via QuickChart's create endpoint."""
    try:
        r = requests.post(
            QUICKCHART_CREATE_URL,
            json={"chart": config, "width": 800, "height": 420,
                  "backgroundColor": "white"},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("success") and data.get("url"):
            return data["url"]
    except Exception as e:
        print(f"[bot] quickchart error: {e}")
    return None


def cmd_chart(chat_id: str, args: str):
    try:
        days = int(args.strip()) if args.strip() else 7
    except ValueError:
        days = 7
    days = max(1, min(days, 30))

    history = storage.get_price_history()
    config = build_chart_config(history, days)
    if config is None:
        send_message("📊 Data collecting — not enough history for a chart yet", chat_id)
        return

    url = _quickchart_short_url(config)
    if url is None:
        send_message("⚠️ Chart service unavailable — ခဏနေ ပြန်စမ်းပါ", chat_id)
        return

    prices = [p["thb_gram"] for p in chart_points(history, days)]
    change = ((prices[-1] - prices[0]) / prices[0]) * 100 if prices[0] else 0
    arrow = "📈" if change >= 0 else "📉"
    caption = (
        f"📊 <b>ရွှေဈေး {days}-Day Chart</b>\n"
        f"💰 Now: {fmt(prices[-1])}/g | {arrow} {change:+.2f}%\n"
        f"⬆️ High: {fmt(max(prices))} | ⬇️ Low: {fmt(min(prices))}"
    )
    resp = send_photo(url, caption, chat_id)
    if not resp or not resp.get("ok"):
        # Fallback: at least give the user the link.
        send_message(f"{caption}\n🔗 {url}", chat_id)


def cmd_macro(chat_id: str):
    """Show the macro & fear context (DXY / US10Y / VIX) on demand."""
    block = signals.format_macro_block()
    if not block:
        send_message("⚠️ Macro data ယူမရပါ — ခဏနေ ပြန်စမ်းပါ", chat_id)
        return
    send_message(
        f"{block}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"ℹ️ Gold drivers — context only, not a forecast",
        chat_id,
    )


def cmd_bought(chat_id: str, args: str):
    try:
        amount = float(args.strip())
    except (ValueError, AttributeError):
        send_message(
            "📝 Usage: <code>/bought 5000</code>\n"
            "5000 = ဝယ်ယူသည့် ငွေပမာဏ (THB)",
            chat_id,
        )
        return

    if amount <= 0:
        send_message("⚠️ ပမာဏ 0 ထက်ကြီးရပါမည်", chat_id)
        return

    thb_gram, _, _ = goldapi.get_gold_price()
    if thb_gram is None:
        send_message("⚠️ ဈေးနှုန်း ယူမရ — ထပ်ကြိုးစားပါ", chat_id)
        return

    entry = storage.log_buy(amount, thb_gram)
    send_message(
        f"✅ <b>ဝယ်ယူမှု မှတ်တမ်းတင်ပြီး!</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💵 ပမာဏ: {fmt(amount)}\n"
        f"💰 ဈေးနှုန်း: {fmt(thb_gram)}/gram\n"
        f"⚖️ ရွှေ: {entry['grams']:.4f} grams\n"
        f"📅 {datetime.now(BANGKOK_TZ).strftime('%d %b %Y %H:%M')}",
        chat_id,
    )


def cmd_sold(chat_id: str, args: str):
    try:
        amount = float(args.strip())
    except (ValueError, AttributeError):
        send_message(
            "📝 Usage: <code>/sold 5000</code>\n"
            "5000 = ရောင်းချသည့် ငွေပမာဏ (THB)",
            chat_id,
        )
        return

    if amount <= 0:
        send_message("⚠️ ပမာဏ 0 ထက်ကြီးရပါမည်", chat_id)
        return

    thb_gram, _, _ = goldapi.get_gold_price()
    if thb_gram is None:
        send_message("⚠️ ဈေးနှုန်း ယူမရ — ထပ်ကြိုးစားပါ", chat_id)
        return

    entry = storage.log_sell(amount, thb_gram)
    if entry is None:
        send_message("⚠️ ရွှေ မလုံလောက်ပါ — portfolio ထဲမှာ ရွှေအနည်းငယ်သာ ရှိပါသည်", chat_id)
        return

    send_message(
        f"✅ <b>ရောင်းချမှု မှတ်တမ်းတင်ပြီး!</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💵 ပမာဏ: {fmt(amount)}\n"
        f"💰 ဈေးနှုန်း: {fmt(thb_gram)}/gram\n"
        f"⚖️ ရွှေ: {entry['grams']:.4f} grams\n"
        f"📅 {datetime.now(BANGKOK_TZ).strftime('%d %b %Y %H:%M')}",
        chat_id,
    )


def cmd_edit(chat_id: str, args: str):
    parts = args.strip().split()
    if len(parts) != 2:
        send_message(
            "📝 Usage: <code>/edit 3 6000</code>\n"
            "3 = entry နံပါတ် (/portfolio မှာ ကြည့်ပါ)\n"
            "6000 = ပြင်ဆင်လိုသည့် ပမာဏ (THB)",
            chat_id,
        )
        return

    try:
        index = int(parts[0])
        new_amount = float(parts[1])
    except ValueError:
        send_message("⚠️ /edit &lt;နံပါတ်&gt; &lt;ပမာဏ&gt; — ဂဏန်းဖြစ်ရပါမည်", chat_id)
        return

    if new_amount <= 0:
        send_message("⚠️ ပမာဏ 0 ထက်ကြီးရပါမည်", chat_id)
        return

    entry = storage.edit_entry(index, new_amount)
    if entry is None:
        send_message(f"⚠️ Entry #{index} မရှိပါ — /portfolio မှာ နံပါတ်ကြည့်ပါ", chat_id)
        return

    type_label = "ဝယ်ယူ" if entry["type"] == "buy" else "ရောင်းချ"
    send_message(
        f"✏️ <b>Entry #{index} ပြင်ဆင်ပြီး!</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📋 Type: {type_label}\n"
        f"💵 ပမာဏ: {fmt(new_amount)}\n"
        f"💰 ဈေးနှုန်း: {fmt(entry['price_per_gram'])}/gram\n"
        f"⚖️ ရွှေ: {entry['grams']:.4f} grams",
        chat_id,
    )


def cmd_delete(chat_id: str, args: str):
    try:
        index = int(args.strip())
    except (ValueError, AttributeError):
        send_message(
            "📝 Usage: <code>/delete 3</code>\n"
            "3 = ဖျက်လိုသည့် entry နံပါတ်",
            chat_id,
        )
        return

    entry = storage.delete_entry(index)
    if entry is None:
        send_message(f"⚠️ Entry #{index} မရှိပါ", chat_id)
        return

    type_label = "ဝယ်ယူ" if entry["type"] == "buy" else "ရောင်းချ"
    send_message(
        f"🗑 <b>Entry #{index} ဖျက်ပြီး!</b>\n"
        f"📋 {type_label}: {fmt(entry['amount_thb'])} @ {fmt(entry['price_per_gram'])}/g",
        chat_id,
    )


def cmd_portfolio(chat_id: str):
    thb_gram, _, _ = goldapi.get_gold_price()
    if thb_gram is None:
        send_message("⚠️ ဈေးနှုန်း ယူမရပါ", chat_id)
        return

    pnl = storage.get_portfolio_pnl(thb_gram)
    if pnl["num_buys"] == 0 and pnl["num_sells"] == 0:
        send_message(
            "📂 မှတ်တမ်း မရှိသေးပါ\n"
            "Use: <code>/bought 5000</code> to log a purchase\n"
            "Use: <code>/sold 3000</code> to log a sale",
            chat_id,
        )
        return

    profit_emoji = "🟢" if pnl["pnl_thb"] >= 0 else "🔴"
    lines = [
        "📊 <b>ရွှေ Portfolio</b>",
        "━━━━━━━━━━━━━━━",
        f"📦 Buys: {pnl['num_buys']} | Sells: {pnl['num_sells']}",
        f"💵 Invested: {fmt(pnl['total_invested'])}",
        f"⚖️ Holdings: {pnl['total_grams']:.4f} grams",
        f"📈 Avg buy cost: {fmt(pnl['avg_cost'])}/gram",
        f"💰 Current price: {fmt(pnl['current_price'])}/gram",
        "━━━━━━━━━━━━━━━",
        f"💎 Current value: {fmt(pnl['current_value'])}",
    ]

    if pnl["realized_pnl"] != 0:
        r_emoji = "🟢" if pnl["realized_pnl"] >= 0 else "🔴"
        lines.append(f"{r_emoji} Realized P&L: {fmt(pnl['realized_pnl'])}")
    if pnl.get("unrealized_pnl") is not None and pnl["total_grams"] > 0:
        u_emoji = "🟢" if pnl["unrealized_pnl"] >= 0 else "🔴"
        lines.append(f"{u_emoji} Unrealized P&L: {fmt(pnl['unrealized_pnl'])}")

    lines.append(f"{profit_emoji} <b>Total P&L: {fmt(pnl['pnl_thb'])} ({pnl['pnl_pct']:+.2f}%)</b>")

    if pnl["entries"]:
        total_entries = pnl["num_buys"] + pnl["num_sells"]
        start_idx = max(1, total_entries - len(pnl["entries"]) + 1)
        lines.append("\n📝 <b>Recent entries:</b>")
        for i, e in enumerate(pnl["entries"]):
            idx = start_idx + i
            ts = e["ts"][:10]
            icon = "🟢" if e.get("type", "buy") == "buy" else "🔴"
            label = "BUY" if e.get("type", "buy") == "buy" else "SELL"
            lines.append(f"  {icon} #{idx} {label} {ts}: {fmt(e['amount_thb'])} @ {fmt(e['price_per_gram'])}/g")

    send_message("\n".join(lines), chat_id)


def cmd_history(chat_id: str, args: str):
    try:
        days = int(args.strip()) if args.strip() else 7
    except ValueError:
        days = 7
    # Clamp BOTH ends: `dates[-0:]` is the whole list and `dates[-(-3):]` skips
    # from the front, so 0 and negatives used to dump far more than requested.
    days = max(1, min(days, 30))

    history = storage.get_price_history()
    if len(history) < 2:
        send_message("📊 Data collecting — not enough history yet", chat_id)
        return

    daily = {}
    for h in history:
        date = h["ts"][:10]
        if date not in daily:
            daily[date] = {"prices": [], "usd": []}
        daily[date]["prices"].append(h["thb_gram"])
        daily[date]["usd"].append(h.get("usd_oz", 0))

    dates = sorted(daily.keys())[-days:]
    lines = [f"📊 <b>ရွှေဈေး {len(dates)}-Day History</b>", "━━━━━━━━━━━━━━━"]

    for date in dates:
        p = daily[date]["prices"]
        high, low, close, opn = max(p), min(p), p[-1], p[0]
        change = ((close - opn) / opn) * 100
        arrow = "📈" if change > 0 else "📉" if change < 0 else "➡️"
        lines.append(
            f"{arrow} {date}: {fmt(close)} "
            f"(H:{fmt(high)} L:{fmt(low)} {change:+.2f}%)"
        )

    send_message("\n".join(lines), chat_id)


def cmd_setthreshold(chat_id: str, args: str):
    try:
        val = float(args.strip())
    except (ValueError, AttributeError):
        send_message("Usage: <code>/setthreshold 0.5</code>", chat_id)
        return

    if val <= 0 or val > 10:
        send_message("⚠️ 0.1 — 10 ကြား ဖြစ်ရပါမည်", chat_id)
        return

    bot_state = storage.load_bot_state()
    bot_state["drop_threshold"] = val
    storage.save_bot_state(bot_state)
    # The monitor fires 5 equally spaced levels at 1x–5x this value, so quote
    # the real ladder rather than a "1.5x strong alert" tier that never fires.
    send_message(
        f"✅ Drop alert threshold → <b>{val}%</b>\n"
        f"🟡 L1: ≥{val:g}% | 🟠 L2: ≥{val * 2:g}% | 🔴 L3: ≥{val * 3:g}%\n"
        f"🔴🔴 L4: ≥{val * 4:g}% | 🚨 L5: ≥{val * 5:g}%",
        chat_id,
    )


def cmd_setrisethreshold(chat_id: str, args: str):
    try:
        val = float(args.strip())
    except (ValueError, AttributeError):
        send_message("Usage: <code>/setrisethreshold 0.5</code>", chat_id)
        return

    if val <= 0 or val > 10:
        send_message("⚠️ 0.1 — 10 ကြား ဖြစ်ရပါမည်", chat_id)
        return

    bot_state = storage.load_bot_state()
    bot_state["rise_threshold"] = val
    storage.save_bot_state(bot_state)
    send_message(
        f"✅ Rise alert threshold → <b>{val}%</b>\n"
        f"🟢 L1: ≥{val:g}% | 🟢🟢 L2: ≥{val * 2:g}% | 🟣 L3: ≥{val * 3:g}%\n"
        f"🟣🟣 L4: ≥{val * 4:g}% | 🚀 L5: ≥{val * 5:g}%",
        chat_id,
    )


# ── Price-level alerts ──────────────────────────────────────────

def cmd_alert(chat_id: str, args: str):
    """/alert above 4500  |  /alert below 4200 — one-shot price-level alert."""
    parts = args.strip().lower().split()
    usage = (
        "📝 Usage:\n"
        "<code>/alert above 4500</code> — ဈေး 4500 ရောက်ရင် အကြောင်းကြားပါ\n"
        "<code>/alert below 4200</code> — ဈေး 4200 အောက်ကျရင် အကြောင်းကြားပါ\n"
        "📋 /alerts — သတ်မှတ်ထားသော alerts ကြည့်ပါ"
    )
    if len(parts) != 2 or parts[0] not in ("above", "below"):
        send_message(usage, chat_id)
        return
    try:
        price = float(parts[1].replace(",", ""))
    except ValueError:
        send_message(usage, chat_id)
        return
    if price <= 0:
        send_message("⚠️ ဈေးနှုန်း 0 ထက်ကြီးရပါမည်", chat_id)
        return

    # Sanity check against the current price so "above" alerts below market
    # (which would fire instantly) are rejected with a helpful message.
    thb_gram, _, _ = goldapi.get_gold_price()
    if thb_gram is not None:
        if parts[0] == "above" and price <= thb_gram:
            send_message(
                f"⚠️ လက်ရှိဈေး {fmt(thb_gram)} ထက် မြင့်ရပါမည် (above alert)", chat_id)
            return
        if parts[0] == "below" and price >= thb_gram:
            send_message(
                f"⚠️ လက်ရှိဈေး {fmt(thb_gram)} ထက် နိမ့်ရပါမည် (below alert)", chat_id)
            return

    if not storage.add_level_alert(chat_id, parts[0], price):
        send_message(
            f"⚠️ Alert {storage.MAX_ALERTS_PER_USER} ခုထက် မပိုနိုင်ပါ — "
            f"/delalert ဖြင့် အရင်ဖျက်ပါ",
            chat_id,
        )
        return

    arrow = "⬆️" if parts[0] == "above" else "⬇️"
    send_message(
        f"✅ <b>Alert သတ်မှတ်ပြီး!</b>\n"
        f"{arrow} ဈေး {fmt(price)}/g {'ရောက်' if parts[0] == 'above' else 'အောက်ကျ'}ရင် "
        f"အကြောင်းကြားပါမည်\n"
        f"ℹ️ တစ်ကြိမ်သာ — fire ပြီးရင် auto ဖျက်ပါမည်",
        chat_id,
    )


def cmd_alerts(chat_id: str):
    alerts = storage.get_user_alerts(chat_id)
    if not alerts:
        send_message(
            "📂 Alert မရှိသေးပါ\n"
            "Use: <code>/alert above 4500</code> or <code>/alert below 4200</code>",
            chat_id,
        )
        return
    lines = ["🎯 <b>သင့် Price Alerts</b>", "━━━━━━━━━━━━━━━"]
    for i, a in enumerate(alerts, 1):
        arrow = "⬆️" if a["dir"] == "above" else "⬇️"
        lines.append(f"  #{i} {arrow} {a['dir']} {fmt(a['price'])}/g")
    lines.append("━━━━━━━━━━━━━━━")
    lines.append("🗑 ဖျက်ရန်: <code>/delalert 1</code>")
    send_message("\n".join(lines), chat_id)


def cmd_delalert(chat_id: str, args: str):
    try:
        index = int(args.strip())
    except (ValueError, AttributeError):
        send_message("📝 Usage: <code>/delalert 1</code> (/alerts မှာ နံပါတ်ကြည့်ပါ)", chat_id)
        return
    removed = storage.remove_level_alert(chat_id, index)
    if removed is None:
        send_message(f"⚠️ Alert #{index} မရှိပါ — /alerts မှာ ကြည့်ပါ", chat_id)
        return
    send_message(f"🗑 Alert ဖျက်ပြီး: {removed['dir']} {fmt(removed['price'])}/g", chat_id)


def cmd_subscribe(chat_id: str):
    if TG_CHAT_ID and chat_id == TG_CHAT_ID:
        send_message("✅ သင်က bot owner ဖြစ်ပါတယ် — အမြဲတမ်း alerts ရရှိပါတယ်", chat_id)
        return
    added = storage.add_subscriber(chat_id)
    if added:
        send_message(
            "✅ <b>Subscribe လုပ်ပြီးပါပြီ!</b>\n"
            "🌅 မနက်ခင်း ရွှေဈေး\n"
            "🌙 ညနေ အနှစ်ချုပ်\n"
            "📊 ဈေးနှုန်း alerts\n"
            "━━━━━━━━━━━━━━━\n"
            "ရပ်ချင်ရင် /unsubscribe ရိုက်ပါ",
            chat_id,
        )
    else:
        send_message("ℹ️ Subscribe ဖြစ်ပြီးသားပါ — /unsubscribe နဲ့ ရပ်နိုင်ပါတယ်", chat_id)


def cmd_unsubscribe(chat_id: str):
    if TG_CHAT_ID and chat_id == TG_CHAT_ID:
        send_message("ℹ️ သင်က bot owner ဖြစ်ပါတယ် — unsubscribe လုပ်လို့မရပါ", chat_id)
        return
    removed = storage.remove_subscriber(chat_id)
    if removed:
        send_message("👋 Unsubscribe လုပ်ပြီးပါပြီ — alerts ပို့တော့မှာ မဟုတ်ပါ", chat_id)
    else:
        send_message("ℹ️ Subscribe မလုပ်ရသေးပါ — /subscribe နဲ့ စတင်ပါ", chat_id)


# ── Notification preferences ────────────────────────────────────

_PREF_LABELS = {"morning": "🌅 Morning", "evening": "🌙 Evening", "alerts": "📊 Price alerts"}


def cmd_settings(chat_id: str):
    prefs = storage.get_user_prefs(chat_id)
    lines = ["⚙️ <b>Notification Settings</b>", "━━━━━━━━━━━━━━━"]
    for key, label in _PREF_LABELS.items():
        state = "🔔 ON" if prefs.get(key, True) else "🔕 OFF"
        lines.append(f"  {label}: {state}")
    quiet = prefs.get("quiet")
    lines.append(f"  🤫 Quiet hours: {quiet if quiet else 'OFF'}")
    lines += [
        "━━━━━━━━━━━━━━━",
        "🔕 <code>/mute morning|evening|alerts</code>",
        "🔔 <code>/unmute morning|evening|alerts</code>",
        "🤫 <code>/quiet 22-7</code> | <code>/quiet off</code>",
    ]
    send_message("\n".join(lines), chat_id)


def _cmd_mute_unmute(chat_id: str, args: str, value: bool):
    key = args.strip().lower()
    if key not in storage.PREF_CATEGORIES:
        send_message(
            f"📝 Usage: <code>/{'unmute' if value else 'mute'} morning|evening|alerts</code>",
            chat_id,
        )
        return
    storage.set_user_pref(chat_id, key, value)
    label = _PREF_LABELS[key]
    send_message(
        f"{'🔔' if value else '🔕'} {label} notifications: <b>{'ON' if value else 'OFF'}</b>",
        chat_id,
    )


def cmd_mute(chat_id: str, args: str):
    _cmd_mute_unmute(chat_id, args, False)


def cmd_unmute(chat_id: str, args: str):
    _cmd_mute_unmute(chat_id, args, True)


def cmd_quiet(chat_id: str, args: str):
    spec = args.strip().lower()
    if spec in ("off", "0"):
        storage.set_user_pref(chat_id, "quiet", None)
        send_message("🔔 Quiet hours: <b>OFF</b> — အချိန်မရွေး notifications ရပါမည်", chat_id)
        return
    if storage.parse_quiet_hours(spec) is None:
        send_message(
            "📝 Usage: <code>/quiet 22-7</code> (BKK နာရီ၊ 22:00–07:00 ဆိတ်ငြိမ်)\n"
            "ပိတ်ရန်: <code>/quiet off</code>",
            chat_id,
        )
        return
    storage.set_user_pref(chat_id, "quiet", spec)
    send_message(
        f"🤫 Quiet hours: <b>{spec}</b> (BKK)\n"
        f"ဤအချိန်အတွင်း broadcast notifications မပို့ပါ\n"
        f"ℹ️ /alert price alerts များက ဆက်ရပါမည်",
        chat_id,
    )


# Inline keyboard shown with /help and /start — tap instead of typing.
MAIN_KEYBOARD = {
    "inline_keyboard": [
        [{"text": "💰 Price", "callback_data": "/price"},
         {"text": "🔮 Predict", "callback_data": "/predict"}],
        [{"text": "📊 Chart", "callback_data": "/chart"},
         {"text": "🌍 Macro", "callback_data": "/macro"}],
        [{"text": "🔔 Subscribe", "callback_data": "/subscribe"},
         {"text": "⚙️ Settings", "callback_data": "/settings"}],
    ]
}


def cmd_help(chat_id: str):
    send_message(
        "🤖 <b>Gold Monitor Commands</b>\n"
        "━━━━━━━━━━━━━━━\n"
        "💰 /price — လက်ရှိ ရွှေဈေး\n"
        "🔮 /predict — 4h/12h/24h ခန့်မှန်းချက်\n"
        "📊 /chart [N] — N-day ဈေး chart (default 7)\n"
        "🎯 /alert above|below &lt;THB&gt; — ဈေးရောက်ရင် အကြောင်းကြားပါ\n"
        "📋 /alerts — သင့် alerts | 🗑 /delalert &lt;#&gt;\n"
        "🌍 /macro — DXY / US10Y / VIX + fear score\n"
        "📝 /bought &lt;THB&gt; — ဝယ်ယူမှု မှတ်ပါ\n"
        "📝 /sold &lt;THB&gt; — ရောင်းချမှု မှတ်ပါ\n"
        "✏️ /edit &lt;#&gt; &lt;THB&gt; — entry ပြင်ဆင်ပါ\n"
        "🗑 /delete &lt;#&gt; — entry ဖျက်ပါ\n"
        "📊 /portfolio — Portfolio P&L\n"
        "📈 /history [N] — N-day ဈေးသမိုင်း\n"
        "⚙️ /setthreshold N — Drop alert % ပြောင်းပါ\n"
        "📈 /setrisethreshold N — Rise alert % ပြောင်းပါ\n"
        "🔔 /subscribe — ဈေးနှုန်း alerts ရယူပါ\n"
        "🔕 /unsubscribe — alerts ရပ်ပါ\n"
        "⚙️ /settings — notification settings (mute / quiet hours)\n"
        "❓ /help — ဤ menu\n"
        "━━━━━━━━━━━━━━━\n"
        "⚡ Instant replies via webhook",
        chat_id,
        reply_markup=MAIN_KEYBOARD,
    )


# ── Dispatch ────────────────────────────────────────────────────

# Public commands — anyone can use
PUBLIC_COMMANDS = {
    "/price": lambda cid, _: cmd_price(cid),
    "/predict": lambda cid, _: cmd_predict(cid),
    "/macro": lambda cid, _: cmd_macro(cid),
    "/chart": cmd_chart,
    "/history": cmd_history,
    "/alert": cmd_alert,
    "/alerts": lambda cid, _: cmd_alerts(cid),
    "/delalert": cmd_delalert,
    "/settings": lambda cid, _: cmd_settings(cid),
    "/mute": cmd_mute,
    "/unmute": cmd_unmute,
    "/quiet": cmd_quiet,
    "/subscribe": lambda cid, _: cmd_subscribe(cid),
    "/unsubscribe": lambda cid, _: cmd_unsubscribe(cid),
    "/help": lambda cid, _: cmd_help(cid),
    "/start": lambda cid, _: cmd_help(cid),
}

# Owner-only commands — require matching TELEGRAM_CHAT_ID
OWNER_COMMANDS = {
    "/bought": cmd_bought,
    "/sold": cmd_sold,
    "/edit": cmd_edit,
    "/delete": cmd_delete,
    "/portfolio": lambda cid, _: cmd_portfolio(cid),
    "/setthreshold": cmd_setthreshold,
    "/setrisethreshold": cmd_setrisethreshold,
}

COMMANDS = {**PUBLIC_COMMANDS, **OWNER_COMMANDS}


def _parse_command(text: str) -> tuple:
    """Parse '/cmd@bot args' -> (cmd, args), with prefix-glue recovery.

    Handles user typos like '/bought5000' or '/bought<5000>' by splitting the
    known command prefix off and treating the remainder as args.
    """
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower().split("@")[0]
    args = parts[1] if len(parts) > 1 else ""

    if cmd not in COMMANDS:
        m = re.match(r"^(/\w+)", cmd)
        if m:
            base_cmd = m.group(1)
            if base_cmd in COMMANDS:
                extra = re.sub(r"[<>]", "", cmd[len(base_cmd):]).strip()
                if extra and not args:
                    args = extra
                cmd = base_cmd
    return cmd, args


def dispatch_update(update: dict) -> bool:
    """Process a single Telegram update. Returns True if a command was handled.

    Shared by both the poller and the webhook so command behaviour and access
    control can never drift between the two entrypoints again.
    """
    # Inline keyboard button press — ack the spinner, then re-dispatch the
    # button's callback_data exactly as if the user had typed the command.
    cq = update.get("callback_query")
    if cq:
        if cq.get("id"):
            answer_callback_query(str(cq["id"]))
        data = (cq.get("data") or "").strip()
        chat_id = str(cq.get("message", {}).get("chat", {}).get("id", ""))
        if not data or not chat_id or not data.startswith("/"):
            return False
        return dispatch_update({"message": {"text": data, "chat": {"id": chat_id}}})

    msg = update.get("message", {})
    text = (msg.get("text") or "").strip()
    chat_id = str(msg.get("chat", {}).get("id", ""))

    if not text or not chat_id or not text.startswith("/"):
        return False

    cmd, args = _parse_command(text)
    # Fail closed: if TELEGRAM_CHAT_ID is not configured, NOBODY is owner.
    # (Previously everyone was owner in that case — an unsafe default for a
    # public bot where a missing env var would expose portfolio commands.)
    is_owner = bool(TG_CHAT_ID) and (chat_id == TG_CHAT_ID)

    handler = COMMANDS.get(cmd)
    if not handler:
        safe_cmd = html_module.escape(cmd)
        send_message(
            f"❓ Unknown command: {safe_cmd}\nType /help for available commands",
            chat_id,
        )
        return False

    if cmd in OWNER_COMMANDS and not is_owner:
        print(f"[bot] Owner-only command '{cmd}' from unauthorized chat: {chat_id}")
        send_message("🔒 ဒီ command က bot owner အတွက်သာ ဖြစ်ပါတယ်", chat_id)
        return False

    print(f"[bot] Command: {cmd} args='{args}' chat={chat_id}")
    try:
        handler(chat_id, args)
    except Exception as e:
        print(f"[bot] Command error: {e}")
        send_message(f"⚠️ Error: {html_module.escape(str(e))}", chat_id)
    return True
