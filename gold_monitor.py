"""
YLG ရွှေဈေး Monitor — LINE Notify ဖြင့် သတိပေး
GitHub Actions မှ တစ်နာရီတစ်ကြိမ် auto run သည်
"""

import requests
import json
import os
from datetime import datetime
import pytz

# ── Config ──────────────────────────────────────────────────────
BANGKOK_TZ   = pytz.timezone("Asia/Bangkok")
LINE_TOKEN   = os.environ.get("LINE_NOTIFY_TOKEN", "")
DROP_THRESHOLD = float(os.environ.get("DROP_THRESHOLD", "0.5"))  # % ကျဆင်းမှ notify
STATE_FILE   = "gold_state.json"

# ── Gold Price Fetch ─────────────────────────────────────────────
def get_gold_thb():
    """ရွှေဈေး THB/gram ယူသည် (metals.live + exchangerate-api)"""
    try:
        # Gold spot price USD/oz
        r = requests.get("https://api.metals.live/v1/spot/gold", timeout=10)
        r.raise_for_status()
        usd_oz = float(r.json()[0]["gold"])

        # USD → THB exchange rate
        r2 = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10)
        r2.raise_for_status()
        thb_rate = r2.json()["rates"]["THB"]

        thb_gram = round((usd_oz * thb_rate) / 31.1035, 2)
        return thb_gram, round(usd_oz, 2)

    except Exception as e:
        # Fallback: Yahoo Finance
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            r = requests.get(
                "https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=1m&range=1d",
                headers=headers, timeout=10
            )
            usd_oz = r.json()["chart"]["result"][0]["meta"]["regularMarketPrice"]

            r2 = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10)
            thb_rate = r2.json()["rates"]["THB"]

            thb_gram = round((usd_oz * thb_rate) / 31.1035, 2)
            return thb_gram, round(usd_oz, 2)

        except Exception as e2:
            print(f"[ERROR] Both APIs failed: {e} | {e2}")
            return None, None


# ── LINE Notify ──────────────────────────────────────────────────
def notify(msg: str):
    if not LINE_TOKEN:
        print("[WARN] LINE_NOTIFY_TOKEN not set — printing only")
        print(msg)
        return
    r = requests.post(
        "https://notify-api.line.me/api/notify",
        headers={"Authorization": f"Bearer {LINE_TOKEN}"},
        data={"message": msg},
        timeout=10
    )
    print(f"[LINE] status={r.status_code}")


# ── State ────────────────────────────────────────────────────────
def load_state() -> dict:
    today = datetime.now(BANGKOK_TZ).strftime("%Y-%m-%d")
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            s = json.load(f)
        if s.get("date") == today:
            return s
    # New day — reset
    return {
        "date":          today,
        "open_price":    None,
        "day_low":       None,
        "day_high":      None,
        "notified_buy":  False,
        "evening_sent":  False,
    }

def save_state(s: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(s, f, indent=2)


# ── Format Helpers ───────────────────────────────────────────────
def fmt(n):
    return f"฿{n:,.0f}"

def pct(a, b):
    return ((a - b) / b) * 100


# ── Main Logic ───────────────────────────────────────────────────
def main():
    now = datetime.now(BANGKOK_TZ)
    hour = now.hour
    time_str = now.strftime("%d %b %Y %H:%M")

    print(f"[{time_str}] Checking gold price...")

    thb_gram, usd_oz = get_gold_thb()
    if thb_gram is None:
        notify("\n⚠️ YLG Monitor\nAPI error — ဈေးနှုန်း ယူမရပါ")
        return

    print(f"  Gold: {fmt(thb_gram)}/g  (${usd_oz}/oz)")

    state = load_state()

    # ── First run of the day: set open price ──
    if state["open_price"] is None:
        state["open_price"] = thb_gram
        state["day_low"]    = thb_gram
        state["day_high"]   = thb_gram
        save_state(state)

        msg = (
            f"\n🌅 ရွှေဈေး မနက်ခင်း အစီရင်ခံ\n"
            f"📅 {time_str} (BKK)\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💰 Open ဈေး : {fmt(thb_gram)}/g\n"
            f"🌐 Spot     : ${usd_oz}/oz\n"
            f"⚙️  Alert at : >{DROP_THRESHOLD}% drop\n"
            f"━━━━━━━━━━━━━━━\n"
            f"✅ Monitoring စပြီ!"
        )
        notify(msg)
        return

    # ── Update day stats ──
    state["day_low"]  = min(state["day_low"],  thb_gram)
    state["day_high"] = max(state["day_high"], thb_gram)

    drop_from_open = pct(state["open_price"], thb_gram)   # + = ကျ, - = တက်
    drop_from_high = pct(state["day_high"],   thb_gram)

    print(f"  Open: {fmt(state['open_price'])} | Drop: {drop_from_open:+.2f}%")

    # ── BUY alert: ဈေး threshold% ကျဆင်းရင် ──
    if drop_from_open >= DROP_THRESHOLD and not state["notified_buy"]:
        msg = (
            f"\n🟡 ရွှေဝယ်သင့်တဲ့ အချိန်!\n"
            f"⏰ {time_str}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💰 လက်ရှိ  : {fmt(thb_gram)}/g\n"
            f"📈 Open    : {fmt(state['open_price'])}/g\n"
            f"📉 ကျဆင်းမှု : {drop_from_open:.2f}%\n"
            f"⬇️  ယနေ့ Low: {fmt(state['day_low'])}/g\n"
            f"━━━━━━━━━━━━━━━\n"
            f"👉 YLG Get Gold ဖွင့်ဝယ်ပါ!"
        )
        notify(msg)
        state["notified_buy"] = True

    # Notif reset — ဈေးပြန်တက်ရင် နောက်ကြိမ် alert ပြန်ပေးနိုင်အောင်
    if drop_from_open < DROP_THRESHOLD * 0.3:
        state["notified_buy"] = False

    # ── Strong drop alert (1.5x threshold) ──
    strong = DROP_THRESHOLD * 1.5
    if drop_from_open >= strong and not state.get("notified_strong"):
        msg = (
            f"\n🔴 ရွှေဈေး ကြီးစွာ ကျဆင်း!\n"
            f"⏰ {time_str}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💰 လက်ရှိ  : {fmt(thb_gram)}/g\n"
            f"📉 ကျဆင်းမှု : {drop_from_open:.2f}%\n"
            f"⬇️  ယနေ့ Low: {fmt(state['day_low'])}/g\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🔥 DCA ထပ်ဝယ်ရန် စဉ်းစားပါ!"
        )
        notify(msg)
        state["notified_strong"] = True

    # ── Evening summary (8–9pm Bangkok) ──
    if 20 <= hour <= 21 and not state["evening_sent"]:
        change = pct(state["open_price"], thb_gram) * -1   # + = ကျ
        arrow  = "📉" if change > 0 else "📈"
        msg = (
            f"\n🌙 ညနေ ရွှေဈေး အနှစ်ချုပ်\n"
            f"📅 {time_str}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💰 ယခု     : {fmt(thb_gram)}/g\n"
            f"📊 Open    : {fmt(state['open_price'])}/g\n"
            f"{arrow} ယနေ့ change: {change:+.2f}%\n"
            f"⬆️  Day High : {fmt(state['day_high'])}/g\n"
            f"⬇️  Day Low  : {fmt(state['day_low'])}/g\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🌐 Spot: ${usd_oz}/oz"
        )
        notify(msg)
        state["evening_sent"] = True

    save_state(state)
    print("  Done.")


if __name__ == "__main__":
    main()
