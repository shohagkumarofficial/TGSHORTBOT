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
  pair, enforced atomically in `storage.create_view`. On top of that, an
  **Anti-Abuse System** caps how many views a single viewer can have
  *credited* against one Admin's links per day
  (`CPMSetting.max_daily_views_per_admin`, Owner-only, set from the
  panel's CPM Settings drawer, default `0` = no cap): once a viewer
  crosses it, `cpm_engine.credit_new_view` still lets every further view
  play its ads and reach the destination as normal, it just stops adding
  to that Admin's balance (the `View` row is flagged `daily_capped`
  instead), so a viewer re-opening many of one Admin's links in a day
  can't keep dragging that Admin's CPM down. **Missed Earnings
  Analytics** (`storage.missed_earnings_trend` /
  `missed_earnings_by_link` / `suggested_daily_limit`, folded into the
  existing `platform_stats`/`admin_stats` payloads) turns the raw
  `daily_capped_views` counter into something actionable: a 14-day daily
  trend (so the Owner can see whether capped views are climbing or just
  had a one-off spike, on both the platform-wide Stats tab and each
  Admin's detail view), a link-wise breakdown ranking which *specific*
  links are absorbing the abuse instead of only an Admin-level total,
  and a "suggested limit" that looks at the trailing 14 days of
  per-viewer-per-day activity and proposes a `max_daily_views_per_admin`
  around the 90th percentile — a starting point for the Owner to review
  and apply from the Stats tab, not an automatic change.
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
  accepting free-form text. A platform-wide **minimum withdrawal amount**
  (`CPMSetting.min_withdraw_amount`, Owner-only, set from the panel's CPM
  Settings drawer) is enforced the same way — the bot's `/withdraw` flow
  and the panel's withdrawal form both reject a request below it before
  it's ever created; the API layer (`POST /api/withdraw`) enforces it
  again server-side regardless of which frontend was used. The moment a
  valid request is made — from the bot or the panel — the Owner gets a
  Telegram DM with the amount, method, account number, and links to
  every one of the requester's Traffic Sources, plus a button into the
  panel. Owner marks Paid/Rejected in the panel's Withdrawals queue;
  balance is only deducted on Paid. The moment the Owner resolves it, the
  *requesting* Admin gets a Telegram DM back — confirming the payment
  (and account it was sent to) on Paid, or the reason on Rejected — so
  they know their money is on its way without having to re-check the
  panel.

## Dashboard layout

The Owner and Admin panels are intentionally different, not just
re-skinned:

- **Admin** gets four tabs: Overview, My Links, Traffic Sources, Withdraw
  — everything a single admin needs day to day.
- **Owner** gets a "business snapshot" card (pending withdrawals, total
  admins, current CPM) instead of a personal balance card, and three
  primary tabs: Overview, Withdrawals (the queue, with a badge showing
  the pending count), and Admins (each with all of their Traffic Sources
  visible and a suspend/reactivate toggle). Tapping an Admin opens a
  detail view — today's income, lifetime income, confirmed balance,
  total withdrawn, pending views/withdrawals, link and view counts — plus
  a manual balance-correction tool for undoing fraud or fixing a mistake
  (see "Owner balance corrections" below). The Owner's own personal
  actions — My Links, Traffic Sources, and Request Withdrawal — are
  listed right on the Overview tab as a simple stacked list, since the
  Owner uses these just like any Admin would. Only genuine platform-level
  configuration —
  CPM Settings and Platform Stats — lives behind the ⚙️ menu at the top
  right, as a bottom-sheet drawer, instead of cluttering the main tab bar.

## Owner balance corrections

From an Admin's detail view (Admins tab → tap an Admin), the Owner can
set that Admin's confirmed balance to any value — e.g. to claw back a
suspicious credit or fix a mistake. This is a deliberately heavyweight
action:

- The panel shows the exact change (`old → new`, with the delta) and
  requires the Owner to type the literal word `CONFIRM` before the
  "Apply change" button enables — this is enforced again server-side
  (`POST /api/admin/admins/{id}/balance` rejects the request unless
  `confirm_text` is exactly `"CONFIRM"`), so the safeguard can't be
  skipped by calling the API directly.
- An optional reason can be attached for your own records.
- The affected Admin is **not** notified — this is a private Owner-side
  tool, not a withdrawal action — but every change is permanently logged
  (`cpm_history`, event `balance_adjustment`: old value, new value,
  reason, who did it, when) and shown back in that Admin's detail view
  under "Balance adjustment history", so nothing here is a silent edit.

The same detail view also surfaces today's income and lifetime income
per Admin, computed from each view's own `credited_amount` (see
"Per-view income tracking" below) rather than just the current balance
— so the numbers stay trustworthy even after a manual correction, which
is the whole point of having them for fraud-watching in the first place.

