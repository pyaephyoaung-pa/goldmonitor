# 🥇 YLG Gold Price Monitor (Telegram)

ရွှေဈေး ကျဆင်းတဲ့အချိန် **Telegram** ဖြင့် အလိုအလျောက် သတိပေးသည့် bot
GitHub Actions + Python — **ကုန်ကျငွေ $0**

> LINE Notify ကို 2025 မတ်လ 31 ရက်တွင် ပိတ်သိမ်းသွားသောကြောင့် Telegram သို့ ပြောင်းသည်

---

## 📲 Telegram မှာ ရမည့် message မျိုးများ

| အချိန် | Message |
|---|---|
| မနက် (first run) | 🌅 Open ဈေး + monitoring start |
| ဈေး 0.5% ကျ | 🟡 ဝယ်သင့်တဲ့ alert |
| ဈေး 0.75% ကျ | 🔴 ကြီးစွာ ကျဆင်း alert |
| ညနေ 8–9pm | 🌙 ယနေ့ summary |

---

## ⚙️ Setup (တစ်ခါတည်း လုပ်ရမည်)

### Step 1 — Telegram Bot ဆောက်ပါ

1. Telegram မှာ **@BotFather** ကို ရှာဖွင့်ပါ
2. `/newbot` ပို့ပါ
3. Bot name ပေးပါ (ဥပမာ: `My Gold Monitor`)
4. Username ပေးပါ (ဥပမာ: `mygoldmonitor_bot`)
5. **Token** ကို copy ပါ — `123456789:ABCdef...` ပုံစံဖြစ်သည်

### Step 2 — Chat ID ယူပါ

1. Bot နှင့် chat ဖွင့်ပြီး မည်သည့် message မဆို ပေးပို့ပါ
2. Browser မှာ အောက်ပါ URL ဖွင့်ပါ (token ကို ထည့်ပါ)
   ```
   https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   ```
3. JSON response ထဲက `"id"` နံပါတ်ကို copy ပါ — ဒါ Chat ID ဖြစ်သည်

### Step 3 — GitHub Repo ဆောက်ပါ

```bash
git init
git add .
git commit -m "Gold monitor setup"
git remote add origin https://github.com/YOUR_USERNAME/gold-monitor.git
git push -u origin main
```

### Step 4 — GitHub Secrets ထည့်ပါ

GitHub repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

| Secret Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Step 1 မှ bot token |
| `TELEGRAM_CHAT_ID` | Step 2 မှ chat ID |

### Step 5 — Test run

GitHub repo → **Actions** → **Gold Price Monitor** → **Run workflow**

Telegram မှာ 🌅 message ရောက်ရင် ✅ setup မှန်ပြီ

---

## ⚙️ Alert % ပြောင်းချင်ရင်

Settings → Variables → `DROP_THRESHOLD`

| Value | ဆိုလိုတာ |
|---|---|
| `0.3` | 0.3% ကျမှ alert (သိသာကျ) |
| `0.5` | **default** — 0.5% ကျမှ alert |
| `1.0` | 1% ကျမှ alert (ကြီးကြီးကျမှ သိချင်ရင်) |

---

## 📁 Files

```
gold-monitor/
├── gold_monitor.py
├── .github/workflows/gold_monitor.yml
└── README.md
```
