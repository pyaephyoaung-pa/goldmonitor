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
  • Retry logic + multi-source price fallback (see goldapi.py)

GitHub Actions: runs on a cron through the day.
Shared logic (price fetch, formatting, Telegram send) lives in goldapi.py,
gold_format.py and bot_core.py so it is not duplicated here.
"""

import os
from datetime import datetime
import pytz

import storage
import predictor
import goldapi
import bot_core
import signals
from gold_format import fmt, gold_breakdown

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


# ── Telegram Notify ─────────────────────────────────────────────

def notify(msg: str):
    """Send message to owner + all subscribers.

    Uses the shared bot_core.send_message; auto-removes subscribers who have
    blocked the bot (Telegram error_code 403).
    """
    if not TG_BOT_TOKEN:
        print("[WARN] Telegram bot token not set")
        print(msg)
        return

    recipients = []
    if TG_CHAT_ID:
        recipients.append(TG_CHAT_ID)
    for sub_id in storage.get_subscribers():
        if sub_id != TG_CHAT_ID:  # avoid duplicate if owner subscribed
            recipients.append(sub_id)

    for chat_id in recipients:
        resp = bot_core.send_message(msg, chat_id)
        if resp and not resp.get("ok") and resp.get("error_code") == 403:
            print(f"[Telegram] Removing blocked subscriber: {chat_id}")
            storage.remove_subscriber(chat_id)


# ── Helpers ─────────────────────────────────────────────────────

def drop_pct(open_p, cur):
    return ((open_p - cur) / open_p) * 100


def rise_pct(open_p, cur):
    return ((cur - open_p) / open_p) * 100


# ── Main Monitor ────────────────────────────────────────────────

def main():
    now = datetime.now(BANGKOK_TZ)
    hour = now.hour
    time_str = now.strftime("%d %b %Y %H:%M")

    print(f"[{time_str}] Gold Monitor v2 checking...")

    # ── Fetch Price ─────────────────────────────────────────────
    thb_gram, usd_oz, thb_rate = goldapi.get_gold_price()
    if thb_gram is None:
        notify("⚠️ <b>YLG Monitor</b>\nAPI error — ဈေးနှုန်း ယူမရပါ")
        return

    print(f"  Gold: {fmt(thb_gram)}/g (${usd_oz}/oz) [THB rate: {thb_rate}]")

    # ── Store Price History ─────────────────────────────────────
    history = storage.append_price(thb_gram, usd_oz, thb_rate)
    print(f"  History: {len(history)} data points stored")

    # ── Day State ───────────────────────────────────────────────
    state = storage.load_day_state()

    # First run of the day — anchor the day's open/high/low.
    if state["open_price"] is None:
        state.update({
            "open_price": thb_gram,
            "day_low": thb_gram,
            "day_high": thb_gram,
        })
        storage.save_day_state(state)

    # ── Morning Message ─────────────────────────────────────────
    # Send once per day during the morning window (6am–2pm BKK), gated by its
    # own `morning_sent` flag — NOT by the "first run of the day" check above.
    #
    # Why: the cron's last UTC hours fall after midnight BKK (e.g. 17:00 UTC =
    # 00:00 BKK the next day). Those overnight runs used to consume the
    # first-run slot — setting open_price at hour 0, outside the 6–14 window so
    # no message — and the real 7am run then saw open_price already set and
    # skipped the morning message entirely. Decoupling fixes that; the cron was
    # also tightened so open_price anchors at the true morning price.
    if 6 <= hour <= 14 and not state.get("morning_sent"):
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

        # Macro & fear context (DXY / US10Y / VIX). Omitted if unavailable.
        macro_block = signals.format_macro_block()
        macro_lines = f"\n━━━━━━━━━━━━━━━\n{macro_block}" if macro_block else ""

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
            f"{trend_lines}{ta_line}"
            f"{macro_lines}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"✅ Monitoring စပြီ!"
        )
        state["morning_sent"] = True
        storage.save_day_state(state)

    # ── Update Day Stats ────────────────────────────────────────
    state["day_low"] = min(state["day_low"], thb_gram)
    state["day_high"] = max(state["day_high"], thb_gram)
    d = drop_pct(state["open_price"], thb_gram)
    print(f"  Drop from open: {d:+.2f}%")

    # ── Multi-timeframe Analysis ────────────────────────────────
    ta = predictor.analyze(history) if len(history) >= 14 else {}
    trend = predictor.get_trend_summary(history) if len(history) >= 2 else {}

    # ── Drop Alerts (5 levels, equal spacing) ─────────────────────
    DROP_LEVELS = [
        {"mult": 1, "key": "notified_drop_1", "emoji": "🟡", "title": "ရွှေဈေး ကျဆင်း", "advice": "👉 YLG Get Gold ဖွင့်ဝယ်ပါ!"},
        {"mult": 2, "key": "notified_drop_2", "emoji": "🟠", "title": "ရွှေဈေး ဆက်ကျဆင်း", "advice": "💡 DCA ဝယ်ရန် စဉ်းစားပါ!"},
        {"mult": 3, "key": "notified_drop_3", "emoji": "🔴", "title": "ရွှေဈေး ကြီးစွာ ကျဆင်း", "advice": "🔥 DCA ထပ်ဝယ်ရန် အခွင့်ကောင်း!"},
        {"mult": 4, "key": "notified_drop_4", "emoji": "🔴🔴", "title": "ရွှေဈေး ပြင်းထန်စွာ ကျ", "advice": "⚠️ သတိထားပြီး DCA စဉ်းစားပါ!"},
        {"mult": 5, "key": "notified_drop_5", "emoji": "🚨", "title": "ရွှေဈေး အကြီးအကျယ် ကျဆင်း", "advice": "🏦 အရေးပေါ် — portfolio စစ်ဆေးပါ!"},
    ]

    ta_signal = f"\n🎯 TA Signal: {ta['overall_signal']}" if ta.get("overall_signal") else ""
    rsi_line = f"\n📊 RSI: {ta['rsi']}" if ta.get("rsi") else ""

    for level in DROP_LEVELS:
        threshold = DROP_THRESHOLD * level["mult"]
        if d >= threshold and not state.get(level["key"]):
            notify(
                f"{level['emoji']} <b>{level['title']}!</b>\n"
                f"⏰ {time_str}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"💰 လက်ရှိ  : {fmt(thb_gram)}/g\n"
                f"🌐 Spot    : ${usd_oz}/oz\n"
                f"📈 Open    : {fmt(state['open_price'])}/g\n"
                f"📉 ကျဆင်းမှု : {d:.2f}% (Level {level['mult']})\n"
                f"⬇️ ယနေ့ Low: {fmt(state['day_low'])}/g"
                f"{ta_signal}{rsi_line}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"{level['advice']}\n"
                f"📝 /bought &lt;THB&gt; ဖြင့် မှတ်ပါ"
            )
            state[level["key"]] = True

    # Reset drop notifications if price recovers
    if d < DROP_THRESHOLD * 0.3:
        for level in DROP_LEVELS:
            state[level["key"]] = False

    # ── Rise Alerts (5 levels, equal spacing) ──────────────────
    RISE_LEVELS = [
        {"mult": 1, "key": "notified_rise_1", "emoji": "🟢", "title": "ရွှေဈေး တက်နေပါတယ်", "advice": "💎 Portfolio တန်ဖိုး တက်နေပါပြီ!"},
        {"mult": 2, "key": "notified_rise_2", "emoji": "🟢🟢", "title": "ရွှေဈေး ဆက်တက်နေတယ်", "advice": "📊 Profit ယူရန် စဉ်းစားပါ!"},
        {"mult": 3, "key": "notified_rise_3", "emoji": "🟣", "title": "ရွှေဈေး ကြီးစွာ တက်", "advice": "💰 Partial profit ယူရန် စဉ်းစားပါ!"},
        {"mult": 4, "key": "notified_rise_4", "emoji": "🟣🟣", "title": "ရွှေဈေး ပြင်းထန်စွာ တက်", "advice": "⚡ ဈေးမြင့်ချိန် — profit ယူပါ!"},
        {"mult": 5, "key": "notified_rise_5", "emoji": "🚀", "title": "ရွှေဈေး အကြီးအကျယ် တက်", "advice": "🏆 အမြတ်ကြီး — sell စဉ်းစားပါ!"},
    ]

    r = rise_pct(state["open_price"], thb_gram)
    for level in RISE_LEVELS:
        threshold = RISE_THRESHOLD * level["mult"]
        if r >= threshold and not state.get(level["key"]):
            notify(
                f"{level['emoji']} <b>{level['title']}!</b>\n"
                f"⏰ {time_str}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"💰 လက်ရှိ  : {fmt(thb_gram)}/g\n"
                f"🌐 Spot    : ${usd_oz}/oz\n"
                f"📈 Open    : {fmt(state['open_price'])}/g\n"
                f"🚀 တက်မှု   : +{r:.2f}% (Level {level['mult']})\n"
                f"⬆️ ယနေ့ High: {fmt(state['day_high'])}/g"
                f"{ta_signal}{rsi_line}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"{level['advice']}"
            )
            state[level["key"]] = True

    # Reset rise notifications if price drops back
    if r < RISE_THRESHOLD * 0.3:
        for level in RISE_LEVELS:
            state[level["key"]] = False

    # ── Evening Summary (8pm BKK; window to 11:55pm absorbs Actions delays) ──
    if 20 <= hour <= 23 and not state["evening_sent"]:
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

        # Macro & fear context (DXY / US10Y / VIX). Omitted if unavailable.
        macro_block = signals.format_macro_block()
        macro_lines = f"\n━━━━━━━━━━━━━━━\n{macro_block}" if macro_block else ""

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
            f"{trend_lines}{streak_line}{portfolio_lines}{predict_line}"
            f"{macro_lines}\n"
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
