"""
Vercel Serverless Function — Telegram Webhook Handler
Receives POST from Telegram, processes commands, replies instantly.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler

# storage.py and predictor.py are copied into api/ for Vercel bundling

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
    try:
        r = requests.get("https://api.metals.live/v1/spot/gold", timeout=10)
        r.raise_for_status()
        usd_oz = float(r.json()[0]["gold"])
    except Exception:
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            r = requests.get(
                "https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=1m&range=1d",
                headers=headers, timeout=10,
            )
            usd_oz = r.json()["chart"]["result"][0]["meta"]["regularMarketPrice"]
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


# ── Command Handlers ───────────────────────────────────────────

def cmd_price(chat_id: str):
    thb_gram, usd_oz, thb_rate = fetch_gold_price()
    if thb_gram is None:
        send_message("⚠️ ဈေးနှုန်း ယူမရပါ — API error", chat_id)
        return

    history = storage.get_price_history()
    trend = predictor.get_trend_summary(history) if history else {}

    lines = [
        f"💰 <b>ရွှေဈေး အခုလက်ရှိ</b>",
        f"━━━━━━━━━━━━━━━",
        f"🇹🇭 THB : {fmt(thb_gram)}/gram",
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


def cmd_portfolio(chat_id: str):
    thb_gram, _, _ = fetch_gold_price()
    if thb_gram is None:
        send_message("⚠️ ဈေးနှုန်း ယူမရပါ", chat_id)
        return

    pnl = storage.get_portfolio_pnl(thb_gram)
    if pnl["num_buys"] == 0:
        send_message(
            "📂 ဝယ်ယူမှု မှတ်တမ်း မရှိသေးပါ\n"
            "Use: <code>/bought 5000</code> to log a purchase",
            chat_id,
        )
        return

    profit_emoji = "🟢" if pnl["pnl_thb"] >= 0 else "🔴"
    lines = [
        f"📊 <b>ရွှေ Portfolio</b>",
        f"━━━━━━━━━━━━━━━",
        f"📦 Total buys: {pnl['num_buys']}",
        f"💵 Invested: {fmt(pnl['total_invested'])}",
        f"⚖️ Total gold: {pnl['total_grams']:.4f} grams",
        f"📈 Avg cost: {fmt(pnl['avg_cost'])}/gram",
        f"💰 Current price: {fmt(pnl['current_price'])}/gram",
        f"━━━━━━━━━━━━━━━",
        f"💎 Current value: {fmt(pnl['current_value'])}",
        f"{profit_emoji} P&L: {fmt(pnl['pnl_thb'])} ({pnl['pnl_pct']:+.2f}%)",
    ]

    if pnl["buys"]:
        lines.append(f"\n📝 <b>Recent buys:</b>")
        for b in pnl["buys"][-5:]:
            ts = b["ts"][:10]
            lines.append(f"  • {ts}: {fmt(b['amount_thb'])} @ {fmt(b['price_per_gram'])}/g")

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
            send_headers()
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
