"""
Vercel Serverless Function — Telegram Webhook Handler
Receives POST from Telegram, processes commands, replies instantly.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler

# Add parent directory to path so storage.py and predictor.py can be imported
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import html as html_module
import re
import requests
import pytz
from datetime import datetime

import storage
import predictor

BANGKOK_TZ = pytz.timezone("Asia/Bangkok")
TG_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "")


# ── Telegram Send ──────────────────────────────────────────────

def send_message(text: str, chat_id: str = ""):
    """Send a Telegram message with HTML fallback."""
    cid = chat_id or TG_CHAT_ID
    if not TG_BOT_TOKEN or not cid:
        print(f"[webhook] No credentials. Message:\n{text}")
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            json={"chat_id": cid, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        resp = r.json()
        if resp.get("ok"):
            print(f"[webhook] Sent OK (msg_id={resp['result']['message_id']})")
        else:
            print(f"[webhook] Telegram error: {resp.get('description')}")
            if resp.get("error_code") == 400:
                r2 = requests.post(
                    f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
                    json={"chat_id": cid, "text": text},
                    timeout=10,
                )
                resp2 = r2.json()
                print(f"[webhook] Retry {'OK' if resp2.get('ok') else 'failed'}")
    except Exception as e:
        print(f"[webhook] Send error: {e}")


# ── Gold Price ─────────────────────────────────────────────────

def fetch_gold_price() -> tuple:
    """Fetch current gold price. Returns (thb_gram, usd_oz, thb_rate)."""
    # Primary: Twelve Data
    try:
        r = requests.get(
            "https://api.twelvedata.com/price",
            params={"symbol": "XAU/USD", "apikey": TWELVE_DATA_API_KEY},
            timeout=10,
        )
        r.raise_for_status()
        usd_oz = float(r.json()["price"])
    except Exception:
        # Fallback: metals.live
        try:
            r = requests.get("https://api.metals.live/v1/spot/gold", timeout=10)
            r.raise_for_status()
            usd_oz = float(r.json()[0]["gold"])
        except Exception as e:
            print(f"[webhook] Price fetch failed: {e}")
            return None, None, None

    try:
        r2 = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10)
        r2.raise_for_status()
        thb_rate = r2.json()["rates"]["THB"]
    except Exception as e:
        print(f"[webhook] FX rate failed: {e}")
        return None, None, None

    thb_gram = round((usd_oz * thb_rate) / 31.1035, 2)
    return thb_gram, round(usd_oz, 2), round(thb_rate, 2)


def fmt(n):
    return f"฿{n:,.0f}"


BAHT_WEIGHT_GRAMS = 15.244  # 1 บาททอง = 15.244 grams


def gold_breakdown(thb_gram_9999):
    """Calculate gold prices for 99.99% and 96.50% purity."""
    baht_9999 = round(thb_gram_9999 * BAHT_WEIGHT_GRAMS, 2)
    gram_9650 = round(thb_gram_9999 * (96.50 / 99.99), 2)
    baht_9650 = round(gram_9650 * BAHT_WEIGHT_GRAMS, 2)
    return {
        "gram_9999": thb_gram_9999,
        "baht_9999": baht_9999,
        "gram_9650": gram_9650,
        "baht_9650": baht_9650,
    }


# ── Command Handlers ───────────────────────────────────────────

def cmd_price(chat_id: str):
    thb_gram, usd_oz, thb_rate = fetch_gold_price()
    if thb_gram is None:
        send_message("⚠️ ဈေးနှုန်း ယူမရပါ — API error", chat_id)
        return

    history = storage.get_price_history()
    trend = predictor.get_trend_summary(history) if history else {}
    gb = gold_breakdown(thb_gram)

    lines = [
        f"💰 <b>ရွှေဈေး အခုလက်ရှိ</b>",
        f"━━━━━━━━━━━━━━━",
        f"🥇 <b>99.99% (Pure)</b>",
        f"  ဘတ်သား: {fmt(gb['baht_9999'])}",
        f"  1g: {fmt(gb['gram_9999'])}",
        f"🥈 <b>96.50%</b>",
        f"  ဘတ်သား: {fmt(gb['baht_9650'])}",
        f"  1g: {fmt(gb['gram_9650'])}",
        f"━━━━━━━━━━━━━━━",
        f"🌐 USD : ${usd_oz}/oz",
        f"💱 Rate: 1 USD = {thb_rate} THB",
    ]

    if trend.get("change_1h") is not None:
        lines.append(f"\n📊 <b>Changes:</b>")
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
    prediction = predictor.predict(history, model_data)
    msg = predictor.format_prediction_message(prediction)
    send_message(msg, chat_id)


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

    thb_gram, _, _ = fetch_gold_price()
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

    thb_gram, _, _ = fetch_gold_price()
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
    thb_gram, _, _ = fetch_gold_price()
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
        f"📊 <b>ရွှေ Portfolio</b>",
        f"━━━━━━━━━━━━━━━",
        f"📦 Buys: {pnl['num_buys']} | Sells: {pnl['num_sells']}",
        f"💵 Invested: {fmt(pnl['total_invested'])}",
        f"⚖️ Holdings: {pnl['total_grams']:.4f} grams",
        f"📈 Avg buy cost: {fmt(pnl['avg_cost'])}/gram",
        f"💰 Current price: {fmt(pnl['current_price'])}/gram",
        f"━━━━━━━━━━━━━━━",
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
        lines.append(f"\n📝 <b>Recent entries:</b>")
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
    days = min(days, 30)

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
        d = daily[date]
        p = d["prices"]
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
    send_message(
        f"✅ Alert threshold → <b>{val}%</b>\n"
        f"🟡 Buy alert: ≥{val}% drop\n"
        f"🔴 Strong alert: ≥{val * 1.5}% drop",
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
        f"🟢 Rise alert: ≥{val}% rise\n"
        f"🟣 Strong alert: ≥{val * 1.5}% rise",
        chat_id,
    )


def cmd_help(chat_id: str):
    send_message(
        "🤖 <b>Gold Monitor Commands</b>\n"
        "━━━━━━━━━━━━━━━\n"
        "💰 /price — လက်ရှိ ရွှေဈေး\n"
        "🔮 /predict — 4h/12h/24h ခန့်မှန်းချက်\n"
        "📝 /bought &lt;THB&gt; — ဝယ်ယူမှု မှတ်ပါ\n"
        "📝 /sold &lt;THB&gt; — ရောင်းချမှု မှတ်ပါ\n"
        "✏️ /edit &lt;#&gt; &lt;THB&gt; — entry ပြင်ဆင်ပါ\n"
        "🗑 /delete &lt;#&gt; — entry ဖျက်ပါ\n"
        "📊 /portfolio — Portfolio P&L\n"
        "📈 /history [N] — N-day ဈေးသမိုင်း\n"
        "⚙️ /setthreshold N — Drop alert % ပြောင်းပါ\n"
        "📈 /setrisethreshold N — Rise alert % ပြောင်းပါ\n"
        "❓ /help — ဤ menu\n"
        "━━━━━━━━━━━━━━━\n"
        "⚡ Instant replies via webhook",
        chat_id,
    )


COMMANDS = {
    "/price": lambda cid, _: cmd_price(cid),
    "/predict": lambda cid, _: cmd_predict(cid),
    "/bought": cmd_bought,
    "/sold": cmd_sold,
    "/edit": cmd_edit,
    "/delete": cmd_delete,
    "/portfolio": lambda cid, _: cmd_portfolio(cid),
    "/history": cmd_history,
    "/setthreshold": cmd_setthreshold,
    "/setrisethreshold": cmd_setrisethreshold,
    "/help": lambda cid, _: cmd_help(cid),
    "/start": lambda cid, _: cmd_help(cid),
}


# ── Vercel Handler ─────────────────────────────────────────────

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            update = json.loads(body)
        except Exception as e:
            print(f"[webhook] Parse error: {e}")
            self.send_response(400)
            self.end_headers()
            return

        # Optional: verify secret token
        if WEBHOOK_SECRET:
            token = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if token != WEBHOOK_SECRET:
                print(f"[webhook] Invalid secret token")
                self.send_response(403)
                self.end_headers()
                return

        # Always respond 200 to Telegram quickly
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

        # Process the message
        msg = update.get("message", {})
        text = msg.get("text", "").strip()
        chat_id = str(msg.get("chat", {}).get("id", ""))

        if not text or not chat_id:
            return

        # Only respond to authorized chat
        if TG_CHAT_ID and chat_id != TG_CHAT_ID:
            print(f"[webhook] Ignoring unauthorized chat: {chat_id}")
            return

        if not text.startswith("/"):
            return

        # Parse command and args
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower().split("@")[0]
        args = parts[1] if len(parts) > 1 else ""

        # Smart prefix matching (e.g. /bought5000)
        cmd_handler = COMMANDS.get(cmd)
        if not cmd_handler:
            m = re.match(r'^(/\w+)', cmd)
            if m:
                base_cmd = m.group(1)
                if base_cmd in COMMANDS:
                    extra = cmd[len(base_cmd):]
                    extra = re.sub(r'[<>]', '', extra).strip()
                    if extra and not args:
                        args = extra
                    cmd = base_cmd
                    cmd_handler = COMMANDS.get(cmd)

        print(f"[webhook] Command: {cmd} args='{args}' chat={chat_id}")

        if cmd_handler:
            try:
                cmd_handler(chat_id, args)
            except Exception as e:
                print(f"[webhook] Command error: {e}")
                send_message(f"⚠️ Error: {html_module.escape(str(e))}", chat_id)
        else:
            safe_cmd = html_module.escape(cmd)
            send_message(
                f"❓ Unknown command: {safe_cmd}\nType /help for available commands",
                chat_id,
            )

    def do_GET(self):
        """Health check endpoint."""
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "status": "ok",
            "service": "Gold Monitor Telegram Webhook",
            "timestamp": datetime.now(BANGKOK_TZ).isoformat(),
        }).encode())

    def log_message(self, format, *args):
        """Suppress default HTTP logging."""
        pass
