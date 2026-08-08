"""
Per-user interface language for Gold Monitor (English / Myanmar / Thai).

Every user-facing string lives here keyed by a stable id, with one entry per
language. Callers render with `t(key, lang, **params)`.

Design notes:
  * Myanmar is the DEFAULT and its text is copied verbatim from the original
    hard-coded messages, so existing users see no change until they opt in.
  * Keys hold the FULL message where a message is a fixed block, and small
    fragments where the caller assembles a block conditionally. Placeholders
    are `str.format` style and must match across all three languages — a test
    enforces both that invariant and the absence of missing translations.
  * Tickers and indicator names (RSI, MACD, DXY, VIX, USD, oz) are deliberately
    left untranslated; they are read as symbols in all three locales.
"""

from __future__ import annotations

# Display names shown in /lang, keyed by the code stored in user prefs.
LANGUAGES = {
    "en": "🇬🇧 English",
    "my": "🇲🇲 မြန်မာ",
    "th": "🇹🇭 ไทย",
}

DEFAULT_LANG = "my"

# Accepted spellings for /lang, mapped to a canonical code.
_ALIASES = {
    "en": "en", "eng": "en", "english": "en",
    "my": "my", "mm": "my", "mya": "my", "burmese": "my", "myanmar": "my",
    "မြန်မာ": "my",
    "th": "th", "tha": "th", "thai": "th", "ไทย": "th",
}


def normalize(lang) -> str:
    """Map any user input / stored value to a supported language code."""
    if not isinstance(lang, str):
        return DEFAULT_LANG
    return _ALIASES.get(lang.strip().lower(), DEFAULT_LANG)


def is_supported(lang) -> bool:
    """True if `lang` names a language we actually have (unlike normalize,
    which falls back). Used to reject bad /lang arguments."""
    return isinstance(lang, str) and lang.strip().lower() in _ALIASES


