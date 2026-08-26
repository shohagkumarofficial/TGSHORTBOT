# 🎮 Telegram Mini App Game Bot (Multi-Game Life System & Ad Monetization)

A full-featured Telegram Mini App (Web App) game hub powered by **Python FastAPI**, **aiogram 3.x**, **SQLite (async via aiosqlite)**, and **HTML5/CSS/JS** games.

---

## 🌟 Features

### 🕹️ 6 Standalone Casual Games
1. **🐍 Snake Classic**: Canvas snake with food particles, swipe and on-screen D-pad.
2. **🔢 2048 Puzzle**: 4x4 sliding grid puzzle with merge animations.
3. **🕊️ Flappy Bird**: Physics-based jumping bird with gravity and obstacles.
4. **❌ Tic Tac Toe**: Single-player vs AI (Easy, Medium, Master with Minimax algorithm).
5. **🧠 Memory Match**: 4x4 card grid with emoji pairs and move counter.
6. **🔨 Whack-a-Mole**: 9-hole arcade board with combos and 30s timer.

### ❤️ 3-Life & Energy System
- Starting lives: 3 (Cap: 3, configurable by admin).
- 1 life consumed on game over or game start (admin toggleable).
- Auto-regeneration timer (e.g. +1 life every 30 minutes).
- Rewarded Video Ads (Adsgram & Monetag) to immediately refill +1 life with anti-spam cooldown protection.

### 👑 Telegram In-Bot Admin Panel (`/admin`)
- Accessible only by `OWNER_TELEGRAM_ID`.
- ⚙️ **Ad Config**: Switch active ad network (Adsgram / Monetag / Both), edit Block ID / Zone ID.
- 🎮 **Game Manager**: Real-time toggle to enable/disable any game.
- ❤️ **Life Settings**: Adjust default lives, max capacity, regen interval, and deduct rules.
- 📊 **Analytics Dashboard**: Total users, DAU (24h), game play counts, ad impression statistics.
- 📢 **Broadcast Engine**: Send broadcast announcements to all registered users with live delivery stats.

---

## 🚀 Render Deployment Setup

This project is tailored for **Render Web Service**:

1. **Build Command**:
   ```bash
   pip install -r requirements.txt
   ```
2. **Start Command**:
   ```bash
   uvicorn app:app --host 0.0.0.0 --port $PORT
   ```
3. **Environment Variables Configured in Render**:
   - `BOT_TOKEN`: Telegram bot token from [@BotFather](https://t.me/BotFather)
   - `BOT_USERNAME`: Bot username (without `@`)
   - `OWNER_TELEGRAM_ID`: Your numerical Telegram user ID
   - `WEBAPP_BASE_URL`: Render app public URL (e.g. `https://your-app.onrender.com`)
   - `WEBHOOK_URL`: Render app public URL (e.g. `https://your-app.onrender.com`)
   - `ADSGRAM_BLOCK_ID`: Adsgram Block ID (e.g. `int-4166`)
   - `MONETAG_ZONE_ID`: (Optional) Monetag Zone ID

---

## 💻 Local Development & Testing

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Run server locally:
   ```bash
   python -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload
   ```
3. Open browser at `http://127.0.0.1:8000` to test the Mini App Game Hub directly!
