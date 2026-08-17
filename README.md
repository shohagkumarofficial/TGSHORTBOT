# TGSHORTBOT

A Telegram-based, ad-locked URL shortener and earning platform. Admins
shorten links, share them, and earn money whenever a viewer watches 3
rewarded ads (via Adsgram) before being redirected to the destination URL.
The Owner controls CPM economics, reviews each Admin's Traffic Source, and
pays out via bKash/Nagad.

Built from the PRD in `TGSHORTBOT_PRD.md`, following the build order in
Section 9.6.

## Project structure

```
tgshortbot/
├── bot.py               # aiogram bot: commands, conversational flows
├── app.py                # FastAPI: webhook, redirect route, Mini App API
├── config.py              # environment variable loading
├── storage.py              # JSON-backed data layer (async, atomic writes)
├── models.py                # pydantic data models (Admin, Link, View, ...)
├── cpm_engine.py             # real-time + scheduled CPM crediting logic
├── telegram_auth.py           # Telegram Mini App initData signature check
├── webapp/
│   ├── viewer.html             # ad-lock → redirect Mini App
│   └── panel.html               # admin/owner dashboard Mini App
├── scripts/
│   └── set_webhook.py            # manual webhook set/delete/info helper
├── requirements.txt
├── render.yaml
├── .env.example
└── README.md
```

`data/store.json` is created automatically on first run — it isn't
committed, so there's nothing to conflict with in version control.

## How the core pieces fit together

- **Roles** (Section 2): the first person to `/start` the bot whose
  Telegram ID matches `OWNER_TELEGRAM_ID` becomes Owner; everyone else
  becomes an Admin automatically, with a ৳0 starting balance.
- **Traffic Sources** (at least one required before creating links): each
  Admin can add any number of sources — a platform (Telegram/YouTube/
  Facebook/TikTok/Other) plus a link to their own channel/group/profile —
  via `/trafficsource` in the bot or the panel's "Traffic Sources" tab,
  and can add, edit, or remove any of them at any time. `POST /api/links`
  and the bot's `/newlink` both refuse to create a link until at least
  one exists — it's the Owner's main signal for where traffic is
  actually coming from.
- **Link creation** (4.1): `/newlink <url>` or the panel's "Create a short
  link" form generates a short code. The link shown to the Admin is a
  real Telegram deep link — `https://t.me/<BOT_USERNAME>?start=<code>` —
  so clicking it always opens Telegram and triggers the bot, rather than
  a bare HTTPS URL that might open in a plain browser with no Telegram
  context.
- **Viewer flow** (4.2): the deep link opens the bot, which replies with
  a WebApp button pointing at `/r/{code}` — a Telegram Mini App
  (`webapp/viewer.html`) that runs 3 sequential Adsgram ads, then calls
  `POST /api/log-view`, then `GET /api/link/{code}`, then redirects.
- **Fraud/dedupe** (4.3): one countable view per `(short_code, viewer)`
  pair, enforced atomically in `storage.create_view`.
