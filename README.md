# 🥇 YLG Gold Price Monitor

ရွှေဈေး ကျဆင်းတဲ့အချိန် LINE Notify ဖြင့် အလိုအလျောက် သတိပေးသည့် bot
GitHub Actions + Python ဖြင့် build ထားသည် — **ကုန်ကျငွေ $0**

---

## 📲 LINE မှာ ရမည့် message မျိုးများ

| အချိန် | Message |
|---|---|
| မနက် (first run) | 🌅 Open ဈေး + monitoring စပြီ |
| ဈေး threshold% ကျရင် | 🟡 ဝယ်သင့်တဲ့ alert |
| ဈေး 1.5x threshold ကျရင် | 🔴 ကြီးစွာ ကျဆင်း alert |
| ညနေ 8–9pm | 🌙 ယနေ့ summary |

---

## ⚙️ Setup (တစ်ခါတည်း လုပ်ရမည်)

### Step 1 — GitHub Repo

```bash
# Repo အသစ် create လုပ်ပြီး ဒီ file တွေ push လုပ်ပါ
git init
git add .
git commit -m "Gold monitor setup"
git remote add origin https://github.com/YOUR_USERNAME/gold-monitor.git
git push -u origin main
```

### Step 2 — LINE Notify Token ယူပါ

1. https://notify-bot.line.me/my ဖွင့်ပါ
2. **"Generate token"** နှိပ်ပါ
3. Token name: `Gold Monitor`
4. Chat ရွေး — ကိုယ်တိုင်ကိုပဲ ပို့ချင်ရင် **"1-on-1 chat with LINE Notify"** ရွေးပါ
5. Token ကို copy ပါ (တစ်ကြိမ်သာ ပြပါသည်)

### Step 3 — GitHub Secret ထည့်ပါ

GitHub repo → **Settings** → **Secrets and variables** → **Actions**

| Name | Value |
|---|---|
| `LINE_NOTIFY_TOKEN` | Step 2 မှ ရလာသော token |

### Step 4 — Alert % ပြောင်းချင်ရင် (optional)

GitHub repo → **Settings** → **Secrets and variables** → **Actions** → **Variables**

| Name | Default | ဆိုလိုတာ |
|---|---|---|
| `DROP_THRESHOLD` | `0.5` | 0.5% ကျမှ notify |

ပိုစောစော alert ချင်ရင် `0.3` ထားပါ
ပိုကျမှ alert ချင်ရင် `1.0` ထားပါ

### Step 5 — Test run

GitHub repo → **Actions** → **Gold Price Monitor** → **Run workflow**

LINE မှာ message ရောက်ရင် ✅ setup မှန်ပါပြီ

---

## 🕐 Run ချိန်

| ရက် | UTC | Bangkok |
|---|---|---|
| တနင်္လာ–သောကြာ | 1am–5pm | 8am–midnight |
| စနေ | 3am–10am | 10am–5pm |
| တနင်္ဂနွေ | မ run ပါ | — |

---

## 📁 Files

```
gold-monitor/
├── gold_monitor.py              # Main script
├── .github/
│   └── workflows/
│       └── gold_monitor.yml     # GitHub Actions schedule
└── README.md
```

---

## ❓ FAQ

**Q: ဈေးဒေတာ accuracy ကောင်းလား?**
A: metals.live (primary) + Yahoo Finance (fallback) နှစ်ခုသုံးသည် — international spot ဈေးဖြစ်သောကြောင့် YLG ဈေးနှင့် ฿100-200 ကွာနိုင်သည်။ Trend ကို ကြည့်ရတာ ရည်ရွယ်ချက်ဖြစ်သည်။

**Q: Auto-buy လုပ်မပေးနိုင်ဘူးလား?**
A: YLG app ကိုယ်တိုင် API ဖော်ပြမသည်ကြောင့် auto-buy မဖြစ်နိုင်ပါ — alert ရပြီး ကိုယ်တိုင်ဆုံးဖြတ်ရမည်။

**Q: ငွေကုန်မလား?**
A: GitHub Actions free tier (2,000 min/month) — ဒီ bot က တစ်လ ~300 min သာ သုံးသည်။ ✅ Free

**Q: Alert ပိုများလွန်းနေရင်?**
A: `DROP_THRESHOLD` variable ကို `1.0` သို့မဟုတ် `1.5` ပြောင်းပါ

---

*Built with GitHub Actions + Python + LINE Notify*
