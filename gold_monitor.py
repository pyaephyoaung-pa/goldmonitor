"""
YLG ရွှေဈေး Monitor — Telegram Bot ဖြင့် သတိပေး
GitHub Actions မှ တစ်နာရီတစ်ကြိမ် auto run သည်
"""

import requests
import json
import os
from datetime import datetime
import pytz

# ── Config ──────────────────────────────────────────────────────
BANGKOK_TZ     = pytz.timezone("Asia/Bangkok")
TG_BOT_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID     = os.environ.get("TELEGRAM_CHAT_ID", "")
DROP_THRESHOLD = float(os.environ.get("DROP_THRESHOLD", "0.5"))
STATE_FILE     = "gold_state.json"


# ── Gold Price Fetch ─────────────────────────────────────────────
def get_gold_thb():
    try:
        r = requests.get("https://api.metals.live/v1/spot/gold", timeout=10)
        r.raise_for_status()
        usd_oz = float(r.json()[0]["gold"])
    except Exception:
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            r = requests.get(
                "https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=1m&range=1d",
                headers=headers, timeout=10
            )
            usd_oz = r.json()["chart"]["result"][0]["meta"]["regularMarketPrice"]
        except Exception as e:
            print(f"[ERROR] Gold price fetch failed: {e}")
            return None, None

    try:
        r2 = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10)
        r2.raise_for_status()
        thb_rate = r2.json()["rates"]["THB"]
    except Exception as e:
        print(f"[ERROR] FX rate fetch failed: {e}")
        return None, None

    thb_gram = round((usd_oz * thb_rate) / 31.1035, 2)
    return thb_gram, round(usd_oz, 2)


# ── Telegram Notify ──────────────────────────────────────────────
def notify(msg: str):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("[WARN] Telegram credentials not set")
        print(msg)
        return
    r = requests.post(
        f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
        json={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML"},
        timeout=10,
    )
    print(f"[Telegram] status={r.status_code}")


# ── State ────────────────────────────────────────────────────────
def load_state() -> dict:
    today = datetime.now(BANGKOK_TZ).strftime("%Y-%m-%d")
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            s = json.load(f)
        if s.get("date") == today:
            return s
    return {
        "date": today, "open_price": None, "day_low": None,
        "day_high": None, "notified_buy": False,
        "notified_strong": False, "evening_sent": False,
    }

def save_state(s: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(s, f, indent=2)

def fmt(n): return f"฿{n:,.0f}"
def drop_pct(open_p, cur): return ((open_p - cur) / open_p) * 100


# ── Main ─────────────────────────────────────────────────────────
def main():
    now  = datetime.now(BANGKOK_TZ)
    hour = now.hour
    time_str = now.strftime("%d %b %Y %H:%M")

    print(f"[{time_str}] Checking gold price...")
    thb_gram, usd_oz = get_gold_thb()
    if thb_gram is None:
        notify("⚠️ <b>YLG Monitor</b>\nAPI error — ဈေးနှုန်း ယူမရပါ")
        return

    print(f"  Gold: {fmt(thb_gram)}/g  (${usd_oz}/oz)")
    state = load_state()

    if state["open_price"] is None:
        state.update({"open_price": thb_gram, "day_low": thb_gram, "day_high": thb_gram})
        save_state(state)
        notify(
            f"🌅 <b>ရွှေဈေး မနက်ခင်း</b>\n📅 {time_str} (BKK)\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💰 Open ဈေး : {fmt(thb_gram)}/g\n"
            f"🌐 Spot     : ${usd_oz}/oz\n"
            f"⚙️ Alert at  : &gt;{DROP_THRESHOLD}% drop\n"
            f"━━━━━━━━━━━━━━━\n✅ Monitoring စပြီ!"
        )
        return

    state["day_low"]  = min(state["day_low"],  thb_gram)
    state["day_high"] = max(state["day_high"], thb_gram)
    d = drop_pct(state["open_price"], thb_gram)
    print(f"  Drop from open: {d:+.2f}%")

    if d >= DROP_THRESHOLD and not state["notified_buy"]:
        notify(
            f"🟡 <b>ရွှေဝယ်သင့်တဲ့ အချိန်!</b>\n⏰ {time_str}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💰 လက်ရှိ  : {fmt(thb_gram)}/g\n"
            f"📈 Open    : {fmt(state['open_price'])}/g\n"
            f"📉 ကျဆင်းမှု : {d:.2f}%\n"
            f"⬇️ ယနေ့ Low: {fmt(state['day_low'])}/g\n"
            f"━━━━━━━━━━━━━━━\n👉 YLG Get Gold ဖွင့်ဝယ်ပါ!"
        )
        state["notified_buy"] = True

    if d >= DROP_THRESHOLD * 1.5 and not state["notified_strong"]:
        notify(
            f"🔴 <b>ရွှေဈေး ကြီးစွာ ကျဆင်း!</b>\n⏰ {time_str}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💰 လက်ရှိ  : {fmt(thb_gram)}/g\n"
            f"📉 ကျဆင်းမှု : {d:.2f}%\n"
            f"⬇️ ယနေ့ Low: {fmt(state['day_low'])}/g\n"
            f"━━━━━━━━━━━━━━━\n🔥 DCA ထပ်ဝယ်ရန် စဉ်းစားပါ!"
        )
        state["notified_strong"] = True

    if d < DROP_THRESHOLD * 0.3:
        state["notified_buy"] = False
        state["notified_strong"] = False

    if 20 <= hour <= 21 and not state["evening_sent"]:
        change = d * -1
        arrow = "📉" if change > 0 else "📈"
        notify(
            f"🌙 <b>ညနေ ရွှေဈေး အနှစ်ချုပ်</b>\n📅 {time_str}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💰 ယခု      : {fmt(thb_gram)}/g\n"
            f"📊 Open     : {fmt(state['open_price'])}/g\n"
            f"{arrow} ယနေ့ change : {change:+.2f}%\n"
            f"⬆️ Day High  : {fmt(state['day_high'])}/g\n"
            f"⬇️ Day Low   : {fmt(state['day_low'])}/g\n"
            f"━━━━━━━━━━━━━━━\n🌐 Spot: ${usd_oz}/oz"
        )
        state["evening_sent"] = True

    save_state(state)
    print("  Done.")

if __name__ == "__main__":
    main()