- **CPM engine** (4.5 / 9.5): `cpm_engine.py` handles both modes.
  Real-time credits `balance_confirmed` the instant a view is logged.
  Scheduled holds views as `pending_payout`; a background watcher
  (started in `app.py`'s lifespan) closes each cycle when its duration
  elapses and applies whatever rate is active *at that exact moment* to
  every view from the whole period — no retroactive rate-splitting.
- **Withdrawals** (4.6): Admin requests from confirmed balance. The
  account number is validated server-side as a real 11-digit bKash/Nagad
  mobile number (`01[3-9]XXXXXXXX`, with `+880`/spaces/dashes normalized
  away) before the request is even created — both the bot and the panel
  reject an invalid number with an inline error instead of silently
  accepting free-form text. The moment a valid request is made — from
  the bot or the panel — the Owner gets a Telegram DM with the amount,
  method, account number, and links to every one of the requester's
  Traffic Sources, plus a button into the panel. Owner marks
  Paid/Rejected in the panel's Withdrawals queue; balance is only
  deducted on Paid. The moment the Owner resolves it, the *requesting*
  Admin gets a Telegram DM back — confirming the payment (and account
  it was sent to) on Paid, or the reason on Rejected — so they know
  their money is on its way without having to re-check the panel.

## Dashboard layout

The Owner and Admin panels are intentionally different, not just
re-skinned:

- **Admin** gets four tabs: Overview, My Links, Traffic Sources, Withdraw
  — everything a single admin needs day to day.
- **Owner** gets a "business snapshot" card (pending withdrawals, total
  admins, current CPM) instead of a personal balance card, and three
  primary tabs: Overview, Withdrawals (the queue, with a badge showing
  the pending count), and Admins (each with all of their Traffic Sources
  visible and a suspend/reactivate toggle). The Owner's own personal
  actions — My Links, Traffic Sources, and Request Withdrawal — are
  listed right on the Overview tab as a simple stacked list, since the
  Owner uses these just like any Admin would. Only genuine platform-level
  configuration —
  CPM Settings and Platform Stats — lives behind the ⚙️ menu at the top
  right, as a bottom-sheet drawer, instead of cluttering the main tab bar.

## Local setup

1. Create a bot with [@BotFather](https://t.me/BotFather) and grab both
   the token and the bot's `@username`.
2. Get your numeric Telegram ID from [@userinfobot](https://t.me/userinfobot)
   — this is your `OWNER_TELEGRAM_ID`.
3. Get an Adsgram block ID from your Adsgram dashboard.
4. Copy `.env.example` to `.env` and fill in the values. For local dev,
   `WEBHOOK_URL`/`WEBAPP_BASE_URL` need to be a publicly reachable HTTPS
   URL (e.g. via `ngrok http 8000`), since Telegram can't call `localhost`
   and Mini Apps must be served over HTTPS.
5. Install dependencies and run:

   ```bash
   pip install -r requirements.txt
   export $(cat .env | xargs)   # or use a tool like direnv/python-dotenv
   uvicorn app:app --reload
   ```

   The webhook is set automatically on startup. If it fails (e.g. no
   public URL yet), set it manually once you have one:

   ```bash
   python -m scripts.set_webhook set
   ```

6. Message your bot `/start` from your Owner account, then `/newlink` to
   try the full loop.

## Deploying to Render

`render.yaml` is ready to use as-is:

1. Push this repo to GitHub/GitLab.
2. In Render, "New +" → "Blueprint", point it at the repo — it will read
   `render.yaml` and provision the web service.
3. Fill in the marked-`sync: false` environment variables in Render's
   dashboard (`BOT_TOKEN`, `BOT_USERNAME`, `WEBHOOK_URL`, `WEBHOOK_SECRET`,
   `ADSGRAM_BLOCK_ID`, `OWNER_TELEGRAM_ID`, `WEBAPP_BASE_URL`) — for
   `WEBHOOK_URL`/`WEBAPP_BASE_URL`, use the `https://<service>.onrender.com`
   URL Render assigns you.
4. Deploy. `GET /health` is wired as the health check, which is what
   keeps a free-tier service from sleeping.
5. Test the full loop: `/start` the bot, `/trafficsource` to set where
   you'll share links, `/newlink`, open the resulting `t.me/...` link,
   watch the 3 ads, confirm the redirect, then request a withdrawal and
   check it shows up both as a Telegram DM and in the Owner panel.

## Security notes

- Every Mini App API call is authenticated by validating Telegram's
  `initData` HMAC signature server-side (`telegram_auth.py`) — the
  client-supplied Telegram ID is never trusted directly, per the PRD's
  explicit instruction in Section 9.4.
- The `/webhook` endpoint checks Telegram's
  `X-Telegram-Bot-Api-Secret-Token` header against `WEBHOOK_SECRET`
  before processing any update.
- All balance math happens server-side only, inside `storage.py` and
  `cpm_engine.py` — the Mini App frontends never compute or submit a
  balance figure.
- Every CPM change, Traffic Source update, and cycle payout is appended to
  an in-memory + persisted audit log (`cpm_history` in `store.json`).

## Notes on a few implementation decisions

- **Currency display**: the PRD's data model doesn't pin down a currency
  symbol; since payouts are bKash/Nagad (Bangladeshi mobile payment
  services), the panel and bot display amounts with ৳ (Taka).
- **`CPMSetting.cycle_id`**: not explicitly in the PRD's JSON shape, but
  added so `View.cpm_cycle_id` can unambiguously reference which
  Scheduled-mode cycle a view belongs to, exactly as that field's
  presence in the View model implies it should.
- **Traffic Sources are a list, not a single slot**: an Admin can add,
  edit, or remove any number of sources (platform + link) at any time via
  `/trafficsource` or the panel's Traffic Sources tab, rather than being
  limited to setting one. Views are still credited as soon as they're
  logged; the Owner's oversight happens by inspecting an Admin's full
  list of sources — most visibly right on each withdrawal request —
  rather than approving every individual link. Old `data/store.json`
  files written before this change (a single `traffic_source_platform`/
  `traffic_source_url` pair per Admin) are migrated into a one-item list
  automatically on load, so nothing needs to be done by hand after an
  upgrade.
- **Withdrawal account numbers are validated, not free text**: bKash and
  Nagad personal accounts are both just an 11-digit Bangladeshi mobile
  number (`01` + an operator digit 3-9 + 8 more digits). `validators.py`
  centralizes that check (plus normalizing `+880`/spaces/dashes) so the
  bot's `/withdraw` flow and the panel's withdrawal form enforce the
  exact same rule instead of accepting whatever text was typed into the
  account-number field, which is what happened before this change. An
  invalid number is rejected with an inline error before a request is
  ever created — both in the bot chat and as a popup + red-highlighted
  field in the panel.
- **A few extra API endpoints** beyond a literal reading of the PRD's
  Section 9.4 table were added because the panel Mini App genuinely
  needs them: `GET /api/me`, `GET /api/withdrawals/mine`,
  `GET/POST /api/traffic-sources` + `PUT/DELETE /api/traffic-sources/{id}`,
  and `POST /api/admin/admins/{id}/status` (ban/unban, called out as an
  Owner capability in Section 2).

## Out of scope (unchanged from the PRD)

Database persistence beyond JSON, automated fraud detection beyond the
per-viewer dedupe rule, per-admin CPM mode mixing, withdrawal methods
beyond bKash/Nagad, and exact per-impression Adsgram revenue sync are all
deliberately not implemented here — see Section 7 of the PRD.
