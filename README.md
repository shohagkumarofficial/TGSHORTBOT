# TGSHORTBOT

Telegram ad-locked URL shortener + earning platform. Built per
`TGSHORTBOT_PRD-1.md`. MVP scope — JSON-backed storage, Render free-tier
hosting, single bot + web service in one process.

## Stack

- **aiogram 3.x** — Telegram bot (webhook mode)
- **FastAPI + uvicorn** — webhook receiver, Mini App API, viewer entry
- **pydantic v2** — models
- **JSON file** — storage (MVP). SQLite swap is mechanical behind the
  `storage.py` interface.
- **Single-file HTML** — Mini App frontend (no build step), Telegram
  WebApp JS SDK + Adsgram JS SDK

## Project layout

```
tgshortbot/
├── bot.py          # aiogram commands + reply keyboard
├── app.py          # FastAPI: webhook + Mini App API
├── runner.py       # ASGI entry point for uvicorn / Render
├── config.py       # env loading
├── storage.py      # JSON-backed data layer
├── models.py       # pydantic models
├── cpm_engine.py   # realtime vs scheduled CPM + cycle tick
├── webapp/
│   ├── viewer.html # 3-ad lock screen → redirect
│   └── panel.html  # admin/owner dashboard
├── data/
│   └── store.json  # created at runtime (mounted as disk in Render)
├── requirements.txt
├── render.yaml     # Render Blueprint
└── .env.example
```

## Local run

```bash
cp .env.example .env       # fill in BOT_TOKEN, OWNER_TELEGRAM_ID, etc.
pip install -r requirements.txt
# expose port 10000 to a public URL (ngrok, etc.) and set WEBHOOK_URL
uvicorn runner:app --host 0.0.0.0 --port 10000
```

## Deploy to Render

1. Push the `tgshortbot/` directory to a GitHub repo.
2. In Render dashboard → **New → Blueprint** → pick the repo. Render
   reads `render.yaml` and provisions the free web service.
3. After first deploy, copy the public URL (e.g.
   `https tgshortbot.onrender.com`) and set in the service's env:
   - `WEBHOOK_URL` = `https://tgshortbot.onrender.com/webhook`
   - `WEBAPP_BASE_URL` = `https://tgshortbot.onrender.com`
   - `BOT_TOKEN` from BotFather
   - `OWNER_TELEGRAM_ID` (your numeric Telegram ID — get it from
     `@userinfobot`)
   - `ADSGRAM_BLOCK_ID` from the Adsgram dashboard
4. Restart the service. The webhook registers itself on startup.
5. Open the bot in Telegram → `/start` → use the on-screen keyboard.

## Free-tier sleep protection

`/health` returns 200 + nudges any due CPM cycle. Hit it every 5–10
minutes from an external cron (e.g. UptimeRobot) to keep Render awake.

## Build order (mirrors PRD §9.6)

1. ✅ `config.py` + `storage.py` + `models.py`
2. ✅ `bot.py` — `/start`, `/newlink`, `/mybalance`, `/withdraw`, `/mylinks`, `/myproof`
3. ✅ `app.py` — webhook + `/r/{code}` + viewer API
4. ✅ `webapp/viewer.html` — ad-lock → redirect
5. ✅ admin API + `webapp/panel.html` (sub-admin + owner)
6. ✅ CPM engine + scheduled cycle job
7. ✅ Withdrawal flow end-to-end
8. ⏭ Deploy to Render, verify health-check, test live with Adsgram test block

## Security

- Every Mini App API call validates Telegram's `initData` signature
  server-side (HMAC-SHA256 against `BOT_TOKEN`). The bot never trusts a
  client-supplied `telegram_id`.
- Monetary calculations live only in `cpm_engine.py` / `storage.py`.
  The Mini App never tells the server how much to credit — it just
  reports a completed 3-ad viewing.

## MVP scope boundaries

No DB persistence, manual proof verification, single global CPM mode,
bKash/Nagad only. See PRD §7.
