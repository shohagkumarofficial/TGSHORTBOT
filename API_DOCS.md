# TGSHORTBOT Public API

A small REST API so the Owner or any Admin can create links, check stats,
and request withdrawals from their **own site or server** — no Telegram
Mini App context required. It sits alongside the panel's own `initData`-
authenticated `/api/*` routes and mirrors their behavior 1:1; this is just
a different door into the same data.

All endpoints below live under `/api/v1/` and return JSON.

## 1. Getting an API key

Keys are generated from inside the panel (Telegram-authenticated), so you
need to already be logged into `/panel` once to mint your first one. Only
the **Owner** and **Admin** roles can generate keys — Sub Admins and
Viewers can't.

```
POST /api/apikeys
Content-Type: application/json
X-Telegram-Init-Data: <panel's normal auth header>

{ "name": "My website" }
```

Response:

```json
{
  "api_key": "tgs_9f2c1a7e4b0d6f38a1c9e2b7d4f0a6c3e8b1d5f2a9c7e0b3",
  "key_id": "b6e2...",
  "name": "My website",
  "key_prefix": "tgs_9f2c1a7e",
  "created_at": "2026-08-28T10:00:00+00:00"
}
```

**`api_key` is shown exactly once, in this response.** TGSHORTBOT only
ever stores its SHA-256 hash — there is no "show my key again" screen, so
save it somewhere safe immediately. If you lose it, revoke it and generate
a new one.

Manage existing keys from the same panel session:

- `GET /api/apikeys` — list your keys (name, prefix, created/last-used
  dates, revoked status). Never returns the raw secret again.
- `DELETE /api/apikeys/{key_id}` — revoke a key immediately; anything using
  it starts getting `401 invalid or revoked API key` right away.

## 2. Authenticating API requests

Send the raw key on every `/api/v1/*` request, either header works:

```
X-API-Key: tgs_9f2c1a7e4b0d6f38a1c9e2b7d4f0a6c3e8b1d5f2a9c7e0b3
```

or

```
Authorization: Bearer tgs_9f2c1a7e4b0d6f38a1c9e2b7d4f0a6c3e8b1d5f2a9c7e0b3
```

A key authenticates as whichever Admin generated it, **at that Admin's
current role** — it's not a frozen snapshot of permissions. If the Owner
bans, demotes, or promotes that Admin, every key they hold reflects that
change (or a ban) on the very next request.

| Status | Meaning |
|---|---|
| `401 missing API key` | Neither header was sent |
| `401 invalid or revoked API key` | Key doesn't exist, or was revoked |
| `403 account suspended` | The key's Admin is banned |
| `403 owner only` | Endpoint requires the Owner role specifically |

## 3. Endpoints

### `GET /api/v1/me`
Your own Admin record — role, balances, status. Good for a first
connectivity check.

```bash
curl https://your-domain/api/v1/me \
  -H "X-API-Key: tgs_..."
```

### `POST /api/v1/links`
Create a short link. Requires at least one Traffic Source already added
from the panel — same rule as the bot's `/newlink`. `ad_count` is never
client-settable here either; every link starts at the platform default.
`title` is optional — a display-only label, 100 characters or fewer;
omit it (or send `null`) and the link simply has no title.

```bash
curl -X POST https://your-domain/api/v1/links \
  -H "X-API-Key: tgs_..." \
  -H "Content-Type: application/json" \
  -d '{"destination_url": "https://example.com/my-page", "title": "August giveaway post"}'
```

```json
{
  "short_code": "aB3xQ9z",
  "short_url": "https://t.me/YourBot?start=aB3xQ9z",
  "ad_count": 3,
  "title": "August giveaway post"
}
```

### `GET /api/v1/links`
List your own links with view counts (capped/abusive views excluded, same
as the panel's "My Links"). Each link includes `title` (`null` if none
was set at creation).

```bash
curl https://your-domain/api/v1/links -H "X-API-Key: tgs_..."
```

### `DELETE /api/v1/links/{short_code}`
Delete one of your own links (Owner keys can delete anyone's). The link
stops resolving immediately; already-credited views and your balance are
untouched.

```bash
curl -X DELETE https://your-domain/api/v1/links/aB3xQ9z -H "X-API-Key: tgs_..."
```

### `GET /api/v1/cpm`
Current CPM settings. Sub Admin/Admin keys get the countdown-to-payout
info but not a pre-calculated rate in Scheduled mode (same restriction as
the panel).

### `POST /api/v1/withdraw`
Request a withdrawal from your confirmed balance.

```bash
curl -X POST https://your-domain/api/v1/withdraw \
  -H "X-API-Key: tgs_..." \
  -H "Content-Type: application/json" \
  -d '{"amount": 500, "method": "bkash", "account_number": "01712345678"}'
```

### `GET /api/v1/withdrawals`
Your own withdrawal history, newest first.

### `GET /api/v1/admins` — Owner only
Every Admin/Sub Admin/Viewer on the platform.

### `GET /api/v1/stats` — Owner only
Platform-wide stats (same payload as the panel's Stats tab).

## 4. Notes

- Rate limits: none enforced by the app itself yet — be a good citizen.
- All amounts are in the platform's configured currency, as plain numbers.
- Every timestamp is ISO-8601 UTC.
- Errors always come back as `{"detail": "..."}` with a matching HTTP
  status code — same shape FastAPI already uses for the panel's own API.
