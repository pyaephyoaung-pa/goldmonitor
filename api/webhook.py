"""
Vercel Serverless Function â Telegram Webhook Handler
Receives POST from Telegram, processes commands, replies instantly.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler

# storage.py and predictor.py are in the same directory (api/)

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


def send_message(text: str, chat_id: str = ""):
    """Send a Telegram message."""
    cid = chat_id or TG_CHAT_ID
    if not TG_BOT_TOKEN or not cid:
        print(f"[bot] No credentials. Message:\n{text}")
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            json={"chat_id": cid, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        resp = r.json()
        if resp.get("ok"):
            print(f"[bot] Sent message to {cid}: OK (msg_id={resp['result']['message_id']})")
        else:
            print(f"[bot] Telegram error: {resp.get('description', 'unknown')} (code={resp.get('error_code')})")
            if resp.get("error_code") == 400:
                r2 = requests.post(
                    f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
                    json={"chat_id": cid, "text": text},
                    timeout=10,
                )
                resp2 = r2.json()
                if resp2.get("ok"):
                    print(f"[bot] Retry without HTML: OK")
                else:
                    print(f"[bot] Retry also failed: {resp2.get('description')}")
    except Exception as e:
        print(f"[bot] Send error: {e}")


def get_updates(offset: int = 0) -> list:
    """Fetch new Telegram messages."""
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


# ââ Price Fetch (shared with gold_monitor) ââââââââââââââââââââââ

def fetch_gold_price() -> tuple:
    """Fetch current gold price. Returns (thb_gram, usd_oz, thb_rate)."""
    # Primary: metals.live
    try:
        r = requests.get("https://api.metals.live/v1/spot/gold", timeout=10)
        r.raise_for_status()
        usd_oz = float(r.json()[0]["gold"])
    except Exception:
        # Fallback: Yahoo Finance
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            r = requests.get(
                "https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=1m&range=1d",
                headers=headers, timeout=10,
            )
            usd_oz = r.json()["chart"]["result"][0]["meta"]["regularMarketPrice"]
        except Exception as e:
            print(f"[bot] Price fetch failed: {e}")
            return None, None, None

    try:
        r2 = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10)
        r2.raise_for_status()
        thb_rate = r2.json()["rates"]["THB"]
    except Exception as e:
        print(f"[bot] FX rate failed: {e}")
        return None, None, None

    thb_gram = round((usd_oz * thb_rate) / 31.1035, 2)
    return thb_gram, round(usd_oz, 2), round(thb_rate, 2)


def fmt(n):
    return f"à¸¿{n:,.0f}"


# ââ Command Handlers ââââââââââââââââââââââââââââââââââââââââââââ

def cmd_price(chat_id: str):
    """Show current price with quick technical analysis."""
    thb_gram, usd_oz, thb_rate = fetch_gold_price()
    if thb_gram is None:
        send_message("â ï¸ áá±á¸áá¾á¯ááºá¸ áá°áááá« â API error", chat_id)
        return

    history = storage.get_price_history()
    trend = predictor.get_trend_summary(history) if history else {}

    lines = [
        f"ð° <b>áá½á¾á±áá±á¸ á¡áá¯áááºáá¾á­</b>",
        f"âââââââââââââââ",
        f"ð¹ð­ THB : {fmt(thb_gram)}/gram",
        f"ð USD : ${usd_oz}/oz",
        f"ð± Rate: 1 USD = {thb_rate} THB",
    ]

    if trend.get("change_1h") is not None:
        lines.append(f"\nð <b>Changes:</b>")
        for key, label in [("change_1h", "1h"), ("change_4h", "4h"),
                           ("change_24h", "24h"), ("change_7d", "7d")]:
            if key in trend:
                arrow = "ð" if trend[key] > 0 else "ð" if trend[key] < 0 else "â¡ï¸"
                lines.append(f"  {arrow} {label}: {trend[key]:+.3f}%")

    # Quick TA
    if len(history) >= 14:
        ta = predictor.analyze(history)
        if ta.get("overall_signal"):
            lines.append(f"\nð¯ Signal: <b>{ta['overall_signal']}</b>")
        if ta.get("rsi"):
            lines.append(f"ð RSI: {ta['rsi']}")

    send_message("\n".join(lines), chat_id)


def cmd_predict(chat_id: str):
    """Show price predictions for 4h/12h/24h."""
    history = storage.get_price_history()
    if len(history) < 15:
        send_message(
            f"ð Data points: {len(history)}/100\n"
            f"TA requires 15+, ML requires 100+.\n"
            f"Keep running â data accumulates every hour!",
            chat_id,
        )
        return

    model_data = storage.load_model_data()
    prediction = predictor.predict(history, model_data)
    msg = predictor.format_prediction_message(prediction)
    send_message(msg, chat_id)


def cmd_bought(chat_id: str, args: str):
    """Log a gold purchase. Usage: /bought <amount_in_THB>"""
    try:
        amount = float(args.strip())
    except (ValueError, AttributeError):
        send_message(
            "ð Usage: <code>/bought 5000</code>\n"
            "5000 = áááºáá°ááá·áº áá½á±ááá¬á (THB)",
            chat_id,
        )
        return

    if amount <= 0:
        send_message("â ï¸ ááá¬á 0 áááºáá¼á®á¸ááá«áááº", chat_id)
        return

    thb_gram, _, _ = fetch_gold_price()
    if thb_gram is None:
        send_message("â ï¸ áá±á¸áá¾á¯ááºá¸ áá°áá â áááºáá¼á­á¯á¸áá¬á¸áá«", chat_id)
        return

    entry = storage.log_buy(amount, thb_gram)
    send_message(
        f"â <b>áááºáá°áá¾á¯ áá¾ááºáááºá¸áááºáá¼á®á¸!</b>\n"
        f"âââââââââââââââ\n"
        f"ðµ ááá¬á: {fmt(amount)}\n"
        f"ð° áá±á¸áá¾á¯ááºá¸: {fmt(thb_gram)}/gram\n"
        f"âï¸ áá½á¾á±: {entry['grams']:.4f} grams\n"
        f"ð {datetime.now(BANGKOK_TZ).strftime('%d %b %Y %H:%M')}",
        chat_id,
    )


def cmd_portfolio(chat_id: str):
    """Show portfolio summary with P&L."""
    thb_gram, _, _ = fetch_gold_price()
    if thb_gram is None:
        send_message("â ï¸ áá±á¸áá¾á¯ááºá¸ áá°áááá«", chat_id)
        return

    pnl = storage.get_portfolio_pnl(thb_gram)
    if pnl["num_buys"] == 0:
        send_message(
            "ð áááºáá°áá¾á¯ áá¾ááºáááºá¸ ááá¾á­áá±á¸áá«\n"
            "Use: <code>/bought 5000</code> to log a purchase",
            chat_id,
        )
        return

    profit_emoji = "ð¢" if pnl["pnl_thb"] >= 0 else "ð´"
    lines = [
        f"ð <b>áá½á¾á± Portfolio</b>",
        f"âââââââââââââââ",
        f"ð¦ Total buys: {pnl['num_buys']}",
        f"ðµ Invested: {fmt(pnl['total_invested'])}",
        f"âï¸ Total gold: {pnl['total_grams']:.4f} grams",
        f"ð Avg cost: {fmt(pnl['avg_cost'])}/gram",
        f"ð° Current price: {fmt(pnl['current_price'])}/gram",
        f"âââââââââââââââ",
        f"ð Current value: {fmt(pnl['current_value'])}",
        f"{profit_emoji} P&L: {fmt(pnl['pnl_thb'])} ({pnl['pnl_pct']:+.2f}%)",
    ]

    # Recent buys
    if pnl["buys"]:
        lines.append(f"\nð <b>Recent buys:</b>")
        for b in pnl["buys"][-5:]:
            ts = b["ts"][:10]
            lines.append(f"  â¢ {ts}: {fmt(b['amount_thb'])} @ {fmt(b['price_per_gram'])}/g")

    send_message("\n".join(lines), chat_id)


def cmd_history(chat_id: str, args: str):
    """Show price history summary."""
    try:
        days = int(args.strip()) if args.strip() else 7
    except ValueError:
        days = 7
    days = min(days, 30)

    history = storage.get_price_history()
    if len(history) < 2:
        send_message("ð Data collecting â not enough history yet", chat_id)
        return

    # Group by date
    daily = {}
    for h in history:
        date = h["ts"][:10]
        if date not in daily:
            daily[date] = {"prices": [], "usd": []}
        daily[date]["prices"].append(h["thb_gram"])
        daily[date]["usd"].append(h.get("usd_oz", 0))

    dates = sorted(daily.keys())[-days:]
    lines = [f"ð <b>áá½á¾á±áá±á¸ {len(dates)}-Day History</b>", "âââââââââââââââ"]

    for date in dates:
        d = daily[date]
        p = d["prices"]
        high = max(p)
        low = min(p)
        close = p[-1]
        opn = p[0]
        change = ((close - opn) / opn) * 100
        arrow = "ð" if change > 0 else "ð" if change < 0 else "â¡ï¸"
        lines.append(
            f"{arrow} {date}: {fmt(close)} "
            f"(H:{fmt(high)} L:{fmt(low)} {change:+.2f}%)"
        )

    send_message("\n".join(lines), chat_id)


def cmd_setthreshold(chat_id: str, args: str):
    """Change alert threshold."""
    try:
        val = float(args.strip())
    except (ValueError, AttributeError):
        send_message("Usage: <code>/setthreshold 0.5</code>", chat_id)
        return

    if val <= 0 or val > 10:
        send_message("â ï¸ 0.1 â 10 áá¼á¬á¸ áá¼ááºááá«áááº", chat_id)
        return

    bot_state = storage.load_bot_state()
    bot_state["drop_threshold"] = val
    storage.save_bot_state(bot_state)
    send_message(
        f"â Alert threshold â <b>{val}%</b>\n"
        f"ð¡ Buy alert: â¥{val}% drop\n"
        f"ð´ Strong alert: â¥{val * 1.5}% drop",
        chat_id,
    )


def cmd_help(chat_id: str):
    """Show available commands."""
    send_message(
        "ð¤ <b>Gold Monitor Commands</b>\n"
        "âââââââââââââââ\n"
        "ð° /price â áááºáá¾á­ áá½á¾á±áá±á¸\n"
        "ð® /predict â 4h/12h/24h ááá·áºáá¾ááºá¸áá»ááº\n"
        "ð /bought &lt;THB&gt; â áááºáá°áá¾á¯ áá¾ááºáá«\n"
        "ð /portfolio â Portfolio P&L\n"
        "ð /history [N] â N-day áá±á¸ááá­á¯ááºá¸\n"
        "âï¸ /setthreshold N â Alert % áá¼á±á¬ááºá¸áá«\n"
        "â /help â á¤ menu\n"
        "âââââââââââââââ\n"
        "â¹ï¸ Instant replies via webhook",
        chat_id,
    )


# ââ Main: Poll and Dispatch âââââââââââââââââââââââââââââââââââââ

COMMANDS = {
    "/price": lambda cid, _: cmd_price(cid),
    "/predict": lambda cid, _: cmd_predict(cid),
    "/bought": cmd_bought,
    "/portfolio": lambda cid, _: cmd_portfolio(cid),
    "/history": cmd_history,
    "/setthreshold": cmd_setthreshold,
    "/help": lambda cid, _: cmd_help(cid),
    "/start": lambda cid, _: cmd_help(cid),
}

# ââ Vercel Handler âââââââââââââââââââââââââââââââââââââââââââââ

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
                send_message(f"\u26a0\ufe0f Error: {html_module.escape(str(e))}", chat_id)
        else:
            safe_cmd = html_module.escape(cmd)
            send_message(
                f"\u2753 Unknown command: {safe_cmd}\nType /help for available commands",
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
