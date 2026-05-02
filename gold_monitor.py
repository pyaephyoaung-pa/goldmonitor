"""
YLG ရွှေဈေး Monitor v2 — Enhanced Edition
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Features:
  • Multi-timeframe buy signals (intraday + weekly + monthly)
  • Technical analysis (RSI, SMA, MACD, Bollinger)
  • ML price prediction (4h / 12h / 24h)
  • Portfolio tracking with P&L
  • Rich evening summary with trends
  • GitHub Gist persistent storage
  • Retry logic for API calls

GitHub Actions: hourly auto-run
"""

import requests
import os
import time
from datetime import datetime
import pytz

import storage
import predictor

# ── Config ──────────────────────────────────────────────────────
BANGKOK_TZ = pytz.timezone("Asia/Bangkok")
TG_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
DROP_THRESHOLD = float(os.environ.get("DROP_THRESHOLD", "0.5"))
RISE_THRESHOLD = float(os.environ.get("RISE_THRESHOLD", "0.5"))

# Try to load thresholds from bot state (user-configurable via /setthreshold, /setrisethreshold)
try:
    _bot_state = storage.load_bot_state()
    if "drop_threshold" in _bot_state:
        DROP_THRESHOLD = _bot_state["drop_threshold"]
    if "rise_threshold" in _bot_state:
        RISE_THRESHOLD = _bot_state["rise_threshold"]
except Exception:
    pass


# ── Gold Price Fetch (with retry) ───────────────────────────────

def get_gold_price(retries: int = 2) -> tuple:
    """Fetch gold price with retry logic.
    Returns (thb_gram, usd_oz, thb_rate) or (None, None, None).
    """
    for attempt in range(retries + 1):
        usd_oz = None
        thb_rate = None

        # Gold spot price — primary API
        try:
            r = requests.get("https://api.metals.live/v1/spot/gold", timeout=10)
            r.raise_for_status()
            usd_oz = float(r.json()[0]["gold"])
        except Exception:
            # Fallback: Yahoo Finance
            try:
                headers = {"User-Agent": "Mozilla/5.0"}
                r = requests.get(
                    "https://query1.finance.yahoo.com/v8/finance/chart/GC=F"
                    "?interval=1m&range=1d",
                    headers=headers, timeout=10,
                )
                usd_oz = r.json()["chart"]["result"][0]["meta"]["regularMarketPrice"]
            except Exception as e:
                if attempt < retries:
                    print(f"[retry {attempt+1}] Gold price failed: {e}")
                    time.sleep(10)
                    continue
                print(f"[ERROR] Gold price fetch failed after retries: {e}")
                return None, None, None

        # USD/THB exchange rate
        try:
            r2 = requests.get(
                "https://api.exchangerate-api.com/v4/latest/USD", timeout=10
            )
            r2.raise_for_status()
            thb_rate = r2.json()["rates"]["THB"]
        except Exception as e:
            if attempt < retries:
                print(f"[retry {attempt+1}] FX rate failed: {e}")
                time.sleep(10)
                continue
            print(f"[ERROR] FX rate fetch failed after retries: {e}")
            return None, None, None

        thb_gram = round((usd_oz * thb_rate) / 31.1035, 2)
        return thb_gram, round(usd_oz, 2), round(thb_rate, 2)

    return None, None, None


# ── Telegram Notify ─────────────────────────────────────────────

def notify(msg: str):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("[WARN] Telegram credentials not set")
        print(msg)
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
        print(f"[Telegram] status={r.status_code}")
    except Exception as e:
        print(f"[Telegram] error: {e}")


# ── Helpers ─────────────────────────────────────────────────────

def fmt(n):
    return f"฿{n:,.0f}"


def drop_pct(open_p, cur):
    return ((open_p - cur) / open_p) * 100


def rise_pct(open_p, cur):
    return ((cur - open_p) / open_p) * 100


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


# ── Main Monitor ────────────────────────────────────────────────