STRINGS: dict[str, dict[str, str]] = {
    # ── Shared errors ───────────────────────────────────────────
    "err.price_fetch": {
        "en": "⚠️ Could not fetch the price — API error",
        "my": "⚠️ ဈေးနှုန်း ယူမရပါ — API error",
        "th": "⚠️ ดึงราคาไม่สำเร็จ — API error",
    },
    "err.price_fetch_short": {
        "en": "⚠️ Could not fetch the price",
        "my": "⚠️ ဈေးနှုန်း ယူမရပါ",
        "th": "⚠️ ดึงราคาไม่สำเร็จ",
    },
    "err.price_fetch_retry": {
        "en": "⚠️ Could not fetch the price — please try again",
        "my": "⚠️ ဈေးနှုန်း ယူမရ — ထပ်ကြိုးစားပါ",
        "th": "⚠️ ดึงราคาไม่สำเร็จ — ลองใหม่อีกครั้ง",
    },
    "err.amount_positive": {
        "en": "⚠️ Amount must be greater than 0",
        "my": "⚠️ ပမာဏ 0 ထက်ကြီးရပါမည်",
        "th": "⚠️ จำนวนเงินต้องมากกว่า 0",
    },
    "err.generic": {
        "en": "⚠️ Error: {error}",
        "my": "⚠️ Error: {error}",
        "th": "⚠️ ข้อผิดพลาด: {error}",
    },
    "err.unknown_command": {
        "en": "❓ Unknown command: {cmd}\nType /help for available commands",
        "my": "❓ Unknown command: {cmd}\nType /help for available commands",
        "th": "❓ ไม่รู้จักคำสั่ง: {cmd}\nพิมพ์ /help เพื่อดูคำสั่งทั้งหมด",
    },
    "err.owner_only": {
        "en": "🔒 This command is for the bot owner only",
        "my": "🔒 ဒီ command က bot owner အတွက်သာ ဖြစ်ပါတယ်",
        "th": "🔒 คำสั่งนี้สำหรับเจ้าของบอทเท่านั้น",
    },
    "err.not_enough_data": {
        "en": "📊 Collecting data — not enough history yet",
        "my": "📊 Data collecting — not enough history yet",
        "th": "📊 กำลังเก็บข้อมูล — ประวัติยังไม่พอ",
    },

    # ── /price ──────────────────────────────────────────────────
    "price.header": {
        "en": "💰 <b>Gold Price Right Now</b>",
        "my": "💰 <b>ရွှေဈေး အခုလက်ရှိ</b>",
        "th": "💰 <b>ราคาทองตอนนี้</b>",
    },
    "price.pure": {
        "en": "🥇 <b>99.99% (Pure)</b>",
        "my": "🥇 <b>99.99% (Pure)</b>",
        "th": "🥇 <b>99.99% (ทองคำแท่ง)</b>",
    },
    "price.jewelry": {
        "en": "🥈 <b>96.50%</b>",
        "my": "🥈 <b>96.50%</b>",
        "th": "🥈 <b>96.50% (ทองรูปพรรณ)</b>",
    },
    "price.baht_weight": {
        "en": "  1 baht: {value}",
        "my": "  ဘတ်သား: {value}",
        "th": "  1 บาททอง: {value}",
    },
    "price.per_gram": {
        "en": "  1g: {value}",
        "my": "  1g: {value}",
        "th": "  1 กรัม: {value}",
    },
    "price.spot": {
        "en": "🌐 USD : ${value}/oz",
        "my": "🌐 USD : ${value}/oz",
        "th": "🌐 USD : ${value}/oz",
    },
    "price.rate": {
        "en": "💱 Rate: 1 USD = {value} THB",
        "my": "💱 Rate: 1 USD = {value} THB",
        "th": "💱 อัตรา: 1 USD = {value} THB",
    },
    "price.changes_header": {
        "en": "\n📊 <b>Changes:</b>",
        "my": "\n📊 <b>Changes:</b>",
        "th": "\n📊 <b>การเปลี่ยนแปลง:</b>",
    },
    "price.signal": {
        "en": "\n🎯 Signal: <b>{signal}</b>",
        "my": "\n🎯 Signal: <b>{signal}</b>",
        "th": "\n🎯 สัญญาณ: <b>{signal}</b>",
    },
    "price.rsi": {
        "en": "📊 RSI: {value}",
        "my": "📊 RSI: {value}",
        "th": "📊 RSI: {value}",
    },

    # ── /predict ────────────────────────────────────────────────
    "predict.need_data": {
        "en": ("📊 Data points: {n}/100\n"
               "TA requires 15+, ML requires 100+.\n"
               "Keep running — data accumulates every hour!"),
        "my": ("📊 Data points: {n}/100\n"
               "TA requires 15+, ML requires 100+.\n"
               "Keep running — data accumulates every hour!"),
        "th": ("📊 จำนวนข้อมูล: {n}/100\n"
               "TA ต้องการ 15+, ML ต้องการ 100+\n"
               "ปล่อยให้ทำงานต่อ — ข้อมูลจะเพิ่มขึ้นทุกชั่วโมง!"),
    },

    "predict.title": {
        "en": "🔮 Gold Price Outlook",
        "my": "🔮 ရွှေဈေး ခန့်မှန်းချက်",
        "th": "🔮 แนวโน้มราคาทอง",
    },
    "predict.current": {
        "en": "💰 Current: ฿{price:,.0f}/g{usd}",
        "my": "💰 လက်ရှိဈေး: ฿{price:,.0f}/g{usd}",
        "th": "💰 ราคาปัจจุบัน: ฿{price:,.0f}/g{usd}",
    },
    "predict.ml_ready": {
        "en": "Have {n} data points — models auto-train at 3am BKK",
        "my": "Data {n} ခု ရှိပြီ — 3am BKK တွင် auto-train ဖြစ်ပါမည်",
        "th": "มีข้อมูล {n} จุดแล้ว — โมเดลจะเทรนอัตโนมัติเวลา 03:00 น. (BKK)",
    },
    "predict.ml_collecting": {
        "en": "Data {n}/100 — {need} more needed",
        "my": "Data {n}/100 — {need} ခု ထပ်လိုပါသေးသည်",
        "th": "ข้อมูล {n}/100 — ต้องการอีก {need} จุด",
    },
    "predict.ml_note": {
        "en": "ℹ️ ML: {note}",
        "my": "ℹ️ ML: {note}",
        "th": "ℹ️ ML: {note}",
    },
    "predict.ml_header": {
        "en": "🤖 ML Predictions:",
        "my": "🤖 ML Predictions:",
        "th": "🤖 การพยากรณ์ ML:",
    },
    "predict.no_edge_note": {
        "en": "  ⚠️ No model beats a coin-flip out-of-sample — ML is noise here.",
        "my": "  ⚠️ No model beats a coin-flip out-of-sample — ML is noise here.",
        "th": "  ⚠️ ไม่มีโมเดลใดชนะการเดาสุ่มนอกกลุ่มตัวอย่าง — ML เป็น noise",
    },
    "predict.live_hit_rate": {
        "en": "🎯 Live hit-rate: {parts}",
        "my": "🎯 Live hit-rate: {parts}",
        "th": "🎯 ความแม่นยำจริง: {parts}",
    },
    "predict.tech_signal": {
        "en": "🎯 Technical Signal: {signal} (score: {score})",
        "my": "🎯 Technical Signal: {signal} (score: {score})",
        "th": "🎯 สัญญาณเทคนิค: {signal} (คะแนน: {score})",
    },

    # ── /chart ──────────────────────────────────────────────────
    "chart.no_data": {
        "en": "📊 Collecting data — not enough history for a chart yet",
        "my": "📊 Data collecting — not enough history for a chart yet",
        "th": "📊 กำลังเก็บข้อมูล — ยังไม่พอสำหรับสร้างกราฟ",
    },
    "chart.unavailable": {
        "en": "⚠️ Chart service unavailable — please try again shortly",
        "my": "⚠️ Chart service unavailable — ခဏနေ ပြန်စမ်းပါ",
        "th": "⚠️ บริการกราฟใช้งานไม่ได้ — ลองใหม่อีกสักครู่",
    },
    "chart.caption": {
        "en": ("📊 <b>Gold Price {days}-Day Chart</b>\n"
               "💰 Now: {now}/g | {arrow} {change:+.2f}%\n"
               "⬆️ High: {high} | ⬇️ Low: {low}"),
        "my": ("📊 <b>ရွှေဈေး {days}-Day Chart</b>\n"
               "💰 Now: {now}/g | {arrow} {change:+.2f}%\n"
               "⬆️ High: {high} | ⬇️ Low: {low}"),
        "th": ("📊 <b>กราฟราคาทอง {days} วัน</b>\n"
               "💰 ตอนนี้: {now}/g | {arrow} {change:+.2f}%\n"
               "⬆️ สูงสุด: {high} | ⬇️ ต่ำสุด: {low}"),
    },

    # ── /macro ──────────────────────────────────────────────────
    "macro.unavailable": {
        "en": "⚠️ Could not fetch macro data — please try again shortly",
        "my": "⚠️ Macro data ယူမရပါ — ခဏနေ ပြန်စမ်းပါ",
        "th": "⚠️ ดึงข้อมูล macro ไม่สำเร็จ — ลองใหม่อีกสักครู่",
    },
    "macro.footer": {
        "en": "ℹ️ Gold drivers — context only, not a forecast",
        "my": "ℹ️ Gold drivers — context only, not a forecast",
        "th": "ℹ️ ปัจจัยขับเคลื่อนราคาทอง — เป็นบริบทเท่านั้น ไม่ใช่การพยากรณ์",
    },
    "macro.title": {
        "en": "🌍 <b>Macro &amp; Fear</b>",
        "my": "🌍 <b>Macro &amp; Fear</b>",
        "th": "🌍 <b>Macro &amp; ความกลัว</b>",
    },
    "macro.fear": {
        "en": "  🌡 Fear: {score}/100 ({label})",
        "my": "  🌡 Fear: {score}/100 ({label})",
        "th": "  🌡 ความกลัว: {score}/100 ({label})",
    },
    "macro.bias": {
        "en": "  🧭 Gold bias: {bias}",
        "my": "  🧭 Gold bias: {bias}",
        "th": "  🧭 แนวโน้มทอง: {bias}",
    },
    "macro.fear.calm": {"en": "Calm", "my": "Calm", "th": "สงบ"},
    "macro.fear.normal": {"en": "Normal", "my": "Normal", "th": "ปกติ"},
    "macro.fear.elevated": {"en": "Elevated", "my": "Elevated", "th": "สูงขึ้น"},
    "macro.fear.high": {"en": "High fear", "my": "High fear", "th": "กลัวมาก"},
    "macro.fear.na": {"en": "n/a", "my": "n/a", "th": "ไม่มีข้อมูล"},
    "macro.bias.tailwind": {
        "en": "tailwind (dollar/yields easing)",
        "my": "tailwind (dollar/yields easing)",
        "th": "หนุน (ดอลลาร์/ผลตอบแทนอ่อนลง)",
    },
    "macro.bias.headwind": {
        "en": "headwind (dollar/yields rising)",
        "my": "headwind (dollar/yields rising)",
        "th": "กดดัน (ดอลลาร์/ผลตอบแทนสูงขึ้น)",
    },
    "macro.bias.mixed": {"en": "mixed", "my": "mixed", "th": "ผสม"},

    # ── /bought and /sold ───────────────────────────────────────
    "bought.usage": {
        "en": ("📝 Usage: <code>/bought 5000</code>\n"
               "5000 = amount you spent (THB)"),
        "my": ("📝 Usage: <code>/bought 5000</code>\n"
               "5000 = ဝယ်ယူသည့် ငွေပမာဏ (THB)"),
        "th": ("📝 วิธีใช้: <code>/bought 5000</code>\n"
               "5000 = จำนวนเงินที่ซื้อ (THB)"),
    },
    "bought.ok": {
        "en": ("✅ <b>Purchase logged!</b>\n"
               "━━━━━━━━━━━━━━━\n"
               "💵 Amount: {amount}\n"
               "💰 Price: {price}/gram\n"
               "⚖️ Gold: {grams:.4f} grams\n"
               "📅 {when}"),
        "my": ("✅ <b>ဝယ်ယူမှု မှတ်တမ်းတင်ပြီး!</b>\n"
               "━━━━━━━━━━━━━━━\n"
               "💵 ပမာဏ: {amount}\n"
               "💰 ဈေးနှုန်း: {price}/gram\n"
               "⚖️ ရွှေ: {grams:.4f} grams\n"
               "📅 {when}"),
        "th": ("✅ <b>บันทึกการซื้อแล้ว!</b>\n"
               "━━━━━━━━━━━━━━━\n"
               "💵 จำนวนเงิน: {amount}\n"
               "💰 ราคา: {price}/กรัม\n"
               "⚖️ ทอง: {grams:.4f} กรัม\n"
               "📅 {when}"),
    },
    "sold.usage": {
        "en": ("📝 Usage: <code>/sold 5000</code>\n"
               "5000 = amount you sold for (THB)"),
        "my": ("📝 Usage: <code>/sold 5000</code>\n"
               "5000 = ရောင်းချသည့် ငွေပမာဏ (THB)"),
        "th": ("📝 วิธีใช้: <code>/sold 5000</code>\n"
               "5000 = จำนวนเงินที่ขายได้ (THB)"),
    },
    "sold.not_enough": {
        "en": "⚠️ Not enough gold — your portfolio holds less than that",
        "my": "⚠️ ရွှေ မလုံလောက်ပါ — portfolio ထဲမှာ ရွှေအနည်းငယ်သာ ရှိပါသည်",
        "th": "⚠️ ทองไม่พอ — พอร์ตของคุณมีน้อยกว่านั้น",
    },
    "sold.ok": {
        "en": ("✅ <b>Sale logged!</b>\n"
               "━━━━━━━━━━━━━━━\n"
               "💵 Amount: {amount}\n"
               "💰 Price: {price}/gram\n"
               "⚖️ Gold: {grams:.4f} grams\n"
               "📅 {when}"),
        "my": ("✅ <b>ရောင်းချမှု မှတ်တမ်းတင်ပြီး!</b>\n"
               "━━━━━━━━━━━━━━━\n"
               "💵 ပမာဏ: {amount}\n"
               "💰 ဈေးနှုန်း: {price}/gram\n"
               "⚖️ ရွှေ: {grams:.4f} grams\n"
               "📅 {when}"),
        "th": ("✅ <b>บันทึกการขายแล้ว!</b>\n"
               "━━━━━━━━━━━━━━━\n"
               "💵 จำนวนเงิน: {amount}\n"
               "💰 ราคา: {price}/กรัม\n"
               "⚖️ ทอง: {grams:.4f} กรัม\n"
               "📅 {when}"),
    },

    # ── /edit and /delete ───────────────────────────────────────
    "edit.usage": {
        "en": ("📝 Usage: <code>/edit 3 6000</code>\n"
               "3 = entry number (see /portfolio)\n"
               "6000 = corrected amount (THB)"),
        "my": ("📝 Usage: <code>/edit 3 6000</code>\n"
               "3 = entry နံပါတ် (/portfolio မှာ ကြည့်ပါ)\n"
               "6000 = ပြင်ဆင်လိုသည့် ပမာဏ (THB)"),
        "th": ("📝 วิธีใช้: <code>/edit 3 6000</code>\n"
               "3 = หมายเลขรายการ (ดูที่ /portfolio)\n"
               "6000 = จำนวนเงินที่แก้ไข (THB)"),
    },
    "edit.numbers": {
        "en": "⚠️ /edit &lt;number&gt; &lt;amount&gt; — both must be numeric",
        "my": "⚠️ /edit &lt;နံပါတ်&gt; &lt;ပမာဏ&gt; — ဂဏန်းဖြစ်ရပါမည်",
        "th": "⚠️ /edit &lt;หมายเลข&gt; &lt;จำนวนเงิน&gt; — ต้องเป็นตัวเลข",
    },
    "edit.not_found": {
        "en": "⚠️ Entry #{index} not found — check /portfolio for numbers",
        "my": "⚠️ Entry #{index} မရှိပါ — /portfolio မှာ နံပါတ်ကြည့်ပါ",
        "th": "⚠️ ไม่พบรายการ #{index} — ดูหมายเลขที่ /portfolio",
    },
    "edit.ok": {
        "en": ("✏️ <b>Entry #{index} updated!</b>\n"
               "━━━━━━━━━━━━━━━\n"
               "📋 Type: {type}\n"
               "💵 Amount: {amount}\n"
               "💰 Price: {price}/gram\n"
               "⚖️ Gold: {grams:.4f} grams"),
        "my": ("✏️ <b>Entry #{index} ပြင်ဆင်ပြီး!</b>\n"
               "━━━━━━━━━━━━━━━\n"
               "📋 Type: {type}\n"
               "💵 ပမာဏ: {amount}\n"
               "💰 ဈေးနှုန်း: {price}/gram\n"
               "⚖️ ရွှေ: {grams:.4f} grams"),
        "th": ("✏️ <b>แก้ไขรายการ #{index} แล้ว!</b>\n"
               "━━━━━━━━━━━━━━━\n"
               "📋 ประเภท: {type}\n"
               "💵 จำนวนเงิน: {amount}\n"
               "💰 ราคา: {price}/กรัม\n"
               "⚖️ ทอง: {grams:.4f} กรัม"),
    },
    "delete.usage": {
        "en": ("📝 Usage: <code>/delete 3</code>\n"
               "3 = entry number to remove"),
        "my": ("📝 Usage: <code>/delete 3</code>\n"
               "3 = ဖျက်လိုသည့် entry နံပါတ်"),
        "th": ("📝 วิธีใช้: <code>/delete 3</code>\n"
               "3 = หมายเลขรายการที่ต้องการลบ"),
    },
    "delete.not_found": {
        "en": "⚠️ Entry #{index} not found",
        "my": "⚠️ Entry #{index} မရှိပါ",
        "th": "⚠️ ไม่พบรายการ #{index}",
    },
    "delete.ok": {
        "en": ("🗑 <b>Entry #{index} deleted!</b>\n"
               "📋 {type}: {amount} @ {price}/g"),
        "my": ("🗑 <b>Entry #{index} ဖျက်ပြီး!</b>\n"
               "📋 {type}: {amount} @ {price}/g"),
        "th": ("🗑 <b>ลบรายการ #{index} แล้ว!</b>\n"
               "📋 {type}: {amount} @ {price}/g"),
    },
    "entry.buy": {"en": "BUY", "my": "ဝယ်ယူ", "th": "ซื้อ"},
    "entry.sell": {"en": "SELL", "my": "ရောင်းချ", "th": "ขาย"},

    # ── /portfolio ──────────────────────────────────────────────
    "portfolio.empty": {
        "en": ("📂 No entries yet\n"
               "Use: <code>/bought 5000</code> to log a purchase\n"
               "Use: <code>/sold 3000</code> to log a sale"),
        "my": ("📂 မှတ်တမ်း မရှိသေးပါ\n"
               "Use: <code>/bought 5000</code> to log a purchase\n"
               "Use: <code>/sold 3000</code> to log a sale"),
        "th": ("📂 ยังไม่มีรายการ\n"
               "ใช้: <code>/bought 5000</code> เพื่อบันทึกการซื้อ\n"
               "ใช้: <code>/sold 3000</code> เพื่อบันทึกการขาย"),
    },
    "portfolio.header": {
        "en": "📊 <b>Gold Portfolio</b>",
        "my": "📊 <b>ရွှေ Portfolio</b>",
        "th": "📊 <b>พอร์ตทองคำ</b>",
    },
    "portfolio.counts": {
        "en": "📦 Buys: {buys} | Sells: {sells}",
        "my": "📦 Buys: {buys} | Sells: {sells}",
        "th": "📦 ซื้อ: {buys} | ขาย: {sells}",
    },
    "portfolio.invested": {
        "en": "💵 Invested: {value}",
        "my": "💵 Invested: {value}",
        "th": "💵 เงินลงทุน: {value}",
    },
    "portfolio.holdings": {
        "en": "⚖️ Holdings: {grams:.4f} grams",
        "my": "⚖️ Holdings: {grams:.4f} grams",
        "th": "⚖️ ถือครอง: {grams:.4f} กรัม",
    },
    "portfolio.avg_cost": {
        "en": "📈 Avg buy cost: {value}/gram",
        "my": "📈 Avg buy cost: {value}/gram",
        "th": "📈 ต้นทุนเฉลี่ย: {value}/กรัม",
    },
    "portfolio.current_price": {
        "en": "💰 Current price: {value}/gram",
        "my": "💰 Current price: {value}/gram",
        "th": "💰 ราคาปัจจุบัน: {value}/กรัม",
    },
    "portfolio.current_value": {
        "en": "💎 Current value: {value}",
        "my": "💎 Current value: {value}",
        "th": "💎 มูลค่าปัจจุบัน: {value}",
    },
    "portfolio.realized": {
        "en": "{emoji} Realized P&amp;L: {value}",
        "my": "{emoji} Realized P&amp;L: {value}",
        "th": "{emoji} กำไร/ขาดทุนที่รับรู้แล้ว: {value}",
    },
    "portfolio.unrealized": {
        "en": "{emoji} Unrealized P&amp;L: {value}",
        "my": "{emoji} Unrealized P&amp;L: {value}",
        "th": "{emoji} กำไร/ขาดทุนที่ยังไม่รับรู้: {value}",
    },
    "portfolio.total": {
        "en": "{emoji} <b>Total P&amp;L: {value} ({pct:+.2f}%)</b>",
        "my": "{emoji} <b>Total P&amp;L: {value} ({pct:+.2f}%)</b>",
        "th": "{emoji} <b>กำไร/ขาดทุนรวม: {value} ({pct:+.2f}%)</b>",
    },
    "portfolio.recent": {
        "en": "\n📝 <b>Recent entries:</b>",
        "my": "\n📝 <b>Recent entries:</b>",
        "th": "\n📝 <b>รายการล่าสุด:</b>",
    },

    # ── /history ────────────────────────────────────────────────
    "history.header": {
        "en": "📊 <b>Gold Price — {days}-Day History</b>",
        "my": "📊 <b>ရွှေဈေး {days}-Day History</b>",
        "th": "📊 <b>ประวัติราคาทอง {days} วัน</b>",
    },

    # ── /setthreshold and /setrisethreshold ─────────────────────
    "threshold.usage_drop": {
        "en": "Usage: <code>/setthreshold 0.5</code>",
        "my": "Usage: <code>/setthreshold 0.5</code>",
        "th": "วิธีใช้: <code>/setthreshold 0.5</code>",
    },
    "threshold.usage_rise": {
        "en": "Usage: <code>/setrisethreshold 0.5</code>",
        "my": "Usage: <code>/setrisethreshold 0.5</code>",
        "th": "วิธีใช้: <code>/setrisethreshold 0.5</code>",
    },
    "threshold.range": {
        "en": "⚠️ Must be between 0.1 and 10",
        "my": "⚠️ 0.1 — 10 ကြား ဖြစ်ရပါမည်",
        "th": "⚠️ ต้องอยู่ระหว่าง 0.1 — 10",
    },
    "threshold.drop_ok": {
        "en": ("✅ Drop alert threshold → <b>{val}%</b>\n"
               "🟡 L1: ≥{l1:g}% | 🟠 L2: ≥{l2:g}% | 🔴 L3: ≥{l3:g}%\n"
               "🔴🔴 L4: ≥{l4:g}% | 🚨 L5: ≥{l5:g}%"),
        "my": ("✅ Drop alert threshold → <b>{val}%</b>\n"
               "🟡 L1: ≥{l1:g}% | 🟠 L2: ≥{l2:g}% | 🔴 L3: ≥{l3:g}%\n"
               "🔴🔴 L4: ≥{l4:g}% | 🚨 L5: ≥{l5:g}%"),
        "th": ("✅ เกณฑ์แจ้งเตือนราคาลง → <b>{val}%</b>\n"
               "🟡 L1: ≥{l1:g}% | 🟠 L2: ≥{l2:g}% | 🔴 L3: ≥{l3:g}%\n"
               "🔴🔴 L4: ≥{l4:g}% | 🚨 L5: ≥{l5:g}%"),
    },
    "threshold.rise_ok": {
        "en": ("✅ Rise alert threshold → <b>{val}%</b>\n"
               "🟢 L1: ≥{l1:g}% | 🟢🟢 L2: ≥{l2:g}% | 🟣 L3: ≥{l3:g}%\n"
               "🟣🟣 L4: ≥{l4:g}% | 🚀 L5: ≥{l5:g}%"),
        "my": ("✅ Rise alert threshold → <b>{val}%</b>\n"
               "🟢 L1: ≥{l1:g}% | 🟢🟢 L2: ≥{l2:g}% | 🟣 L3: ≥{l3:g}%\n"
               "🟣🟣 L4: ≥{l4:g}% | 🚀 L5: ≥{l5:g}%"),
        "th": ("✅ เกณฑ์แจ้งเตือนราคาขึ้น → <b>{val}%</b>\n"
               "🟢 L1: ≥{l1:g}% | 🟢🟢 L2: ≥{l2:g}% | 🟣 L3: ≥{l3:g}%\n"
               "🟣🟣 L4: ≥{l4:g}% | 🚀 L5: ≥{l5:g}%"),
    },

    # ── /alert, /alerts, /delalert ──────────────────────────────
    "alert.usage": {
        "en": ("📝 Usage:\n"
               "<code>/alert above 4500</code> — tell me when the price reaches 4500\n"
               "<code>/alert below 4200</code> — tell me when it drops under 4200\n"
               "📋 /alerts — see the alerts you have set"),
        "my": ("📝 Usage:\n"
               "<code>/alert above 4500</code> — ဈေး 4500 ရောက်ရင် အကြောင်းကြားပါ\n"
               "<code>/alert below 4200</code> — ဈေး 4200 အောက်ကျရင် အကြောင်းကြားပါ\n"
               "📋 /alerts — သတ်မှတ်ထားသော alerts ကြည့်ပါ"),
        "th": ("📝 วิธีใช้:\n"
               "<code>/alert above 4500</code> — แจ้งเมื่อราคาถึง 4500\n"
               "<code>/alert below 4200</code> — แจ้งเมื่อราคาต่ำกว่า 4200\n"
               "📋 /alerts — ดูการแจ้งเตือนที่ตั้งไว้"),
    },
    "alert.price_positive": {
        "en": "⚠️ Price must be greater than 0",
        "my": "⚠️ ဈေးနှုန်း 0 ထက်ကြီးရပါမည်",
        "th": "⚠️ ราคาต้องมากกว่า 0",
    },
    "alert.must_be_above": {
        "en": "⚠️ Must be higher than the current price {price} (above alert)",
        "my": "⚠️ လက်ရှိဈေး {price} ထက် မြင့်ရပါမည် (above alert)",
        "th": "⚠️ ต้องสูงกว่าราคาปัจจุบัน {price} (above alert)",
    },
    "alert.must_be_below": {
        "en": "⚠️ Must be lower than the current price {price} (below alert)",
        "my": "⚠️ လက်ရှိဈေး {price} ထက် နိမ့်ရပါမည် (below alert)",
        "th": "⚠️ ต้องต่ำกว่าราคาปัจจุบัน {price} (below alert)",
    },
    "alert.limit": {
        "en": "⚠️ You can have at most {max} alerts — remove one with /delalert first",
        "my": "⚠️ Alert {max} ခုထက် မပိုနိုင်ပါ — /delalert ဖြင့် အရင်ဖျက်ပါ",
        "th": "⚠️ ตั้งได้สูงสุด {max} รายการ — ลบด้วย /delalert ก่อน",
    },
    "alert.ok_above": {
        "en": ("✅ <b>Alert set!</b>\n"
               "⬆️ I will tell you when the price reaches {price}/g\n"
               "ℹ️ One-shot — it is removed automatically after it fires"),
        "my": ("✅ <b>Alert သတ်မှတ်ပြီး!</b>\n"
               "⬆️ ဈေး {price}/g ရောက်ရင် အကြောင်းကြားပါမည်\n"
               "ℹ️ တစ်ကြိမ်သာ — fire ပြီးရင် auto ဖျက်ပါမည်"),
        "th": ("✅ <b>ตั้งการแจ้งเตือนแล้ว!</b>\n"
               "⬆️ จะแจ้งเมื่อราคาถึง {price}/g\n"
               "ℹ️ ครั้งเดียว — จะถูกลบอัตโนมัติหลังแจ้ง"),
    },
    "alert.ok_below": {
        "en": ("✅ <b>Alert set!</b>\n"
               "⬇️ I will tell you when the price drops under {price}/g\n"
               "ℹ️ One-shot — it is removed automatically after it fires"),
        "my": ("✅ <b>Alert သတ်မှတ်ပြီး!</b>\n"
               "⬇️ ဈေး {price}/g အောက်ကျရင် အကြောင်းကြားပါမည်\n"
               "ℹ️ တစ်ကြိမ်သာ — fire ပြီးရင် auto ဖျက်ပါမည်"),
        "th": ("✅ <b>ตั้งการแจ้งเตือนแล้ว!</b>\n"
               "⬇️ จะแจ้งเมื่อราคาต่ำกว่า {price}/g\n"
               "ℹ️ ครั้งเดียว — จะถูกลบอัตโนมัติหลังแจ้ง"),
    },
    "alerts.empty": {
        "en": ("📂 No alerts yet\n"
               "Use: <code>/alert above 4500</code> or <code>/alert below 4200</code>"),
        "my": ("📂 Alert မရှိသေးပါ\n"
               "Use: <code>/alert above 4500</code> or <code>/alert below 4200</code>"),
        "th": ("📂 ยังไม่มีการแจ้งเตือน\n"
               "ใช้: <code>/alert above 4500</code> หรือ <code>/alert below 4200</code>"),
    },
    "alerts.header": {
        "en": "🎯 <b>Your Price Alerts</b>",
        "my": "🎯 <b>သင့် Price Alerts</b>",
        "th": "🎯 <b>การแจ้งเตือนราคาของคุณ</b>",
    },
    "alerts.delete_hint": {
        "en": "🗑 Remove with: <code>/delalert 1</code>",
        "my": "🗑 ဖျက်ရန်: <code>/delalert 1</code>",
        "th": "🗑 ลบด้วย: <code>/delalert 1</code>",
    },
    "delalert.usage": {
        "en": "📝 Usage: <code>/delalert 1</code> (see numbers in /alerts)",
        "my": "📝 Usage: <code>/delalert 1</code> (/alerts မှာ နံပါတ်ကြည့်ပါ)",
        "th": "📝 วิธีใช้: <code>/delalert 1</code> (ดูหมายเลขที่ /alerts)",
    },
    "delalert.not_found": {
        "en": "⚠️ Alert #{index} not found — check /alerts",
        "my": "⚠️ Alert #{index} မရှိပါ — /alerts မှာ ကြည့်ပါ",
        "th": "⚠️ ไม่พบการแจ้งเตือน #{index} — ดูที่ /alerts",
    },
    "delalert.ok": {
        "en": "🗑 Alert removed: {dir} {price}/g",
        "my": "🗑 Alert ဖျက်ပြီး: {dir} {price}/g",
        "th": "🗑 ลบการแจ้งเตือนแล้ว: {dir} {price}/g",
    },

    # ── /subscribe and /unsubscribe ─────────────────────────────
    "subscribe.owner": {
        "en": "✅ You are the bot owner — you always receive alerts",
        "my": "✅ သင်က bot owner ဖြစ်ပါတယ် — အမြဲတမ်း alerts ရရှိပါတယ်",
        "th": "✅ คุณคือเจ้าของบอท — จะได้รับการแจ้งเตือนเสมอ",
    },
    "subscribe.ok": {
        "en": ("✅ <b>Subscribed!</b>\n"
               "🌅 Morning gold price\n"
               "🌙 Evening summary\n"
               "📊 Price alerts\n"
               "━━━━━━━━━━━━━━━\n"
               "Send /unsubscribe to stop"),
        "my": ("✅ <b>Subscribe လုပ်ပြီးပါပြီ!</b>\n"
               "🌅 မနက်ခင်း ရွှေဈေး\n"
               "🌙 ညနေ အနှစ်ချုပ်\n"
               "📊 ဈေးနှုန်း alerts\n"
               "━━━━━━━━━━━━━━━\n"
               "ရပ်ချင်ရင် /unsubscribe ရိုက်ပါ"),
        "th": ("✅ <b>สมัครรับข้อมูลแล้ว!</b>\n"
               "🌅 ราคาทองตอนเช้า\n"
               "🌙 สรุปตอนเย็น\n"
               "📊 แจ้งเตือนราคา\n"
               "━━━━━━━━━━━━━━━\n"
               "พิมพ์ /unsubscribe เพื่อหยุด"),
    },
    "subscribe.already": {
        "en": "ℹ️ Already subscribed — use /unsubscribe to stop",
        "my": "ℹ️ Subscribe ဖြစ်ပြီးသားပါ — /unsubscribe နဲ့ ရပ်နိုင်ပါတယ်",
        "th": "ℹ️ สมัครไว้แล้ว — ใช้ /unsubscribe เพื่อหยุด",
    },
    "unsubscribe.owner": {
        "en": "ℹ️ You are the bot owner — you cannot unsubscribe",
        "my": "ℹ️ သင်က bot owner ဖြစ်ပါတယ် — unsubscribe လုပ်လို့မရပါ",
        "th": "ℹ️ คุณคือเจ้าของบอท — ยกเลิกไม่ได้",
    },
    "unsubscribe.ok": {
        "en": "👋 Unsubscribed — no more alerts will be sent",
        "my": "👋 Unsubscribe လုပ်ပြီးပါပြီ — alerts ပို့တော့မှာ မဟုတ်ပါ",
        "th": "👋 ยกเลิกแล้ว — จะไม่ส่งการแจ้งเตือนอีก",
    },
    "unsubscribe.not_subscribed": {
        "en": "ℹ️ You are not subscribed — send /subscribe to start",
        "my": "ℹ️ Subscribe မလုပ်ရသေးပါ — /subscribe နဲ့ စတင်ပါ",
        "th": "ℹ️ คุณยังไม่ได้สมัคร — พิมพ์ /subscribe เพื่อเริ่ม",
    },

    # ── /settings, /mute, /quiet ────────────────────────────────
    "settings.header": {
        "en": "⚙️ <b>Notification Settings</b>",
        "my": "⚙️ <b>Notification Settings</b>",
        "th": "⚙️ <b>ตั้งค่าการแจ้งเตือน</b>",
    },
    "settings.morning": {"en": "🌅 Morning", "my": "🌅 Morning", "th": "🌅 ตอนเช้า"},
    "settings.evening": {"en": "🌙 Evening", "my": "🌙 Evening", "th": "🌙 ตอนเย็น"},
    "settings.alerts": {"en": "📊 Price alerts", "my": "📊 Price alerts", "th": "📊 แจ้งเตือนราคา"},
    "settings.on": {"en": "🔔 ON", "my": "🔔 ON", "th": "🔔 เปิด"},
    "settings.off": {"en": "🔕 OFF", "my": "🔕 OFF", "th": "🔕 ปิด"},
    "settings.quiet": {
        "en": "  🤫 Quiet hours: {value}",
        "my": "  🤫 Quiet hours: {value}",
        "th": "  🤫 ช่วงเวลาเงียบ: {value}",
    },
    "settings.language": {
        "en": "  🌐 Language: {value}",
        "my": "  🌐 Language: {value}",
        "th": "  🌐 ภาษา: {value}",
    },
    "settings.hints": {
        "en": ("🔕 <code>/mute morning|evening|alerts</code>\n"
               "🔔 <code>/unmute morning|evening|alerts</code>\n"
               "🤫 <code>/quiet 22-7</code> | <code>/quiet off</code>\n"
               "🌐 <code>/lang en|my|th</code>"),
        "my": ("🔕 <code>/mute morning|evening|alerts</code>\n"
               "🔔 <code>/unmute morning|evening|alerts</code>\n"
               "🤫 <code>/quiet 22-7</code> | <code>/quiet off</code>\n"
               "🌐 <code>/lang en|my|th</code>"),
        "th": ("🔕 <code>/mute morning|evening|alerts</code>\n"
               "🔔 <code>/unmute morning|evening|alerts</code>\n"
               "🤫 <code>/quiet 22-7</code> | <code>/quiet off</code>\n"
               "🌐 <code>/lang en|my|th</code>"),
    },
    "mute.usage": {
        "en": "📝 Usage: <code>/{cmd} morning|evening|alerts</code>",
        "my": "📝 Usage: <code>/{cmd} morning|evening|alerts</code>",
        "th": "📝 วิธีใช้: <code>/{cmd} morning|evening|alerts</code>",
    },
    "mute.result": {
        "en": "{icon} {label} notifications: <b>{state}</b>",
        "my": "{icon} {label} notifications: <b>{state}</b>",
        "th": "{icon} การแจ้งเตือน {label}: <b>{state}</b>",
    },
    "mute.on": {"en": "ON", "my": "ON", "th": "เปิด"},
    "mute.off": {"en": "OFF", "my": "OFF", "th": "ปิด"},
    "quiet.off": {
        "en": "🔔 Quiet hours: <b>OFF</b> — notifications may arrive any time",
        "my": "🔔 Quiet hours: <b>OFF</b> — အချိန်မရွေး notifications ရပါမည်",
        "th": "🔔 ช่วงเวลาเงียบ: <b>ปิด</b> — รับการแจ้งเตือนได้ทุกเวลา",
    },
    "quiet.usage": {
        "en": ("📝 Usage: <code>/quiet 22-7</code> (BKK hours, silent 22:00–07:00)\n"
               "Turn off with: <code>/quiet off</code>"),
        "my": ("📝 Usage: <code>/quiet 22-7</code> (BKK နာရီ၊ 22:00–07:00 ဆိတ်ငြိမ်)\n"
               "ပိတ်ရန်: <code>/quiet off</code>"),
        "th": ("📝 วิธีใช้: <code>/quiet 22-7</code> (เวลากรุงเทพฯ เงียบ 22:00–07:00)\n"
               "ปิดด้วย: <code>/quiet off</code>"),
    },
    "quiet.ok": {
        "en": ("🤫 Quiet hours: <b>{spec}</b> (BKK)\n"
               "Broadcast notifications are held during this window\n"
               "ℹ️ Your /alert price alerts still come through"),
        "my": ("🤫 Quiet hours: <b>{spec}</b> (BKK)\n"
               "ဤအချိန်အတွင်း broadcast notifications မပို့ပါ\n"
               "ℹ️ /alert price alerts များက ဆက်ရပါမည်"),
        "th": ("🤫 ช่วงเวลาเงียบ: <b>{spec}</b> (เวลากรุงเทพฯ)\n"
               "จะไม่ส่งการแจ้งเตือนทั่วไปในช่วงนี้\n"
               "ℹ️ การแจ้งเตือนราคาจาก /alert ยังส่งตามปกติ"),
    },

    # ── /lang ───────────────────────────────────────────────────
    "lang.usage": {
        "en": ("🌐 <b>Language</b>\n"
               "━━━━━━━━━━━━━━━\n"
               "Current: <b>{current}</b>\n"
               "━━━━━━━━━━━━━━━\n"
               "<code>/lang en</code> — English\n"
               "<code>/lang my</code> — မြန်မာ\n"
               "<code>/lang th</code> — ไทย\n"
               "ℹ️ Applies to alerts and command replies"),
        "my": ("🌐 <b>ဘာသာစကား</b>\n"
               "━━━━━━━━━━━━━━━\n"
               "လက်ရှိ: <b>{current}</b>\n"
               "━━━━━━━━━━━━━━━\n"
               "<code>/lang en</code> — English\n"
               "<code>/lang my</code> — မြန်မာ\n"
               "<code>/lang th</code> — ไทย\n"
               "ℹ️ Alerts နှင့် command အဖြေများအတွက် အကျုံးဝင်ပါသည်"),
        "th": ("🌐 <b>ภาษา</b>\n"
               "━━━━━━━━━━━━━━━\n"
               "ปัจจุบัน: <b>{current}</b>\n"
               "━━━━━━━━━━━━━━━\n"
               "<code>/lang en</code> — English\n"
               "<code>/lang my</code> — မြန်မာ\n"
               "<code>/lang th</code> — ไทย\n"
               "ℹ️ มีผลกับการแจ้งเตือนและคำตอบของคำสั่ง"),
    },
    "lang.invalid": {
        "en": "⚠️ Unknown language: {choice}",
        "my": "⚠️ ဘာသာစကား မသိပါ: {choice}",
        "th": "⚠️ ไม่รู้จักภาษา: {choice}",
    },
    "lang.ok": {
        "en": ("✅ Language set to <b>{lang}</b>\n"
               "All alerts and replies will now be in English."),
        "my": ("✅ ဘာသာစကား <b>{lang}</b> သို့ ပြောင်းပြီးပါပြီ\n"
               "Alerts နှင့် အဖြေအားလုံး မြန်မာဘာသာဖြင့် ရရှိပါမည်။"),
        "th": ("✅ ตั้งภาษาเป็น <b>{lang}</b> แล้ว\n"
               "การแจ้งเตือนและคำตอบทั้งหมดจะเป็นภาษาไทย"),
    },

    # ── /help ───────────────────────────────────────────────────
    "help.text": {
        "en": ("🤖 <b>Gold Monitor Commands</b>\n"
               "━━━━━━━━━━━━━━━\n"
               "💰 /price — current gold price\n"
               "🔮 /predict — 4h/12h/24h outlook\n"
               "📊 /chart [N] — N-day price chart (default 7)\n"
               "🎯 /alert above|below &lt;THB&gt; — alert me at a price\n"
               "📋 /alerts — your alerts | 🗑 /delalert &lt;#&gt;\n"
               "🌍 /macro — DXY / US10Y / VIX + fear score\n"
               "📅 /events — upcoming FOMC / CPI / NFP releases\n"
               "📝 /bought &lt;THB&gt; — log a purchase\n"
               "📝 /sold &lt;THB&gt; — log a sale\n"
               "✏️ /edit &lt;#&gt; &lt;THB&gt; — edit an entry\n"
               "🗑 /delete &lt;#&gt; — delete an entry\n"
               "📊 /portfolio — portfolio P&amp;L\n"
               "📈 /history [N] — N-day price history\n"
               "⚙️ /setthreshold N — change drop alert %\n"
               "📈 /setrisethreshold N — change rise alert %\n"
               "🔔 /subscribe — receive price alerts\n"
               "🔕 /unsubscribe — stop alerts\n"
               "⚙️ /settings — notifications (mute / quiet hours)\n"
               "🌐 /lang en|my|th — change language\n"
               "❓ /help — this menu\n"
               "━━━━━━━━━━━━━━━\n"
               "⚡ Instant replies via webhook"),
        "my": ("🤖 <b>Gold Monitor Commands</b>\n"
               "━━━━━━━━━━━━━━━\n"
               "💰 /price — လက်ရှိ ရွှေဈေး\n"
               "🔮 /predict — 4h/12h/24h ခန့်မှန်းချက်\n"
               "📊 /chart [N] — N-day ဈေး chart (default 7)\n"
               "🎯 /alert above|below &lt;THB&gt; — ဈေးရောက်ရင် အကြောင်းကြားပါ\n"
               "📋 /alerts — သင့် alerts | 🗑 /delalert &lt;#&gt;\n"
               "🌍 /macro — DXY / US10Y / VIX + fear score\n"
               "📅 /events — လာမည့် FOMC / CPI / NFP ကြေညာချက်များ\n"
               "📝 /bought &lt;THB&gt; — ဝယ်ယူမှု မှတ်ပါ\n"
               "📝 /sold &lt;THB&gt; — ရောင်းချမှု မှတ်ပါ\n"
               "✏️ /edit &lt;#&gt; &lt;THB&gt; — entry ပြင်ဆင်ပါ\n"
               "🗑 /delete &lt;#&gt; — entry ဖျက်ပါ\n"
               "📊 /portfolio — Portfolio P&amp;L\n"
               "📈 /history [N] — N-day ဈေးသမိုင်း\n"
               "⚙️ /setthreshold N — Drop alert % ပြောင်းပါ\n"
               "📈 /setrisethreshold N — Rise alert % ပြောင်းပါ\n"
               "🔔 /subscribe — ဈေးနှုန်း alerts ရယူပါ\n"
               "🔕 /unsubscribe — alerts ရပ်ပါ\n"
               "⚙️ /settings — notification settings (mute / quiet hours)\n"
               "🌐 /lang en|my|th — ဘာသာစကား ပြောင်းပါ\n"
               "❓ /help — ဤ menu\n"
               "━━━━━━━━━━━━━━━\n"
               "⚡ Instant replies via webhook"),
        "th": ("🤖 <b>คำสั่ง Gold Monitor</b>\n"
               "━━━━━━━━━━━━━━━\n"
               "💰 /price — ราคาทองปัจจุบัน\n"
               "🔮 /predict — แนวโน้ม 4h/12h/24h\n"
               "📊 /chart [N] — กราฟราคา N วัน (ค่าเริ่มต้น 7)\n"
               "🎯 /alert above|below &lt;THB&gt; — แจ้งเตือนที่ราคาที่กำหนด\n"
               "📋 /alerts — การแจ้งเตือนของคุณ | 🗑 /delalert &lt;#&gt;\n"
               "🌍 /macro — DXY / US10Y / VIX + คะแนนความกลัว\n"
               "📅 /events — FOMC / CPI / NFP ที่กำลังจะประกาศ\n"
               "📝 /bought &lt;THB&gt; — บันทึกการซื้อ\n"
               "📝 /sold &lt;THB&gt; — บันทึกการขาย\n"
               "✏️ /edit &lt;#&gt; &lt;THB&gt; — แก้ไขรายการ\n"
               "🗑 /delete &lt;#&gt; — ลบรายการ\n"
               "📊 /portfolio — กำไร/ขาดทุนพอร์ต\n"
               "📈 /history [N] — ประวัติราคา N วัน\n"
               "⚙️ /setthreshold N — เปลี่ยน % แจ้งเตือนราคาลง\n"
               "📈 /setrisethreshold N — เปลี่ยน % แจ้งเตือนราคาขึ้น\n"
               "🔔 /subscribe — รับการแจ้งเตือนราคา\n"
               "🔕 /unsubscribe — หยุดการแจ้งเตือน\n"
               "⚙️ /settings — ตั้งค่าการแจ้งเตือน (mute / quiet hours)\n"
               "🌐 /lang en|my|th — เปลี่ยนภาษา\n"
               "❓ /help — เมนูนี้\n"
               "━━━━━━━━━━━━━━━\n"
               "⚡ ตอบทันทีผ่าน webhook"),
    },

    # ── Market regime (volatility + driver divergence) ──────────
    "regime.vol_elevated": {
        "en": "⚡ Volatility {ratio}× normal — larger moves than usual",
        "my": "⚡ ဈေးလှုပ်ရှားမှု ပုံမှန်ထက် {ratio} ဆ — ပုံမှန်ထက် ကြီးမားသည်",
        "th": "⚡ ความผันผวน {ratio} เท่าของปกติ — ราคาขยับแรงกว่าปกติ",
    },
    "regime.vol_extreme": {
        "en": "🌪 Volatility {ratio}× normal — something is moving this market",
        "my": "🌪 ဈေးလှုပ်ရှားမှု ပုံမှန်ထက် {ratio} ဆ — တစ်ခုခု ဖြစ်နေသည်",
        "th": "🌪 ความผันผวน {ratio} เท่าของปกติ — มีบางอย่างกำลังขับเคลื่อนตลาด",
    },
    "regime.shock": {
        "en": "❗ Last move {move:+.2f}% — {sigma}σ vs its own baseline, worth checking the news",
        "my": "❗ နောက်ဆုံး ပြောင်းလဲမှု {move:+.2f}% — baseline ထက် {sigma}σ၊ သတင်း စစ်သင့်သည်",
        "th": "❗ การเปลี่ยนแปลงล่าสุด {move:+.2f}% — {sigma}σ เทียบค่าปกติ ควรเช็กข่าว",
    },
    "regime.div.safe_haven": {
        "en": "🛡 Gold rising against BOTH a stronger dollar and higher yields — safe-haven bid, not a rates move",
        "my": "🛡 ဒေါ်လာနှင့် yields နှစ်ခုလုံး တက်နေချိန် ရွှေတက် — safe-haven ဝယ်လိုအား၊ အတိုးနှုန်း အကြောင်း မဟုတ်",
        "th": "🛡 ทองขึ้นสวนทางทั้งดอลลาร์แข็งและผลตอบแทนสูงขึ้น — แรงซื้อสินทรัพย์ปลอดภัย ไม่ใช่เรื่องดอกเบี้ย",
    },
    "regime.div.liquidation": {
        "en": "🩸 Gold falling despite a weaker dollar and lower yields — looks like forced selling",
        "my": "🩸 ဒေါ်လာနှင့် yields ကျနေသော်လည်း ရွှေကျနေ — အတင်းရောင်းချမှု ဖြစ်နိုင်",
        "th": "🩸 ทองลงทั้งที่ดอลลาร์อ่อนและผลตอบแทนลดลง — น่าจะเป็นการเทขาย",
    },
    "regime.header": {
        "en": "🔍 <b>Market Regime</b>",
        "my": "🔍 <b>ဈေးကွက် အခြေအနေ</b>",
        "th": "🔍 <b>สภาวะตลาด</b>",
    },
    "regime.calm": {
        "en": "😴 Volatility {ratio}× normal — quiet market",
        "my": "😴 ဈေးလှုပ်ရှားမှု ပုံမှန်ထက် {ratio} ဆ — ငြိမ်သက်နေသည်",
        "th": "😴 ความผันผวน {ratio} เท่าของปกติ — ตลาดเงียบ",
    },
    "regime.normal": {
        "en": "🟢 Volatility {ratio}× normal",
        "my": "🟢 ဈေးလှုပ်ရှားမှု ပုံမှန်ထက် {ratio} ဆ",
        "th": "🟢 ความผันผวน {ratio} เท่าของปกติ",
    },
    "regime.unavailable": {
        "en": "📊 Collecting data — {have}/{need} points needed for a volatility baseline",
        "my": "📊 Data စုဆောင်းနေသည် — volatility baseline အတွက် {have}/{need} လိုအပ်သည်",
        "th": "📊 กำลังเก็บข้อมูล — ต้องการ {have}/{need} จุดเพื่อคำนวณค่าฐาน",
    },

    # ── Economic event calendar ─────────────────────────────────
    "event.type.fomc": {
        "en": "FOMC rate decision", "my": "FOMC အတိုးနှုန်း ဆုံးဖြတ်ချက်",
        "th": "การประชุม FOMC (ดอกเบี้ย)",
    },
    "event.type.cpi": {
        "en": "US CPI inflation", "my": "US CPI ငွေကြေးဖောင်းပွမှု",
        "th": "เงินเฟ้อ CPI สหรัฐ",
    },
    "event.type.nfp": {
        "en": "US Non-Farm Payrolls", "my": "US Non-Farm Payrolls (အလုပ်အကိုင်)",
        "th": "การจ้างงานนอกภาคเกษตรสหรัฐ",
    },
    "event.type.pce": {
        "en": "US PCE inflation", "my": "US PCE ငွေကြေးဖောင်းပွမှု",
        "th": "เงินเฟ้อ PCE สหรัฐ",
    },
    "event.type.other": {"en": "Scheduled release", "my": "သတ်မှတ်ထားသော ကြေညာချက်",
                         "th": "การประกาศตามกำหนด"},

    "predict.models_stale": {
        "en": "ℹ️ Models are being rebuilt for the new event features — ML resumes after the 3am BKK retrain.",
        "my": "ℹ️ Event features အသစ်အတွက် models ပြန်တည်ဆောက်နေပါသည် — 3am BKK retrain ပြီးမှ ML ပြန်ရပါမည်။",
        "th": "ℹ️ กำลังสร้างโมเดลใหม่สำหรับฟีเจอร์เหตุการณ์ — ML จะกลับมาหลังเทรนรอบ 03:00 น. (BKK)",
    },
    "events.header": {
        "en": "📅 <b>Upcoming Market Events</b>",
        "my": "📅 <b>လာမည့် ဈေးကွက် အဖြစ်အပျက်များ</b>",
        "th": "📅 <b>เหตุการณ์ตลาดที่กำลังจะมาถึง</b>",
    },
    "events.line": {
        "en": "{emoji} <b>{name}</b>{est}\n     {when} (BKK) — in {countdown}",
        "my": "{emoji} <b>{name}</b>{est}\n     {when} (BKK) — နောက် {countdown}",
        "th": "{emoji} <b>{name}</b>{est}\n     {when} (BKK) — อีก {countdown}",
    },
    "events.estimated": {
        "en": " <i>(estimated)</i>", "my": " <i>(ခန့်မှန်း)</i>",
        "th": " <i>(ประมาณการ)</i>",
    },
    "events.none": {
        "en": "📅 No scheduled events on the calendar.",
        "my": "📅 သတ်မှတ်ထားသော အဖြစ်အပျက် မရှိပါ။",
        "th": "📅 ไม่มีเหตุการณ์ในปฏิทิน",
    },
    "events.footer": {
        "en": "ℹ️ Gold often moves sharply around these — timing only, not a forecast",
        "my": "ℹ️ ဤအချိန်များတွင် ရွှေဈေး ပြင်းထန်စွာ လှုပ်ရှားတတ်သည် — အချိန်သာ၊ ခန့်မှန်းချက် မဟုတ်ပါ",
        "th": "ℹ️ ราคาทองมักผันผวนแรงช่วงนี้ — บอกเวลาเท่านั้น ไม่ใช่การพยากรณ์",
    },
    "events.stale": {
        "en": ("⚠️ <b>Calendar needs updating</b> — only {days}d of events left.\n"
               "Refresh CALENDAR in events.py from federalreserve.gov / bls.gov."),
        "my": ("⚠️ <b>Calendar update လိုအပ်သည်</b> — {days} ရက်စာသာ ကျန်တော့သည်။\n"
               "events.py ထဲရှိ CALENDAR ကို federalreserve.gov / bls.gov မှ ပြန်ဖြည့်ပါ။"),
        "th": ("⚠️ <b>ต้องอัปเดตปฏิทิน</b> — เหลือเหตุการณ์อีกเพียง {days} วัน\n"
               "รีเฟรช CALENDAR ใน events.py จาก federalreserve.gov / bls.gov"),
    },
    "events.countdown_h": {"en": "{h}h {m}m", "my": "{h}h {m}m", "th": "{h} ชม. {m} น."},
    "events.countdown_d": {"en": "{d}d {h}h", "my": "{d}d {h}h", "th": "{d} วัน {h} ชม."},

    "events.banner_pre": {
        "en": "\n⚠️ <b>{name} in {countdown}</b> — expect volatility",
        "my": "\n⚠️ <b>{name} — နောက် {countdown}</b> — ဈေးလှုပ်ရှားမှု ကြီးနိုင်သည်",
        "th": "\n⚠️ <b>{name} อีก {countdown}</b> — คาดว่าจะผันผวน",
    },
    "events.banner_post": {
        "en": "\n📰 <b>{name} just released</b> — this move is likely event-driven",
        "my": "\n📰 <b>{name} ထွက်ပြီ</b> — ဤဈေးလှုပ်ရှားမှုမှာ သတင်းကြောင့် ဖြစ်နိုင်သည်",
        "th": "\n📰 <b>{name} เพิ่งประกาศ</b> — ราคาที่ขยับน่าจะมาจากข่าวนี้",
    },
    "events.ta_caution": {
        "en": "\n⚠️ TA is unreliable inside an event window — treat the signal with caution",
        "my": "\n⚠️ Event window အတွင်း TA မမှန်တတ်ပါ — signal ကို သတိဖြင့် သုံးပါ",
        "th": "\n⚠️ TA ไม่น่าเชื่อถือในช่วงเหตุการณ์ — ใช้สัญญาณอย่างระมัดระวัง",
    },

    # ── Inline keyboard button labels ───────────────────────────
    "btn.price": {"en": "💰 Price", "my": "💰 Price", "th": "💰 ราคา"},
    "btn.predict": {"en": "🔮 Predict", "my": "🔮 Predict", "th": "🔮 พยากรณ์"},
    "btn.chart": {"en": "📊 Chart", "my": "📊 Chart", "th": "📊 กราฟ"},
    "btn.macro": {"en": "🌍 Macro", "my": "🌍 Macro", "th": "🌍 Macro"},
    "btn.subscribe": {"en": "🔔 Subscribe", "my": "🔔 Subscribe", "th": "🔔 สมัคร"},
    "btn.settings": {"en": "⚙️ Settings", "my": "⚙️ Settings", "th": "⚙️ ตั้งค่า"},

    # ── Monitor broadcasts ──────────────────────────────────────
    "monitor.api_error": {
        "en": "⚠️ <b>YLG Monitor</b>\nAPI error — could not fetch the price",
        "my": "⚠️ <b>YLG Monitor</b>\nAPI error — ဈေးနှုန်း ယူမရပါ",
        "th": "⚠️ <b>YLG Monitor</b>\nAPI error — ดึงราคาไม่สำเร็จ",
    },
    "monitor.morning": {
        "en": ("🌅 <b>Morning Gold Price</b>\n"
               "📅 {when} (BKK)\n"
               "━━━━━━━━━━━━━━━\n"
               "🥇 <b>99.99% (Pure)</b>\n"
               "  1 baht: {baht_9999}\n"
               "  1g: {gram_9999}\n"
               "🥈 <b>96.50%</b>\n"
               "  1 baht: {baht_9650}\n"
               "  1g: {gram_9650}\n"
               "━━━━━━━━━━━━━━━\n"
               "🌐 Spot     : ${usd_oz}/oz\n"
               "💱 Rate     : 1 USD = {thb_rate} THB\n"
               "⚙️ Alert    : ↓{drop}% drop | ↑{rise}% rise"
               "{extras}\n"
               "━━━━━━━━━━━━━━━\n"
               "✅ Monitoring started!"),
        "my": ("🌅 <b>ရွှေဈေး မနက်ခင်း</b>\n"
               "📅 {when} (BKK)\n"
               "━━━━━━━━━━━━━━━\n"
               "🥇 <b>99.99% (Pure)</b>\n"
               "  ဘတ်သား: {baht_9999}\n"
               "  1g: {gram_9999}\n"
               "🥈 <b>96.50%</b>\n"
               "  ဘတ်သား: {baht_9650}\n"
               "  1g: {gram_9650}\n"
               "━━━━━━━━━━━━━━━\n"
               "🌐 Spot     : ${usd_oz}/oz\n"
               "💱 Rate     : 1 USD = {thb_rate} THB\n"
               "⚙️ Alert    : ↓{drop}% drop | ↑{rise}% rise"
               "{extras}\n"
               "━━━━━━━━━━━━━━━\n"
               "✅ Monitoring စပြီ!"),
        "th": ("🌅 <b>ราคาทองตอนเช้า</b>\n"
               "📅 {when} (BKK)\n"
               "━━━━━━━━━━━━━━━\n"
               "🥇 <b>99.99% (ทองคำแท่ง)</b>\n"
               "  1 บาททอง: {baht_9999}\n"
               "  1 กรัม: {gram_9999}\n"
               "🥈 <b>96.50% (ทองรูปพรรณ)</b>\n"
               "  1 บาททอง: {baht_9650}\n"
               "  1 กรัม: {gram_9650}\n"
               "━━━━━━━━━━━━━━━\n"
               "🌐 Spot     : ${usd_oz}/oz\n"
               "💱 อัตรา    : 1 USD = {thb_rate} THB\n"
               "⚙️ แจ้งเตือน : ↓{drop}% ลง | ↑{rise}% ขึ้น"
               "{extras}\n"
               "━━━━━━━━━━━━━━━\n"
               "✅ เริ่มติดตามแล้ว!"),
    },
    "monitor.trend": {
        "en": "\n📊 Trend: {parts}",
        "my": "\n📊 Trend: {parts}",
        "th": "\n📊 แนวโน้ม: {parts}",
    },
    "monitor.trends": {
        "en": "\n📊 Trends: {parts}",
        "my": "\n📊 Trends: {parts}",
        "th": "\n📊 แนวโน้ม: {parts}",
    },
    "monitor.ta_signal": {
        "en": "\n🎯 Signal: {signal}",
        "my": "\n🎯 Signal: {signal}",
        "th": "\n🎯 สัญญาณ: {signal}",
    },
    "monitor.drop": {
        "en": ("{emoji} <b>{title}!</b>\n"
               "⏰ {when}\n"
               "━━━━━━━━━━━━━━━\n"
               "💰 Now     : {price}/g\n"
               "🌐 Spot    : ${usd_oz}/oz\n"
               "📈 Open    : {open}/g\n"
               "📉 Drop    : {pct:.2f}% (Level {level})\n"
               "⬇️ Day Low : {low}/g"
               "{ta}\n"
               "━━━━━━━━━━━━━━━\n"
               "{advice}\n"
               "📝 Log it with /bought &lt;THB&gt;"),
        "my": ("{emoji} <b>{title}!</b>\n"
               "⏰ {when}\n"
               "━━━━━━━━━━━━━━━\n"
               "💰 လက်ရှိ  : {price}/g\n"
               "🌐 Spot    : ${usd_oz}/oz\n"
               "📈 Open    : {open}/g\n"
               "📉 ကျဆင်းမှု : {pct:.2f}% (Level {level})\n"
               "⬇️ ယနေ့ Low: {low}/g"
               "{ta}\n"
               "━━━━━━━━━━━━━━━\n"
               "{advice}\n"
               "📝 /bought &lt;THB&gt; ဖြင့် မှတ်ပါ"),
        "th": ("{emoji} <b>{title}!</b>\n"
               "⏰ {when}\n"
               "━━━━━━━━━━━━━━━\n"
               "💰 ตอนนี้   : {price}/g\n"
               "🌐 Spot    : ${usd_oz}/oz\n"
               "📈 เปิด     : {open}/g\n"
               "📉 ลดลง    : {pct:.2f}% (ระดับ {level})\n"
               "⬇️ ต่ำสุดวันนี้: {low}/g"
               "{ta}\n"
               "━━━━━━━━━━━━━━━\n"
               "{advice}\n"
               "📝 บันทึกด้วย /bought &lt;THB&gt;"),
    },
    "monitor.rise": {
        "en": ("{emoji} <b>{title}!</b>\n"
               "⏰ {when}\n"
               "━━━━━━━━━━━━━━━\n"
               "💰 Now      : {price}/g\n"
               "🌐 Spot     : ${usd_oz}/oz\n"
               "📈 Open     : {open}/g\n"
               "🚀 Rise     : +{pct:.2f}% (Level {level})\n"
               "⬆️ Day High : {high}/g"
               "{ta}\n"
               "━━━━━━━━━━━━━━━\n"
               "{advice}"),
        "my": ("{emoji} <b>{title}!</b>\n"
               "⏰ {when}\n"
               "━━━━━━━━━━━━━━━\n"
               "💰 လက်ရှိ  : {price}/g\n"
               "🌐 Spot    : ${usd_oz}/oz\n"
               "📈 Open    : {open}/g\n"
               "🚀 တက်မှု   : +{pct:.2f}% (Level {level})\n"
               "⬆️ ယနေ့ High: {high}/g"
               "{ta}\n"
               "━━━━━━━━━━━━━━━\n"
               "{advice}"),
        "th": ("{emoji} <b>{title}!</b>\n"
               "⏰ {when}\n"
               "━━━━━━━━━━━━━━━\n"
               "💰 ตอนนี้    : {price}/g\n"
               "🌐 Spot     : ${usd_oz}/oz\n"
               "📈 เปิด      : {open}/g\n"
               "🚀 เพิ่มขึ้น  : +{pct:.2f}% (ระดับ {level})\n"
               "⬆️ สูงสุดวันนี้: {high}/g"
               "{ta}\n"
               "━━━━━━━━━━━━━━━\n"
               "{advice}"),
    },
    "monitor.gap": {
        "en": ("🌃 <b>Overnight Gap Down!</b>\n"
               "⏰ {when}\n"
               "━━━━━━━━━━━━━━━\n"
               "💰 Now         : {price}/g\n"
               "🌐 Spot        : ${usd_oz}/oz\n"
               "📕 Prev close  : {prev_close}/g\n"
               "📉 Drop        : {pct:.2f}% (vs yesterday's close)\n"
               "⬇️ Day Low     : {low}/g"
               "{ta}\n"
               "━━━━━━━━━━━━━━━\n"
               "👉 Overnight dip — check for a DCA opportunity!\n"
               "📝 Log it with /bought &lt;THB&gt;"),
        "my": ("🌃 <b>ည/အိပ်ရာထ ဈေးကျ (Gap Down)!</b>\n"
               "⏰ {when}\n"
               "━━━━━━━━━━━━━━━\n"
               "💰 လက်ရှိ   : {price}/g\n"
               "🌐 Spot     : ${usd_oz}/oz\n"
               "📕 မနေ့ပိတ် : {prev_close}/g\n"
               "📉 ကျဆင်းမှု : {pct:.2f}% (မနေ့ပိတ်ဈေးနှင့်)\n"
               "⬇️ ယနေ့ Low : {low}/g"
               "{ta}\n"
               "━━━━━━━━━━━━━━━\n"
               "👉 ည/နံနက်ပိုင်း ဈေးကျ — DCA အခွင့်အရေး စစ်ပါ!\n"
               "📝 /bought &lt;THB&gt; ဖြင့် မှတ်ပါ"),
        "th": ("🌃 <b>ราคาลงข้ามคืน (Gap Down)!</b>\n"
               "⏰ {when}\n"
               "━━━━━━━━━━━━━━━\n"
               "💰 ตอนนี้      : {price}/g\n"
               "🌐 Spot       : ${usd_oz}/oz\n"
               "📕 ปิดเมื่อวาน : {prev_close}/g\n"
               "📉 ลดลง       : {pct:.2f}% (เทียบราคาปิดเมื่อวาน)\n"
               "⬇️ ต่ำสุดวันนี้ : {low}/g"
               "{ta}\n"
               "━━━━━━━━━━━━━━━\n"
               "👉 ราคาลงช่วงกลางคืน — พิจารณาโอกาส DCA!\n"
               "📝 บันทึกด้วย /bought &lt;THB&gt;"),
    },
    "monitor.evening": {
        "en": ("🌙 <b>Evening Gold Summary</b>\n"
               "📅 {when}\n"
               "━━━━━━━━━━━━━━━\n"
               "💰 Now      : {price}/g\n"
               "📊 Open     : {open}/g\n"
               "{arrow} Today       : {change:+.2f}%\n"
               "⬆️ Day High  : {high}/g\n"
               "⬇️ Day Low   : {low}/g\n"
               "🌐 Spot: ${usd_oz}/oz"
               "{extras}\n"
               "━━━━━━━━━━━━━━━"),
        "my": ("🌙 <b>ညနေ ရွှေဈေး အနှစ်ချုပ်</b>\n"
               "📅 {when}\n"
               "━━━━━━━━━━━━━━━\n"
               "💰 ယခု      : {price}/g\n"
               "📊 Open     : {open}/g\n"
               "{arrow} ယနေ့ change : {change:+.2f}%\n"
               "⬆️ Day High  : {high}/g\n"
               "⬇️ Day Low   : {low}/g\n"
               "🌐 Spot: ${usd_oz}/oz"
               "{extras}\n"
               "━━━━━━━━━━━━━━━"),
        "th": ("🌙 <b>สรุปราคาทองตอนเย็น</b>\n"
               "📅 {when}\n"
               "━━━━━━━━━━━━━━━\n"
               "💰 ตอนนี้     : {price}/g\n"
               "📊 เปิด       : {open}/g\n"
               "{arrow} วันนี้        : {change:+.2f}%\n"
               "⬆️ สูงสุดวันนี้ : {high}/g\n"
               "⬇️ ต่ำสุดวันนี้ : {low}/g\n"
               "🌐 Spot: ${usd_oz}/oz"
               "{extras}\n"
               "━━━━━━━━━━━━━━━"),
    },
    "monitor.portfolio": {
        "en": ("\n\n💼 <b>Portfolio:</b>\n"
               "  ⚖️ {grams:.4f}g ({buys} buys)\n"
               "  {emoji} P&amp;L: {pnl} ({pct:+.2f}%)"),
        "my": ("\n\n💼 <b>Portfolio:</b>\n"
               "  ⚖️ {grams:.4f}g ({buys} buys)\n"
               "  {emoji} P&amp;L: {pnl} ({pct:+.2f}%)"),
        "th": ("\n\n💼 <b>พอร์ต:</b>\n"
               "  ⚖️ {grams:.4f}g ({buys} ครั้ง)\n"
               "  {emoji} กำไร/ขาดทุน: {pnl} ({pct:+.2f}%)"),
    },
    "monitor.streak_up": {
        "en": "\n🔥 {hours}h consecutive rise",
        "my": "\n🔥 {hours}h consecutive rise",
        "th": "\n🔥 ขึ้นต่อเนื่อง {hours} ชม.",
    },
    "monitor.streak_down": {
        "en": "\n🔥 {hours}h consecutive decline",
        "my": "\n🔥 {hours}h consecutive decline",
        "th": "\n🔥 ลงต่อเนื่อง {hours} ชม.",
    },
    "monitor.outlook": {
        "en": "\n🔮 Tomorrow: {outlook}",
        "my": "\n🔮 Tomorrow: {outlook}",
        "th": "\n🔮 พรุ่งนี้: {outlook}",
    },
    "monitor.hit_rate": {
        "en": "\n🎯 ML live hit-rate: {parts}",
        "my": "\n🎯 ML live hit-rate: {parts}",
        "th": "\n🎯 ความแม่นยำ ML จริง: {parts}",
    },
    "monitor.level_alert": {
        "en": ("🎯 <b>Price Alert Hit!</b>\n"
               "⏰ {when}\n"
               "━━━━━━━━━━━━━━━\n"
               "{arrow} Target : {dir} {target}/g\n"
               "💰 Now    : {price}/g\n"
               "━━━━━━━━━━━━━━━\n"
               "ℹ️ This alert was removed automatically — set a new one with /alert"),
        "my": ("🎯 <b>Price Alert ထိပြီ!</b>\n"
               "⏰ {when}\n"
               "━━━━━━━━━━━━━━━\n"
               "{arrow} သတ်မှတ်ချက်: {dir} {target}/g\n"
               "💰 လက်ရှိဈေး : {price}/g\n"
               "━━━━━━━━━━━━━━━\n"
               "ℹ️ ဤ alert ကို auto ဖျက်ပြီးပါပြီ — /alert ဖြင့် အသစ်သတ်မှတ်နိုင်ပါသည်"),
        "th": ("🎯 <b>ถึงราคาที่ตั้งไว้แล้ว!</b>\n"
               "⏰ {when}\n"
               "━━━━━━━━━━━━━━━\n"
               "{arrow} เป้าหมาย : {dir} {target}/g\n"
               "💰 ตอนนี้   : {price}/g\n"
               "━━━━━━━━━━━━━━━\n"
               "ℹ️ ลบการแจ้งเตือนนี้อัตโนมัติแล้ว — ตั้งใหม่ด้วย /alert"),
    },
    "monitor.weekly": {
        "en": ("\n\n📅 <b>Weekly Recap (7d)</b>\n"
               "  {arrow} Week: {change:+.2f}% ({open} → {close})\n"
               "  ⬆️ High: {high} | ⬇️ Low: {low}\n"
               "  🏆 Best day: {best_day} ({best:+.2f}%)\n"
               "  💔 Worst day: {worst_day} ({worst:+.2f}%)"),
        "my": ("\n\n📅 <b>သီတင်းပတ် အနှစ်ချုပ် (7d)</b>\n"
               "  {arrow} Week: {change:+.2f}% ({open} → {close})\n"
               "  ⬆️ High: {high} | ⬇️ Low: {low}\n"
               "  🏆 Best day: {best_day} ({best:+.2f}%)\n"
               "  💔 Worst day: {worst_day} ({worst:+.2f}%)"),
        "th": ("\n\n📅 <b>สรุปรายสัปดาห์ (7 วัน)</b>\n"
               "  {arrow} สัปดาห์: {change:+.2f}% ({open} → {close})\n"
               "  ⬆️ สูงสุด: {high} | ⬇️ ต่ำสุด: {low}\n"
               "  🏆 วันที่ดีที่สุด: {best_day} ({best:+.2f}%)\n"
               "  💔 วันที่แย่ที่สุด: {worst_day} ({worst:+.2f}%)"),
    },
    "monitor.crash": {
        "en": ("🛑 <b>Gold Monitor crashed</b>\n"
               "<code>{error}</code>\n"
               "Check GitHub Actions logs."),
        "my": ("🛑 <b>Gold Monitor crashed</b>\n"
               "<code>{error}</code>\n"
               "Check GitHub Actions logs."),
        "th": ("🛑 <b>Gold Monitor ล่ม</b>\n"
               "<code>{error}</code>\n"
               "ตรวจสอบ log ของ GitHub Actions"),
    },

    # ── Drop / rise alert titles and advice ─────────────────────
    "drop.1.title": {
        "en": "Gold price falling", "my": "ရွှေဈေး ကျဆင်း", "th": "ราคาทองลดลง",
    },
    "drop.1.advice": {
        "en": "👉 Open YLG Get Gold and buy!",
        "my": "👉 YLG Get Gold ဖွင့်ဝယ်ပါ!",
        "th": "👉 เปิด YLG Get Gold แล้วซื้อเลย!",
    },
    "drop.2.title": {
        "en": "Gold price still falling", "my": "ရွှေဈေး ဆက်ကျဆင်း", "th": "ราคาทองลดลงต่อ",
    },
    "drop.2.advice": {
        "en": "💡 Consider a DCA buy!", "my": "💡 DCA ဝယ်ရန် စဉ်းစားပါ!",
        "th": "💡 พิจารณาซื้อแบบ DCA!",
    },
    "drop.3.title": {
        "en": "Gold price down sharply", "my": "ရွှေဈေး ကြီးစွာ ကျဆင်း", "th": "ราคาทองลดลงมาก",
    },
    "drop.3.advice": {
        "en": "🔥 Good chance to add to your DCA!",
        "my": "🔥 DCA ထပ်ဝယ်ရန် အခွင့်ကောင်း!",
        "th": "🔥 โอกาสดีที่จะ DCA เพิ่ม!",
    },
    "drop.4.title": {
        "en": "Gold price down severely", "my": "ရွှေဈေး ပြင်းထန်စွာ ကျ", "th": "ราคาทองดิ่งแรง",
    },
    "drop.4.advice": {
        "en": "⚠️ Be careful, but consider a DCA buy!",
        "my": "⚠️ သတိထားပြီး DCA စဉ်းစားပါ!",
        "th": "⚠️ ระวัง แต่พิจารณา DCA ได้!",
    },
    "drop.5.title": {
        "en": "Gold price crashing", "my": "ရွှေဈေး အကြီးအကျယ် ကျဆင်း", "th": "ราคาทองดิ่งหนัก",
    },
    "drop.5.advice": {
        "en": "🏦 Urgent — review your portfolio!",
        "my": "🏦 အရေးပေါ် — portfolio စစ်ဆေးပါ!",
        "th": "🏦 เร่งด่วน — ตรวจสอบพอร์ตของคุณ!",
    },
    "rise.1.title": {
        "en": "Gold price is rising", "my": "ရွှေဈေး တက်နေပါတယ်", "th": "ราคาทองกำลังขึ้น",
    },
    "rise.1.advice": {
        "en": "💎 Your portfolio value is up!",
        "my": "💎 Portfolio တန်ဖိုး တက်နေပါပြီ!",
        "th": "💎 มูลค่าพอร์ตของคุณเพิ่มขึ้นแล้ว!",
    },
    "rise.2.title": {
        "en": "Gold price keeps rising", "my": "ရွှေဈေး ဆက်တက်နေတယ်", "th": "ราคาทองขึ้นต่อ",
    },
    "rise.2.advice": {
        "en": "📊 Consider taking profit!", "my": "📊 Profit ယူရန် စဉ်းစားပါ!",
        "th": "📊 พิจารณาขายทำกำไร!",
    },
    "rise.3.title": {
        "en": "Gold price up sharply", "my": "ရွှေဈေး ကြီးစွာ တက်", "th": "ราคาทองขึ้นมาก",
    },
    "rise.3.advice": {
        "en": "💰 Consider taking partial profit!",
        "my": "💰 Partial profit ယူရန် စဉ်းစားပါ!",
        "th": "💰 พิจารณาขายทำกำไรบางส่วน!",
    },
    "rise.4.title": {
        "en": "Gold price up steeply", "my": "ရွှေဈေး ပြင်းထန်စွာ တက်", "th": "ราคาทองพุ่งแรง",
    },
    "rise.4.advice": {
        "en": "⚡ Price is high — take profit!", "my": "⚡ ဈေးမြင့်ချိန် — profit ယူပါ!",
        "th": "⚡ ราคาสูง — ขายทำกำไร!",
    },
    "rise.5.title": {
        "en": "Gold price surging", "my": "ရွှေဈေး အကြီးအကျယ် တက်", "th": "ราคาทองพุ่งทะยาน",
    },
    "rise.5.advice": {
        "en": "🏆 Big gain — consider selling!", "my": "🏆 အမြတ်ကြီး — sell စဉ်းစားပါ!",
        "th": "🏆 กำไรมาก — พิจารณาขาย!",
    },

    # ── Technical-analysis outlooks (/predict) ──────────────────
    "ta.strong_buy": {
        "en": "🟢 STRONG BUY — oversold, the best time to buy",
        "my": "🟢 STRONG BUY — ဈေး oversold ဖြစ်နေ၊ ဝယ်ရန် အကောင်းဆုံးအချိန်",
        "th": "🟢 STRONG BUY — ขายมากเกินไป เป็นจังหวะซื้อที่ดีที่สุด",
    },
    "ta.buy": {
        "en": "🟡 BUY — price is dipping, consider buying",
        "my": "🟡 BUY — ဈေးကျနေ၊ ဝယ်ရန် စဉ်းစားပါ",
        "th": "🟡 BUY — ราคาย่อลง พิจารณาซื้อ",
    },
    "ta.hold": {
        "en": "⚪ HOLD — price is stable, keep watching",
        "my": "⚪ HOLD — ဈေးတည်ငြိမ်နေ၊ စောင့်ကြည့်ပါ",
        "th": "⚪ HOLD — ราคานิ่ง เฝ้าดูต่อไป",
    },
    "ta.wait": {
        "en": "🟠 WAIT — price is rising, not a good entry yet",
        "my": "🟠 WAIT — ဈေးတက်နေ၊ ဝယ်ဖို့ မသင့်သေး",
        "th": "🟠 WAIT — ราคากำลังขึ้น ยังไม่ควรซื้อ",
    },
    "ta.overbought": {
        "en": "🔴 OVERBOUGHT — price is very high, do not buy",
        "my": "🔴 OVERBOUGHT — ဈေးအလွန်မြင့်နေ၊ မဝယ်သင့်",
        "th": "🔴 OVERBOUGHT — ราคาสูงมาก ไม่ควรซื้อ",
    },
    "ta.no_edge": {
        "en": ("⚠️ ML models show no historical edge over a coin-flip — "
               "treat ML as noise; rely on the TA signal below"),
        "my": ("⚠️ ML models show no historical edge over a coin-flip — "
               "treat ML as noise; rely on the TA signal below"),
        "th": ("⚠️ โมเดล ML ไม่มีความได้เปรียบเหนือการเดาสุ่ม — "
               "ถือว่าเป็น noise ให้ดูสัญญาณ TA ด้านล่างแทน"),
    },
    "ta.bullish": {
        "en": "ML models (with edge) lean BULLISH",
        "my": "ML models (with edge) lean BULLISH",
        "th": "โมเดล ML (ที่มี edge) เอนไปทาง BULLISH",
    },
    "ta.bearish": {
        "en": "ML models (with edge) lean BEARISH — consider buying",
        "my": "ML models (with edge) lean BEARISH — consider buying",
        "th": "โมเดล ML (ที่มี edge) เอนไปทาง BEARISH — พิจารณาซื้อ",
    },
    "ta.mixed": {
        "en": "ML models (with edge) are MIXED",
        "my": "ML models (with edge) are MIXED",
        "th": "โมเดล ML (ที่มี edge) ให้ผลผสม",
    },
}


def t(key: str, lang: str | None = None, /, **params) -> str:
    """Render `key` in `lang`, falling back to the default language.

    `key` and `lang` are positional-only so that **params can use ANY name —
    including "lang" and "key", which several strings legitimately need as
    placeholders. Without that, `t("lang.ok", code, lang=...)` would raise
    "got multiple values for argument 'lang'".

    An unknown key returns the key itself rather than raising — a missing
    string should degrade to something inspectable in Telegram, never take
    down a scheduled broadcast. A test asserts the catalogue is complete.
    """
    entry = STRINGS.get(key)
    if entry is None:
        return key
    code = normalize(lang)
    text = entry.get(code) or entry.get(DEFAULT_LANG) or key
    if not params:
        return text
    try:
        return text.format(**params)
    except (KeyError, IndexError, ValueError) as e:
        print(f"[i18n] format failed for {key!r}/{code}: {e}")
        return text
