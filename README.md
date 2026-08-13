# TGSHORTBOT — Telegram Ad-Locked URL Shortener & Earning Platform

একটি Telegram-based URL shortener যেখানে Admin-রা লিংক শর্ট করে শেয়ার করে, ভিউয়াররা ৩টি Ad দেখে আসল লিংকে যায়, এবং Admin-রা CPM অনুযায়ী টাকা কামায়।

## 🚀 Quick Setup

### Prerequisites
1. **Telegram Bot Token** — [@BotFather](https://t.me/BotFather) থেকে তৈরি করুন
2. **Your Telegram User ID** — [@userinfobot](https://t.me/userinfobot) থেকে জানুন
3. **Adsgram Block ID** — [adsgram.ai](https://adsgram.ai) থেকে তৈরি করুন
4. **Render Account** — [render.com](https://render.com) এ সাইন আপ করুন

### Local Development

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/tgshortbot.git
cd tgshortbot

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export BOT_TOKEN="your-bot-token"
export OWNER_TELEGRAM_ID="your-telegram-id"
export ADSGRAM_BLOCK_ID="your-block-id"
export WEBAPP_BASE_URL="https://your-app.onrender.com"
export WEBHOOK_URL="https://your-app.onrender.com/webhook"

# Run
python app.py
```

### Deploy to Render

1. Push code to GitHub
2. Go to [Render Dashboard](https://dashboard.render.com) → New → Web Service
3. Connect your GitHub repo
4. Set the following environment variables:

| Variable | Value |
|---|---|
| `BOT_TOKEN` | Your Telegram bot token |
| `WEBHOOK_URL` | `https://YOUR-APP.onrender.com/webhook` |
| `ADSGRAM_BLOCK_ID` | Your Adsgram block ID |
| `OWNER_TELEGRAM_ID` | Your Telegram numeric user ID |
| `WEBAPP_BASE_URL` | `https://YOUR-APP.onrender.com` |

5. Deploy!

## 📂 Project Structure

```
tgshortbot/
├── bot.py              # Telegram bot commands (aiogram 3.x)
├── app.py              # FastAPI server (webhook + API + Mini App)
├── config.py           # Environment variable loader
├── models.py           # Pydantic data models
├── storage.py          # JSON-backed storage layer
├── cpm_engine.py       # CPM calculation engine
├── webapp/
│   ├── viewer.html     # Viewer Mini App (3 ads → redirect)
│   └── panel.html      # Admin/Owner Dashboard
├── data/
│   └── store.json      # JSON data store (MVP)
├── requirements.txt
├── render.yaml         # Render deployment config
└── README.md
```

## 🤖 Bot Commands

| Command | Description |
|---|---|
| `/start` | বটে রেজিস্টার হন |
| `/newlink <url>` | নতুন শর্ট লিংক তৈরি করুন |
| `/proof <code> <url>` | প্রুফ URL সাবমিট করুন |
| `/mylinks` | আপনার সব লিংক দেখুন |
| `/mybalance` | ব্যালেন্স দেখুন |
| `/withdraw <bkash/nagad> <number>` | টাকা তোলার রিকোয়েস্ট |
| `/panel` | ড্যাশবোর্ড ওপেন করুন |
| `/help` | সাহায্য |

## 💰 CPM System

- **Real-time Mode**: প্রতিটি verified view-এ সাথে সাথে ব্যালেন্সে জমা হয়
- **Scheduled Mode**: নির্দিষ্ট সময় পর batch-এ সব view-এর টাকা জমা হয়

## 🔒 Security

- Telegram `initData` HMAC-SHA256 validation
- Server-side balance calculations only
- View deduplication (one view per viewer per link)
- Owner-only administrative routes

## License

MIT