def main():
    now = datetime.now(BANGKOK_TZ)
    hour = now.hour
    time_str = now.strftime("%d %b %Y %H:%M")

    print(f"[{time_str}] Gold Monitor v2 checking...")

    # ── Fetch Price ─────────────────────────────────────────────
    thb_gram, usd_oz, thb_rate = get_gold_price()
    if thb_gram is None:
        notify("⚠️ <b>YLG Monitor</b>\nAPI error — ဈေးနှုန်း ယူမရပါ")
        return

    print(f"  Gold: {fmt(thb_gram)}/g (${usd_oz}/oz) [THB rate: {thb_rate}]")

    # ── Store Price History ─────────────────────────────────────
    history = storage.append_price(thb_gram, usd_oz, thb_rate)
    print(f"  History: {len(history)} data points stored")

    # ── Day State ───────────────────────────────────────────────
    state = storage.load_day_state()

    # First run of the day — morning message
    if state["open_price"] is None:
        state.update({
            "open_price": thb_gram,
            "day_low": thb_gram,
            "day_high": thb_gram,
        })
        storage.save_day_state(state)

        # Include trend if we have history
        trend_lines = ""
        if len(history) >= 24:
            trend = predictor.get_trend_summary(history)
            parts = []
            if "change_24h" in trend:
                parts.append(f"24h: {trend['change_24h']:+.3f}%")
            if "change_7d" in trend:
                parts.append(f"7d: {trend['change_7d']:+.3f}%")
            if parts:
                trend_lines = f"\n📊 Trend: {' | '.join(parts)}"

        # Quick TA signal
        ta_line = ""
        if len(history) >= 14:
            ta = predictor.analyze(history)
            if ta.get("overall_signal"):
                ta_line = f"\n🎯 Signal: {ta['overall_signal']}"

        gb = gold_breakdown(thb_gram)
        notify(
            f"🌅 <b>ရွှေဈေး မနက်ခင်း</b>\n"
            f"📅 {time_str} (BKK)\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🥇 <b>99.99% (Pure)</b>\n"
            f"  ဘတ်သား: {fmt(gb['baht_9999'])}\n"
            f"  1g: {fmt(gb['gram_9999'])}\n"
            f"🥈 <b>96.50%</b>\n"
            f"  ဘတ်သား: {fmt(gb['baht_9650'])}\n"
            f"  1g: {fmt(gb['gram_9650'])}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🌐 Spot     : ${usd_oz}/oz\n"
            f"💱 Rate     : 1 USD = {thb_rate} THB\n"
            f"⚙️ Alert    : ↓{DROP_THRESHOLD}% drop | ↑{RISE_THRESHOLD}% rise"
            f"{trend_lines}{ta_line}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"✅ Monitoring စပြီ!"
        )
        return

    # ── Update Day Stats ────────────────────────────────────────
    state["day_low"] = min(state["day_low"], thb_gram)
    state["day_high"] = max(state["day_high"], thb_gram)
    d = drop_pct(state["open_price"], thb_gram)
    print(f"  Drop from open: {d:+.2f}%")

    # ── Multi-timeframe Analysis ────────────────────────────────
    ta = predictor.analyze(history) if len(history) >= 14 else {}
    trend = predictor.get_trend_summary(history) if len(history) >= 2 else {}

    # ── Buy Alert (intraday drop) ───────────────────────────────
    if d >= DROP_THRESHOLD and not state["notified_buy"]:
        ta_signal = f"\n🎯 TA Signal: {ta['overall_signal']}" if ta.get("overall_signal") else ""
        rsi_line = f"\n📊 RSI: {ta['rsi']}" if ta.get("rsi") else ""

        notify(
            f"🟡 <b>ရွှေဝယ်သင့်တဲ့ အချိန်!</b>\n"
            f"⏰ {time_str}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💰 လက်ရှိ  : {fmt(thb_gram)}/g\n"
            f"📈 Open    : {fmt(state['open_price'])}/g\n"
            f"📉 ကျဆင်းမှု : {d:.2f}%\n"
            f"⬇️ ယနေ့ Low: {fmt(state['day_low'])}/g"
            f"{ta_signal}{rsi_line}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"👉 YLG Get Gold ဖြင့်ဝယ်ပါ!\n"
            f"📝 ဝယ်ပြီးရင် /bought &lt;THB&gt; ပို့ပါ"
        )
        state["notified_buy"] = True

    # ── Strong Drop Alert ───────────────────────────────────────
    if d >= DROP_THRESHOLD * 1.5 and not state["notified_strong"]:
        notify(
            f"🔴 <b>ရွှေဈေး ကြီးစွာ ကျဆင်း!</b>\n"
            f"⏰ {time_str}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💰 လက်ရှိ  : {fmt(thb_gram)}/g\n"
            f"📉 ကျဆင်းမှု : {d:.2f}%\n"
            f"⬇️ ယနေ့ Low: {fmt(state['day_low'])}/g\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🔥 DCA ထပ်ဝယ်ရန် စဉ်းစားပါ!\n"
            f"📝 /bought &lt;THB&gt; ဖြင့် မှတ်ပါ"
        )
        state["notified_strong"] = True

    # Reset drop notifications if price recovers
    if d < DROP_THRESHOLD * 0.3:
        state["notified_buy"] = False
        state["notified_strong"] = False

    # ── Rise Alert (intraday rise) ─────────────────────────────
    r = rise_pct(state["open_price"], thb_gram)
    if r >= RISE_THRESHOLD and not state.get("notified_rise"):
        ta_signal = f"\n🎯 TA Signal: {ta['overall_signal']}" if ta.get("overall_signal") else ""
        rsi_line = f"\n📊 RSI: {ta['rsi']}" if ta.get("rsi") else ""

        notify(
            f"🟢 <b>ရွှေဈေး တက်နေပါတယ်!</b>\n"
            f"⏰ {time_str}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💰 လက်ရှိ  : {fmt(thb_gram)}/g\n"
            f"📈 Open    : {fmt(state['open_price'])}/g\n"
            f"🚀 တက်မှု   : +{r:.2f}%\n"
            f"⬆️ ယနေ့ High: {fmt(state['day_high'])}/g"
            f"{ta_signal}{rsi_line}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💎 Portfolio တန်ဖိုး တက်နေပါပြီ!"
        )
        state["notified_rise"] = True

    # ── Strong Rise Alert ──────────────────────────────────────
    if r >= RISE_THRESHOLD * 1.5 and not state.get("notified_strong_rise"):
        notify(
            f"🟣 <b>ရွှေဈေး ကြီးစွာ တက်!</b>\n"
            f"⏰ {time_str}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💰 လက်ရှိ  : {fmt(thb_gram)}/g\n"
            f"🚀 တက်မှု   : +{r:.2f}%\n"
            f"⬆️ ယနေ့ High: {fmt(state['day_high'])}/g\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📊 Profit ယူရန် စဉ်းစားပါ!"
        )
        state["notified_strong_rise"] = True

    # Reset rise notifications if price drops back
    if r < RISE_THRESHOLD * 0.3:
        state["notified_rise"] = False
        state["notified_strong_rise"] = False

    # ── Evening Summary (8–9pm BKK) ────────────────────────────
    if 20 <= hour <= 21 and not state["evening_sent"]:
        change = -d
        arrow = "📈" if change > 0 else "📉"

        # Portfolio P&L
        portfolio_lines = ""
        pnl = storage.get_portfolio_pnl(thb_gram)
        if pnl["num_buys"] > 0:
            p_emoji = "🟢" if pnl["pnl_thb"] >= 0 else "🔴"
            portfolio_lines = (
                f"\n\n💼 <b>Portfolio:</b>\n"
                f"  ⚖️ {pnl['total_grams']:.4f}g ({pnl['num_buys']} buys)\n"
                f"  {p_emoji} P&L: {fmt(pnl['pnl_thb'])} ({pnl['pnl_pct']:+.2f}%)"
            )

        # Multi-timeframe trends
        trend_lines = ""
        if trend:
            parts = []
            for key, label in [("change_4h", "4h"), ("change_24h", "24h"), ("change_7d", "7d")]:
                if key in trend:
                    parts.append(f"{label}: {trend[key]:+.3f}%")
            if parts:
                trend_lines = f"\n📊 Trends: {' | '.join(parts)}"

        # Prediction outlook
        predict_line = ""
        if len(history) >= 15:
            model_data = storage.load_model_data()
            pred = predictor.predict(history, model_data)
            outlook = pred.get("combined_outlook") or pred.get("ta_outlook", "")
            if outlook:
                predict_line = f"\n🔮 Tomorrow: {outlook}"

        # Streak info
        streak_line = ""
        if trend.get("streak", 0) >= 3:
            streak_line = (
                f"\n🔥 {trend['streak']}h consecutive "
                f"{'rise' if trend['streak_direction'] == 'up' else 'decline'}"
            )

        notify(
            f"🌙 <b>ညနေ ရွှေဈေး အနှစ်ချုပ်</b>\n"
            f"📅 {time_str}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💰 ယခု      : {fmt(thb_gram)}/g\n"
            f"📊 Open     : {fmt(state['open_price'])}/g\n"
            f"{arrow} ယနေ့ change : {change:+.2f}%\n"
            f"⬆️ Day High  : {fmt(state['day_high'])}/g\n"
            f"⬇️ Day Low   : {fmt(state['day_low'])}/g\n"
            f"🌐 Spot: ${usd_oz}/oz"
            f"{trend_lines}{streak_line}{portfolio_lines}{predict_line}\n"
            f"━━━━━━━━━━━━━━━"
        )
        state["evening_sent"] = True

    storage.save_day_state(state)

    # ── Train ML Model (once per day, after enough data) ────────
    if hour == 3 and len(history) >= 100:
        model_data = storage.load_model_data()
        last_trained = model_data.get("last_trained", "")
        today = now.strftime("%Y-%m-%d")
        if not last_trained or last_trained[:10] != today:
            print("[ML] Training prediction models...")
            new_model = predictor.train_model(history)
            if new_model:
                storage.save_model_data(new_model)
                print("[ML] Models saved to Gist")
            else:
                print("[ML] Training skipped or failed")

    print("  Done.")


if __name__ == "__main__":
    main()
