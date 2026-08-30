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
├── API_DOCS.md            # public REST API reference (Owner/Admin API keys)
└── README.md
```

`data/store.json` is created automatically on first run — it isn't
committed, so there's nothing to conflict with in version control.

## How the core pieces fit together

- **Roles** (Section 2): the first person to `/start` the bot whose
  Telegram ID matches `OWNER_TELEGRAM_ID` becomes Owner; everyone else
  starts out as a **Viewer** — the lowest tier, no earning power — and is
  auto-promoted to **Sub Admin** the moment they add their first Traffic
  Source. Sub Admin -> **Admin** only happens through an explicit
  Owner-approved request. See **Sub Admin tier** below for the full
  Owner > Admin > Sub Admin > Viewer model.
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
  context. Every new link starts at `Storage.DEFAULT_AD_COUNT` (3)
  regardless of who creates it — see **Ad count per link** below for how
  that gets changed afterward.
- **Ad count per link**: how many sequential ads a link's viewer must
  watch (`Link.ad_count`, 1–10, default 3) is Owner-only to change,
  per link — not a single platform-wide number. Neither `POST
  /api/links` nor the bot's `/newlink` flow accepts a client-supplied
  value; every link starts at the default and stays there until the
  Owner adjusts it from a specific Admin's detail page in the panel
  (`GET /api/admin/admins/{id}/links` to list, `POST
  /api/admin/links/{short_code}/ad-count` to change one — both
  `require_owner`). The owning Admin can see the current count on their
  own "My Links" list (`GET /api/links`) but has no endpoint that can
  change it. `webapp/viewer.html`'s dial, step dots, and copy are all
  built dynamically from `Link.ad_count` at render time (`/r/{code}`
  derives it from the length of the per-slot ad network sequence it
  injects as `__AD_CONFIG_JSON__` — see **Ad networks**) rather than
  assuming a fixed 3.
- **Viewer flow** (4.2): the deep link opens the bot, which replies with
  a WebApp button pointing at `/r/{code}` — a Telegram Mini App
  (`webapp/viewer.html`) that runs that link's `ad_count` sequential
  ads (Adsgram, Monetag, and/or GigaPub, per the Owner's configured
  order — see **Ad networks**), then calls
  `POST /api/log-view`, then `GET /api/link/{code}`, then redirects.
- **Fraud/dedupe** (4.3, revised): a viewer revisiting the same link
  repeatedly counts every time — each completed ad-watch creates its own
  View row and credits the owning Admin, with no per-link,
  once-per-viewer ceiling any more. The only thing still limiting repeat
  views is the **Anti-Abuse System**'s daily cap
  (`CPMSetting.max_daily_views_per_admin`, Owner-only, set from the
  panel's CPM Settings drawer, default `0` = no cap), which counts a
  viewer's views against one Admin *across all of that Admin's links
  combined*, same-link repeats included: once a viewer crosses it,
  `cpm_engine.credit_new_view` still lets every further view play its
  ads and reach the destination as normal, it just stops adding
  to that Admin's balance (the `View` row is flagged `daily_capped`
  instead), so a viewer replaying one link (or several of one Admin's
  links) all day can't keep dragging that Admin's CPM down. **Missed
  Earnings Analytics** (`storage.missed_earnings_trend` /
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
  and apply from the Stats tab, not an automatic change. A `daily_capped`
  view **never** counts toward any `total_views` / `view_count` figure
  anywhere in the app — platform-wide, per-Admin, or per-link — since it
  earned nothing; it's tracked only through the separate
  `daily_capped_views` counter and the Missed Earnings views above. This
  split is also a visibility boundary: `GET /api/links` (what an Admin
  sees on their own "My Links" page) excludes capped views from
  `view_count`/`confirmed_views` entirely rather than showing a smaller,
  labelled number — an Admin never sees that their views were capped, it
  simply isn't there. Only the Owner-only endpoints
  (`/api/admin/stats`, `/api/admin/admins/{id}`) expose
  `daily_capped_views` and the Missed Earnings breakdowns.
- **Platform income reconciliation** (`storage.platform_income_summary`,
  surfaced on `/api/admin/stats` and the panel's Stats tab): today's /
  last-7-day / last-30-day / lifetime income across every Admin combined,
  plus the same breakdown for money actually paid out, each with a
  30-day daily bar chart — meant to be checked against Adsgram's own
  dashboard for the same days to see whether the platform is running at
  a profit or a loss. Derived from each view's own `credited_amount`
  (never from `balance_confirmed`), so a manual balance correction via
  `set_admin_balance` never skews it.
- **Withdrawal pause** (`CPMSetting.withdrawals_paused` /
  `storage.set_withdrawals_paused`, Owner-only, set from the panel's CPM
  Settings screen): a kill switch for new withdrawal requests, meant for
  when the Owner is busy or on leave. `POST /api/withdraw` and the bot's
  `/withdraw` flow both reject a new request outright while paused
  (with an optional Owner-set message), but anything already `PENDING`
  when the pause is turned on is untouched and still resolvable
  normally — this only stops new requests from being created, it's not
  a freeze on the existing queue.
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
  CPM Settings, Ad Networks, User Policy, and Platform Stats — lives
  behind the ⚙️ menu at the top right, as a bottom-sheet drawer, instead
  of cluttering the main tab bar.

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
3. You don't need an ad network ID before your first run anymore — Adsgram,
   Monetag, and GigaPub block/zone/project IDs are all set from the admin
   panel's **Ad Networks** tab after the bot is up (see "Ad networks"
   below), not from an env var. Sign up with whichever of the three you
   plan to use and grab their dashboard's ID whenever it's convenient.
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

## Ad networks

Adsgram, Monetag, and GigaPub block/zone/project IDs, and the order in
which each ad slot pulls from them, all live in the `ad_network_settings`
Supabase table (`models.AdNetworkSetting`, mirroring the single-row
pattern `cpm_settings`/`policy_settings` already use) and are managed
entirely from the Owner-only **Ad Networks** tab in `/panel` — there's no
env var for any of this anymore. `app.py`'s `/r/{code}` route reads that
row on every view and injects the resolved config straight into
`webapp/viewer.html`.

Run this once in Supabase's SQL editor before using the feature (the app
self-heals to an empty/default config if the table doesn't exist yet, but
saving from the panel needs it to be there):

```sql
create table if not exists ad_network_settings (
  id integer primary key default 1,
  adsgram_block_id text not null default '',
  monetag_zone_id text not null default '',
  monetag_sdk_url text not null default '',
  gigapub_project_id text not null default '',
  slot_sequence jsonb not null default '["adsgram","adsgram","adsgram"]',
  updated_at text not null default now()::text,
  updated_by bigint
);
```

**Ad display order.** The panel's "Ad display order" card is an ordered
list — Ad 1, Ad 2, Ad 3, ... — where each position picks a network, e.g.:

```
Ad 1 — Adsgram
Ad 2 — Monetag
Ad 3 — GigaPub
```

or any repeating mix, like `Adsgram, Monetag, Adsgram`. This doesn't need
to be as long as a given link's `ad_count` — the sequence just repeats
from the top once it runs out, so a 3-entry sequence covers a 7-ad link as
`Ad1, Ad2, Ad3, Ad1, Ad2, Ad3, Ad1`. A slot pointed at a network with no
ID filled in simply fails to load for that viewer, surfacing the same
"ad didn't load, try again" state as any other ad error — nothing blocks
saving an incomplete combination.

**Per-network integration details**, for reference:

- **Adsgram** — `webapp/viewer.html` calls
  `window.Adsgram.init({ blockId }).show()`. Per Adsgram's own docs, this
  exact call is shared by both **Reward** and **Interstitial** block
  types. The two differ in one important way for this app's payout model:
  an Interstitial block can resolve `.show()` successfully even if the
  viewer closes the ad early, while a Reward block only resolves once the
  ad is watched in full. Since a resolved `.show()` here directly triggers
  a credited view (and therefore money owed to the Admin), **create the
  Adsgram block as Reward, not Interstitial** — otherwise a viewer who
  skips the ad can still trigger a payout Adsgram itself may not
  compensate for. Avoid Task-type blocks entirely; they use a completely
  different `<adsgram-task>` embed, not `.show()`.
- **Monetag** — needs two values, not one: the **Zone ID**, and the full
  `<script src="...">` URL from Monetag's own "Get SDK" → Rewarded
  Interstitial tag for that zone. Monetag personalizes that script's
  domain per publisher/zone for anti-adblock reasons, so copy the exact
  URL shown in your dashboard rather than guessing at one — there's no
  single fixed domain this app could default to. The viewer loads that
  script with `data-zone`/`data-sdk="show_<zone>"` attributes, then calls
  `window.show_<zone>()`, matching Monetag's documented integration.
- **GigaPub** — needs only a Project ID. The viewer loads
  `https://ad.gigapub.tech/script?id=<project_id>` and calls
  `window.showGiga()`.