## Local setup

1. Create a bot with [@BotFather](https://t.me/BotFather) and grab both
   the token and the bot's `@username`.
2. Get your numeric Telegram ID from [@userinfobot](https://t.me/userinfobot)
   — this is your `OWNER_TELEGRAM_ID`.
3. Get an Adsgram block ID from your Adsgram dashboard — create it as a
   **Reward** (or Interstitial) block, not a Task block; see "Adsgram
   integration notes" below for why.
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

## Adsgram integration notes

`webapp/viewer.html` calls `window.Adsgram.init({ blockId }).show()` —
per Adsgram's own docs, this exact call is shared by both **Reward** and
**Interstitial** block types, so no code changes are needed for either.
The two differ in one important way for this app's payout model: an
Interstitial block can resolve `.show()` successfully even if the viewer
closes the ad early, while a Reward block only resolves once the ad is
watched in full. Since a resolved `.show()` here directly triggers a
credited view (and therefore money owed to the Admin), **create the
Adsgram block as Reward, not Interstitial** — otherwise a viewer who
skips the ad can still trigger a payout that Adsgram itself may not
compensate for. Avoid Task-type blocks entirely for this flow; they use
a completely different `<adsgram-task>` embed, not `.show()`, and are
meant for one-off actions rather than a repeated "watch 3 ads" loop.

The bare root domain (`https://tgshortbot.onrender.com`, no path) is the
one registered with both BotFather (as the bot's Mini App / menu button
URL) and Adsgram (as the platform's Web App URL) — `GET /` just redirects
to `/panel`. Both `/panel` and `/r/{code}` already live under this same
origin, so this is about having one stable, canonical URL to register
externally rather than a functional requirement; it doesn't change who
can access what, since role is still decided server-side by Telegram ID.

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
- Every CPM change, Traffic Source update, cycle payout, and manual
  balance correction is appended to an in-memory + persisted audit log
  (`cpm_history` in `store.json`).

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
- **Per-view income tracking**: `View` now carries `credited_amount` and
  `credited_at`, filled in by `cpm_engine.py` the moment a view's status
  becomes CONFIRMED (immediately in Real-time mode; at cycle-close time
  in Scheduled mode, since the rate isn't known any earlier). This is
  what makes the Owner's per-Admin "today's income" / "lifetime income"
  figures possible — without it, only the current balance total would be
  recoverable, with no way to say how much of it came from today. A
  still-`pending_payout` view has `credited_amount: null` until its cycle
  closes; the Admin detail view shows those separately as an *estimated*
  pending amount (view count × the current CPM rate) rather than
  pretending to know the exact figure early.
- **Ad view delay**: Adsgram doesn't have the next Reward ad ready the
  instant one finishes — there's typically a 5–8 second gap. Between ad 1
  and ad 2, and between ad 2 and ad 3, `webapp/viewer.html` shows a
  disabled, counting-down "Next ad ready in Ns" button instead of letting
  the viewer tap straight into an ad that isn't loaded yet (which would
  just surface an Adsgram error). This gap defaults to 7 seconds and is
  configurable platform-wide from the panel's CPM Settings screen
  (`CPMSetting.ad_view_delay_seconds`, `POST /api/admin/cpm`) — it lives
  alongside CPM rather than as its own model since it's Owner-only,
  platform-wide config with nowhere else to sit.
- **SVG icons over emoji in the Mini App UI**: `webapp/panel.html`'s nav,
  drawer, and action-button icons are all small inline stroke-based SVGs
  now (a shared `icon(name, size)` helper) instead of emoji glyphs, for a
  more consistent, professional look that doesn't vary by OS/emoji font.
  This applies to the Mini App only — `bot.py`'s Telegram chat messages
  keep their emoji, since a plain Telegram text message can't render SVG.
- **Bot commands as tappable buttons**: `/start` and `/help` now show a
  persistent reply keyboard (`bot.py`'s `_main_menu_keyboard`) with one
  button per command — 🔗 নতুন লিংক, 📡 ট্রাফিক সোর্স, 💰 ব্যালেন্স,
  💸 উইথড্র, 📊 ড্যাশবোর্ড (opens the Mini App directly), and ❓ সাহায্য —
  instead of a plain-text list the Admin has to read and type from. Each
  button is wired to the exact same handler as its slash command, and the
  keyboard reappears after any flow completes so it's always one tap away.
  These button handlers are registered before any FSM-state handler, so a
  tap always takes priority even mid-flow (e.g. partway through
  `/withdraw`) rather than being swallowed as free text by that flow.
  Telegram's own "/" command menu (`bot.set_my_commands`, called on every
  startup from `app.py`'s lifespan) is also populated as a second, native
  way to reach every command.
- **Minimum withdrawal amount**: `CPMSetting.min_withdraw_amount`
  (default `0`, meaning no minimum) is Owner-only, platform-wide config
  set from the panel's CPM Settings drawer — same "nowhere else to sit"
  reasoning as `ad_view_delay_seconds`. Below it, a withdrawal request is
  rejected before it's ever created: the bot's `/withdraw` flow checks it
  both when the flow starts and when the amount is entered, the panel's
  withdrawal form checks it client-side and shows the minimum next to the
  confirmed balance, and `POST /api/withdraw` enforces it again
  server-side regardless of which frontend was used. Every change to it
  is logged in `cpm_history` the same way a CPM-rate change is.
- **Anti-abuse daily view cap**: `CPMSetting.max_daily_views_per_admin`
  (default `0`, meaning no cap) is Owner-only, platform-wide config set
  from the panel's CPM Settings drawer — same "nowhere else to sit"
  reasoning as `ad_view_delay_seconds` and `min_withdraw_amount`. It
  counts per `(Admin, viewer, UTC calendar day)` — every view a viewer
  has logged today across *all* of that Admin's links, not just one, so
  spreading views across several links doesn't dodge it. The check and
  the credit decision happen atomically inside `cpm_engine.
  credit_new_view`'s existing lock, so two views logged in the same
  instant can't both slip in just under the limit. A capped view is
  still marked `CONFIRMED` with `credited_amount: 0` (not left
  `pending_payout`) since there's nothing left to pay out on it later —
  it's flagged `daily_capped: true` instead, which is how the Owner's
  per-Admin detail view and Platform Stats surface a "Daily-capped
  views" count. The viewer experience in `webapp/viewer.html` is
  unchanged either way — ads still play and the redirect still happens,
  since the whole point is that Adsgram gets paid regardless; only the
  Admin's earning silently stops.
- **Copy buttons on short links**: both the "Create a short link" result
  and every row in "My Links" now have a Copy button
  (`navigator.clipboard`, with a `document.execCommand("copy")` fallback
  for older WebViews) — there was previously no way to copy a generated
  link without manually selecting the text.
- **A few extra API endpoints** beyond a literal reading of the PRD's
  Section 9.4 table were added because the panel Mini App genuinely
  needs them: `GET /api/me`, `GET /api/withdrawals/mine`,
  `GET/POST /api/traffic-sources` + `PUT/DELETE /api/traffic-sources/{id}`,
  `POST /api/admin/admins/{id}/status` (ban/unban, called out as an
  Owner capability in Section 2), and `GET /api/admin/admins/{id}` +
  `POST /api/admin/admins/{id}/balance` for the Owner's per-Admin detail
  view and balance-correction tool.

## Out of scope (unchanged from the PRD)

Database persistence beyond JSON, automated fraud detection beyond the
per-viewer dedupe rule, per-admin CPM mode mixing, withdrawal methods
beyond bKash/Nagad, and exact per-impression Adsgram revenue sync are all
deliberately not implemented here — see Section 7 of the PRD.