The bare root domain (`https://tgshortbot.onrender.com`, no path) is the
one registered with both BotFather (as the bot's Mini App / menu button
URL) and Adsgram (as the platform's Web App URL) — `GET /` just redirects
to `/panel`. Both `/panel` and `/r/{code}` already live under this same
origin, so this is about having one stable, canonical URL to register
externally rather than a functional requirement; it doesn't change who
can access what, since role is still decided server-side by Telegram ID.

## Sub Admin tier

The role hierarchy is now **Owner > Admin > Sub Admin > Viewer**, each with
strictly less power than the one before it:

- **Viewer** — a brand new `/start`. No earning power, no CPM, can't
  create links yet. The only thing to do at this tier is add a Traffic
  Source.
- **Sub Admin** — auto-promoted the instant a Viewer adds their first
  Traffic Source (`storage.add_traffic_source`). Can create links, add
  more Traffic Sources, and request a withdrawal, same as an Admin — but
  the Owner can (optionally, per Sub Admin) override their CPM rate
  (`Admin.sub_admin_cpm`, falls back to the platform-wide rate when
  unset — see `models.effective_cpm`, used by both crediting paths in
  `cpm_engine.py`) and set an auto-delete window for their *future* links
  (`Admin.link_auto_delete_months`, one of 1/3/6/12 months —
  `Storage.SUB_ADMIN_AUTO_DELETE_CHOICES` — or unset for "never"; purged
  by `cpm_engine.run_link_expiry_watcher`, a background loop alongside
  the CPM cycle watcher). Changing either setting only ever affects *new*
  links/views from that point on — never retroactive, same principle as
  a CPM-rate change never re-pricing views that already happened — and
  the Sub Admin gets a Telegram DM about the change either way.
- **Admin** — full Admin capabilities, no CPM override, no auto-delete.
  Reached only by an Owner-approved promotion request, never
  automatically.
- **Owner** — unchanged; fixed at boot from `OWNER_TELEGRAM_ID`.

**Promotion requests.** A Sub Admin sends `/requestadmin` in the bot (or
uses the "Admin হওয়ার আবেদন করুন" card on the panel's Profile tab), with
an optional short note about their traffic. The Owner gets a Telegram DM
with that Sub Admin's Traffic Sources, link/view/lifetime-income totals,
and the note, plus one-tap **✅ Approve** / **❌ Reject** buttons right in
the DM (Reject prompts for a reason in-chat, since one is required) — or
the same thing from the panel's **Admin Requests** tab. Either way the
Sub Admin gets a DM back: a congratulations on approval, or the Owner's
reason on rejection (and they're free to fix whatever the reason called
out and request again later). The Owner can also promote or demote
anyone directly from a specific Admin's detail page in the panel, outside
this request flow entirely (`POST /api/admin/admins/{id}/role`) —
demoting *out of* Sub Admin clears their CPM override and auto-delete
setting, so a later re-promotion starts clean.

**Role badges.** Every role has its own colored badge (violet Owner,
brass Admin, emerald Sub Admin, gray Viewer) — shown on your own top card
in the panel and next to every user in the Owner's Admins list. Tapping
any badge opens a short "what can I do" popup for that role.

**Required Supabase migration.** The `admins` and `links` tables need a
few new columns before any of this works — run this once in Supabase's
SQL editor (safe to re-run; `if not exists` skips columns that are
already there):

```sql
alter table admins
  add column if not exists sub_admin_cpm double precision,
  add column if not exists link_auto_delete_months integer,
  add column if not exists admin_request_status text,
  add column if not exists admin_request_note text,
  add column if not exists admin_request_at text,
  add column if not exists admin_request_reason text,
  add column if not exists admin_request_resolved_at text;

alter table links
  add column if not exists expires_at text;

alter table cpm_settings
  add column if not exists admin_cpm double precision,
  add column if not exists sub_admin_cpm double precision,
  add column if not exists default_sub_admin_auto_delete_months integer;
```

(The `cpm_settings` columns power the CPM tab's "Per-role CPM" card —
platform-wide rates for the Admin and Sub Admin roles, separate from the
per-Sub-Admin override on the Admins tab — and the "default for new Sub
Admins" auto-delete card, which pre-fills a Viewer's link auto-delete
window the moment they're promoted to Sub Admin, so the Owner doesn't
have to open every new Sub Admin's profile by hand. Writes still work
without this migration — `_safe_upsert` drops unknown columns and logs a
warning — but the values won't actually persist until it's run.)

If your `admins.role` column has a `CHECK` constraint limiting it to
specific values (e.g. only `'owner'`/`'admin'`), widen it to also allow
`'sub_admin'` and `'viewer'` — for example:

```sql
alter table admins drop constraint if exists admins_role_check;
alter table admins add constraint admins_role_check
  check (role in ('owner', 'admin', 'sub_admin', 'viewer'));
```

(Skip this if `role` is a plain unconstrained `text` column — most setups
following this README's earlier instructions will be.)

## Public REST API

Beyond the Mini App's own `/api/*` routes (Telegram-`initData`-authenticated,
used by `webapp/panel.html`), the Owner and every Admin can generate an API
key from the panel and call a small public API (`/api/v1/*`) from their own
site or server — no Telegram context needed. Full endpoint reference, auth
details, and curl examples: **[`API_DOCS.md`](API_DOCS.md)**.

Quick summary:

- **Generating a key** (panel-authenticated, Owner/Admin only):
  `POST /api/apikeys` `{"name": "My site"}` → the raw key is returned
  **once**, in that response, and never again — only its SHA-256 hash is
  stored (`storage.create_api_key`). `GET /api/apikeys` lists your own keys
  (name, prefix, last used) without ever re-exposing the secret;
  `DELETE /api/apikeys/{key_id}` revokes one. Sub Admins and Viewers can't
  generate keys.
- **Using a key**: send it as `X-API-Key: <key>` (or
  `Authorization: Bearer <key>`) on any `/api/v1/*` request. A key
  authenticates as whichever Admin generated it, at their *current* role —
  banning, demoting, or role-changing that Admin instantly changes (or cuts
  off) what their keys can do too, same as their Mini App session would be.
- **Required Supabase migration** — run once (safe to re-run):

  ```sql
  create table if not exists api_keys (
    key_id text primary key,
    owner_telegram_id bigint not null,
    name text not null,
    key_hash text not null unique,
    key_prefix text not null,
    created_at text not null,
    last_used_at text,
    revoked_at text
  );
  ```

  The app self-heals to "no keys yet" if this table doesn't exist (mirroring
  how `_safe_upsert` already tolerates a missing column elsewhere), but
  `POST /api/apikeys` needs it to actually persist anything.

## Link titles (optional)

Both `POST /api/links` (Mini App) and `POST /api/v1/links` (public REST
API) accept an optional `title` field (e.g. `{"destination_url": "...",
"title": "August giveaway post"}`) — purely a display label so an Admin
with many links can tell them apart at a glance. Nothing else in the app
reads it: it doesn't affect the short_code, the ad-serving flow, or CPM
crediting. Leaving it out (or the bot's `/newlink`, which doesn't ask for
one) works exactly as before — every existing link simply has
`title: null`. When set, it's shown in place of the bare short_code on
"My Links", the Owner's per-Admin link list, and every "Top Links"
breakdown; the short_code itself is still shown alongside it as a
secondary line so it's never hidden.

**Required Supabase migration** — run once (safe to re-run):

```sql
alter table links add column if not exists title text;
```

Until this is run, `_safe_upsert` silently drops the `title` field from
every write to the `links` table (logging a warning each time, per its
usual missing-column tolerance) — link creation still succeeds, the
title just won't survive a restart until the column exists.

## Deploying to Render

`render.yaml` is ready to use as-is:

1. Push this repo to GitHub/GitLab.
2. In Render, "New +" → "Blueprint", point it at the repo — it will read
   `render.yaml` and provision the web service.
3. Fill in the marked-`sync: false` environment variables in Render's
   dashboard (`BOT_TOKEN`, `BOT_USERNAME`, `WEBHOOK_URL`, `WEBHOOK_SECRET`,
   `OWNER_TELEGRAM_ID`, `WEBAPP_BASE_URL`) — for
   `WEBHOOK_URL`/`WEBAPP_BASE_URL`, use the `https://<service>.onrender.com`
   URL Render assigns you.
4. Deploy. `GET /health` is wired as the health check, which is what
   keeps a free-tier service from sleeping.
5. Create the `ad_network_settings` table (see "Ad networks" above), then
   from `/panel`'s Ad Networks tab fill in whichever of Adsgram / Monetag /
   GigaPub you're using and set the display order.
6. Test the full loop: `/start` the bot, `/trafficsource` to set where
   you'll share links, `/newlink`, open the resulting `t.me/...` link,
   watch the ads (3 by default — see **Ad count per link**), confirm the
   redirect, then request a withdrawal and
   check it shows up both as a Telegram DM and in the Owner panel.

## Security notes

- **Required migration if you're upgrading from an earlier version**:
  drop the old UNIQUE constraint on the `views` table so repeat views by
  the same viewer on the same link can be inserted —
  ```sql
  ALTER TABLE views DROP CONSTRAINT IF EXISTS views_short_code_viewer_telegram_id_key;
  ```
  (the constraint name may differ if you named it explicitly when
  creating the table — check with `\d views` in `psql` or the Supabase
  Table Editor's constraints view if the command above finds nothing to
  drop). Without this, `storage.create_view` fails on every repeat view
  and logs a duplicate-key error instead of counting it — see that
  method's docstring.
- Every Mini App API call is authenticated by validating Telegram's
  `initData` HMAC signature server-side (`telegram_auth.py`) — the
  client-supplied Telegram ID is never trusted directly, per the PRD's
  explicit instruction in Section 9.4.
- Every `/api/v1/*` public API call is authenticated by hashing the
  presented key and looking it up against the stored SHA-256 hash
  (`storage.get_admin_by_api_key`) — the raw key itself is never stored
  anywhere after the one response that issues it (see "Public REST API"
  above).
- If your `views` table has a foreign key on `links.short_code` (as
  README's earlier setup instructions have it), do **not** hard-delete a
  row from `links` while `views` referencing it still exist — do what
  `storage.delete_link`/`purge_expired_links` do and only remove it from
  the in-memory `self.links`, leaving the Supabase row in place. Deleting
  it directly orphans those Views, and since `storage._save_locked()`
  re-upserts the *entire* `views` table on every mutation, one orphaned
  row is enough to break every future write to any table until it's
  cleaned up.
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
daily Anti-Abuse view cap, per-admin CPM mode mixing, withdrawal methods
beyond bKash/Nagad, and exact per-impression Adsgram revenue sync are all
deliberately not implemented here — see Section 7 of the PRD.
