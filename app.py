"""FastAPI app for TGSHORTBOT — webhook receiver, short-link redirect
entrypoint, and the Mini App API.

Run locally with:
    uvicorn app:app --reload

Deployed on Render with:
    uvicorn app:app --host 0.0.0.0 --port $PORT
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import random
import string
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiohttp
from aiogram.types import Update
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

import cpm_engine
from bot import (
    build_bot_and_dispatcher,
    notify_admin_of_ad_count_change,
    notify_admin_of_withdrawal_resolution,
    notify_owner_of_admin_request,
    notify_owner_of_withdrawal,
    notify_sub_admin_of_admin_request_resolution,
    notify_sub_admin_of_auto_delete_change,
    notify_sub_admin_of_cpm_change,
    register_handlers,
    set_bot_commands,
)
from config import get_settings
from models import (
    Admin,
    AdminRequestStatus,
    AdminStatus,
    AdNetwork,
    AdNetworkSetting,
    CountedStatus,
    CPMMode,
    CPMSetting,
    Role,
    WithdrawMethod,
    WithdrawStatus,
    effective_ad_count,
)
from storage import Storage
from telegram_auth import InitDataError, validate_init_data
from validators import bd_mobile_validation_error, normalize_bd_mobile_number

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")

settings = get_settings()
storage = Storage(settings.SUPABASE_URL, settings.SUPABASE_KEY)
bot, dp = build_bot_and_dispatcher(settings.BOT_TOKEN)
register_handlers(dp, storage, settings)

_cpm_watcher_task: Optional[asyncio.Task] = None
_keep_alive_task: Optional[asyncio.Task] = None
_link_expiry_task: Optional[asyncio.Task] = None


async def _keep_alive_worker(base_url: str, interval_seconds: int = 600) -> None:
    """Self-pings `/health` every `interval_seconds` (default 10 min) so
    Render's free tier — which spins a web service down after 15 minutes
    with no inbound HTTP traffic — never sees a long enough idle gap to
    sleep it. This is the exact same "external uptime ping" workaround
    people commonly point an outside service like cron-job.org or
    UptimeRobot at; the only difference here is the app pings itself, so
    no third-party service or extra setup is needed.

    Trade-off (identical to the external-pinger approach, not avoided by
    doing it this way): keeping the service alive around the clock burns
    through Render's free 750 instance-hours/month much faster than
    normal bursty traffic would — 750 hours is roughly a full month of
    24/7 uptime, so this alone can use up nearly the whole free monthly
    allowance.
    """
    await asyncio.sleep(20)  # let the app finish its own startup first
    url = f"{base_url}/health"
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        logger.info("Keep-alive ping OK (%s)", url)
                    else:
                        logger.warning("Keep-alive ping got HTTP %s from %s", resp.status, url)
            except Exception:
                logger.warning("Keep-alive ping failed", exc_info=True)
            await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await storage.load()

    try:
        await bot.set_webhook(
            url=settings.WEBHOOK_URL,
            secret_token=settings.WEBHOOK_SECRET,
            drop_pending_updates=False,
        )
        logger.info("Webhook set to %s", settings.WEBHOOK_URL)
    except Exception:
        logger.exception("Could not set webhook on startup — set it manually with scripts/set_webhook.py")

    try:
        await set_bot_commands(bot)
    except Exception:
        logger.exception("Could not set bot command menu on startup")

    global _cpm_watcher_task, _keep_alive_task, _link_expiry_task
    _cpm_watcher_task = asyncio.create_task(
        cpm_engine.run_cpm_cycle_watcher(storage, settings.CPM_CHECK_INTERVAL_SECONDS)
    )
    _link_expiry_task = asyncio.create_task(cpm_engine.run_link_expiry_watcher(storage))
    _keep_alive_task = asyncio.create_task(_keep_alive_worker(settings.WEBAPP_BASE_URL))
    logger.info("TGSHORTBOT backend started")

    yield

    if _cpm_watcher_task:
        _cpm_watcher_task.cancel()
    if _link_expiry_task:
        _link_expiry_task.cancel()
    if _keep_alive_task:
        _keep_alive_task.cancel()
    await bot.session.close()


app = FastAPI(title="TGSHORTBOT", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="webapp"), name="webapp-static")


# ---------------------------------------------------------------------------
# Auth dependencies — every Mini App call is validated against Telegram's
# initData signature server-side (never trust a client-supplied Telegram ID).
# ---------------------------------------------------------------------------

async def _extract_user(x_telegram_init_data: Optional[str]) -> dict:
    if not x_telegram_init_data:
        raise HTTPException(status_code=401, detail="missing X-Telegram-Init-Data header")
    try:
        result = validate_init_data(x_telegram_init_data, settings.BOT_TOKEN)
    except InitDataError as e:
        raise HTTPException(status_code=401, detail=f"invalid init data: {e}")
    user = result.get("user")
    if not user or "id" not in user:
        raise HTTPException(status_code=401, detail="init data missing user")
    return user


async def require_admin(
    x_telegram_init_data: Optional[str] = Header(default=None, alias="X-Telegram-Init-Data")
) -> Admin:
    user = await _extract_user(x_telegram_init_data)
    admin = await storage.get_or_create_admin(user["id"], user.get("username"), settings.OWNER_TELEGRAM_ID)
    if admin.status == AdminStatus.BANNED:
        raise HTTPException(status_code=403, detail="account suspended")
    return admin


async def require_owner(admin: Admin = Depends(require_admin)) -> Admin:
    if admin.role != Role.OWNER:
        raise HTTPException(status_code=403, detail="owner only")
    return admin


async def require_owner_or_admin(admin: Admin = Depends(require_admin)) -> Admin:
    """Gate for the API-key management endpoints (/api/apikeys/*) — only
    Owner and Admin can generate keys for the public REST API; a Sub
    Admin or Viewer never gets one, matching the panel's own "Owner/Admin
    only" framing for this feature.
    """
    if admin.role not in (Role.OWNER, Role.ADMIN):
        raise HTTPException(status_code=403, detail="owner/admin only")
    return admin


# ---------------------------------------------------------------------------
# Public REST API auth (/api/v1/*) — a long-lived API key instead of a
# Telegram-signed initData header, for calling the API from the Owner's or
# an Admin's own site/server. See API_DOCS.md.
# ---------------------------------------------------------------------------

async def require_api_key(
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> Admin:
    raw_key = None
    if x_api_key:
        raw_key = x_api_key.strip()
    elif authorization and authorization.lower().startswith("bearer "):
        raw_key = authorization[7:].strip()
    if not raw_key:
        raise HTTPException(
            status_code=401,
            detail="missing API key — send it as 'X-API-Key: <key>' or 'Authorization: Bearer <key>'",
        )
    admin = await storage.get_admin_by_api_key(raw_key)
    if not admin:
        raise HTTPException(status_code=401, detail="invalid or revoked API key")
    if admin.status == AdminStatus.BANNED:
        raise HTTPException(status_code=403, detail="account suspended")
    return admin


async def require_api_key_owner(admin: Admin = Depends(require_api_key)) -> Admin:
    if admin.role != Role.OWNER:
        raise HTTPException(status_code=403, detail="owner only")
    return admin


# ---------------------------------------------------------------------------
# Health & webhook
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    """Keeps Render's free-tier service awake (NFR, Section 6)."""
    return {"ok": True}


@app.get("/")
async def root():
    """The bare domain is the canonical URL registered with BotFather and
    with Adsgram (both `/panel` and `/r/{code}` already live under this
    same origin, so this is purely about having one stable, memorable
    root URL rather than a path — it doesn't change what anyone can
    access, since role is still decided server-side by Telegram ID, not
    by which URL was opened).
    """
    return RedirectResponse(url="/panel")


_PRIVACY_PAGE_TEMPLATE = """<!doctype html>
<html lang="bn">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Privacy Policy & Terms — TGSHORTBOT</title>
<style>
  :root{{
    --bg:#12141c; --panel:#1e2230; --hairline:#2b3040;
    --brass:#d9a441; --text:#f1ede4; --text-dim:#9aa0b4;
  }}
  *{{box-sizing:border-box;}}
  html,body{{margin:0;padding:0;background:var(--bg);color:var(--text);
    font-family:Inter,system-ui,sans-serif;}}
  .wrap{{max-width:640px;margin:0 auto;padding:40px 20px 60px;}}
  .eyebrow{{font-size:11px;letter-spacing:.18em;text-transform:uppercase;
    color:var(--text-dim);margin-bottom:8px;}}
  h1{{font-size:22px;margin:0 0 24px;}}
  .card{{background:var(--panel);border:1px solid var(--hairline);
    border-radius:14px;padding:22px 20px;white-space:pre-wrap;
    word-wrap:break-word;line-height:1.7;font-size:15px;}}
  .back{{display:inline-block;margin-top:24px;color:var(--brass);
    text-decoration:none;font-size:14px;}}
  .back:hover{{text-decoration:underline;}}
</style>
</head>
<body>
  <div class="wrap">
    <div class="eyebrow">TGSHORTBOT</div>
    <h1>Privacy Policy &amp; Terms</h1>
    <div class="card">{policy_text}</div>
    <a class="back" href="https://t.me/{bot_username}">← Open in Telegram</a>
  </div>
</body>
</html>
"""


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_page():
    """Publicly viewable Privacy Policy & Terms page — no Telegram auth
    required, so ad-network moderators, prospective users, or anyone else
    can read it straight from a plain browser visit. Reuses the same
    Owner-editable PolicySetting text shown inside the bot's /privacy
    command and Accept/Reject gate, so there's exactly one policy text
    across the bot, the dashboard, and this page.
    """
    ps = await storage.get_policy_setting()
    body = _PRIVACY_PAGE_TEMPLATE.format(
        policy_text=html.escape(ps.text),
        bot_username=html.escape(settings.BOT_USERNAME),
    )
    return HTMLResponse(body)


@app.post("/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(default=None),
):
    if x_telegram_bot_api_secret_token != settings.WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="bad secret token")
    data = await request.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Short-link entrypoint — serves the ad-lock Mini App page (Section 4.2)
# ---------------------------------------------------------------------------

def _ad_slot_sequence(ans: AdNetworkSetting, count: int) -> list[str]:
    """Returns the Owner's configured Ad1/Ad2/Ad3... network pattern,
    cycled to exactly `count` entries — `count` is whatever
    models.effective_ad_count() decided for this link's owner (their
    own Admin/Sub-Admin profile override, or the platform default).
    Cycling (rather than padding with a fixed network, or truncating
    silently) keeps every slot pointing at a real, Owner-configured
    network even when an Admin's override is longer or shorter than the
    base pattern.
    """
    seq = ans.slot_sequence or [AdNetwork.ADSGRAM]
    return [seq[i % len(seq)].value for i in range(count)]


def _build_ad_config(ans: AdNetworkSetting, cs: CPMSetting, count: int) -> dict:
    return {
        "networks": {
            "adsgram": {"block_id": ans.adsgram_block_id},
            "monetag": {"zone_id": ans.monetag_zone_id, "sdk_url": ans.monetag_sdk_url},
            "gigapub": {"project_id": ans.gigapub_project_id},
        },
        "sequence": _ad_slot_sequence(ans, count),
        "ad_view_delay_seconds": cs.ad_view_delay_seconds,
    }


def _json_for_script(obj) -> str:
    """Serializes `obj` for embedding as a bare (unquoted) JS expression
    inside webapp/viewer.html's inline <script> tag — safe against a
    stray "</script>" inside an Owner-entered value ever prematurely
    closing the surrounding tag.
    """
    return json.dumps(obj).replace("</", "<\\/")


@app.get("/r/{short_code}", response_class=HTMLResponse)
async def redirect_entry(short_code: str):
    link = await storage.get_link(short_code)
    if not link:
        raise HTTPException(status_code=404, detail="link not found")
    cs = await storage.get_cpm_setting()
    ans = await storage.get_ad_network_setting()
    owner = await storage.get_admin(link.owner_telegram_id)
    ad_config = _build_ad_config(ans, cs, effective_ad_count(owner, ans))
    with open("webapp/viewer.html", "r", encoding="utf-8") as f:
        html = f.read()
    html = (
        html.replace("__SHORT_CODE__", short_code)
        .replace("__AD_CONFIG_JSON__", _json_for_script(ad_config))
        .replace("__AD_VIEW_DELAY_SECONDS__", str(cs.ad_view_delay_seconds))
    )
    return HTMLResponse(html)


@app.get("/r", response_class=HTMLResponse)
async def redirect_entry_direct():
    """Same ad-lock page as /r/{short_code}, but with no short_code baked
    into the HTML. This is the one fixed URL registered with @BotFather
    as this bot's Mini App (see README.md's "Direct-open Mini App"
    section) — Telegram opens it straight from a
    t.me/<bot>/<short_name>?startapp=<code> link, skipping the chat and
    the extra button tap entirely. webapp/viewer.html resolves which
    link it's showing and fetches that link's ad config itself, entirely
    client-side, via Telegram.WebApp.initDataUnsafe.start_param and
    GET /api/ad-config/{short_code} below.
    """
    with open("webapp/viewer.html", "r", encoding="utf-8") as f:
        html = f.read()
    html = (
        html.replace("__SHORT_CODE__", "")
        .replace("__AD_CONFIG_JSON__", "null")
        .replace("__AD_VIEW_DELAY_SECONDS__", "0")
    )
    return HTMLResponse(html)


@app.get("/api/ad-config/{short_code}")
async def get_ad_config(short_code: str):
    """Public, no auth — called client-side by webapp/viewer.html only
    when it was opened via the short_code-less GET /r route above (the
    direct-open Mini App flow) and needs to look up which link it's
    unlocking and that link's ad sequence. Exposes nothing an anyone
    viewing /r/{short_code}'s page source couldn't already see.
    """
    link = await storage.get_link(short_code)
    if not link:
        raise HTTPException(status_code=404, detail="link not found")
    cs = await storage.get_cpm_setting()
    ans = await storage.get_ad_network_setting()
    owner = await storage.get_admin(link.owner_telegram_id)
    return _build_ad_config(ans, cs, effective_ad_count(owner, ans))


@app.get("/panel", response_class=HTMLResponse)
async def panel_page():
    with open("webapp/panel.html", "r", encoding="utf-8") as f:
        html = f.read()
    # Powers the "Open in Telegram" button on the outside-Telegram landing
    # page (shown when there's no initData) — always 200 OK with real HTML,
    # never a redirect, so ad-network moderation bots see a working page.
    html = html.replace("__BOT_USERNAME__", settings.BOT_USERNAME)
    return HTMLResponse(html)


# ---------------------------------------------------------------------------
# Viewer API
# ---------------------------------------------------------------------------

@app.post("/api/log-view")
async def log_view(
    payload: dict,
    x_telegram_init_data: Optional[str] = Header(default=None, alias="X-Telegram-Init-Data"),
):
    """Logs one completed ad-watch. Repeat visits by the same viewer to
    the same link each create their own View and are credited the same
    as a first visit — see storage.create_view's docstring — the only
    thing still capping repeat views is the Anti-Abuse System's daily
    limit (`daily_capped` on the response), not a one-view-per-link
    ceiling.
    """
    user = await _extract_user(x_telegram_init_data)
    short_code = payload.get("short_code")
    if not short_code:
        raise HTTPException(status_code=400, detail="short_code required")

    link = await storage.get_link(short_code)
    if not link:
        raise HTTPException(status_code=404, detail="link not found")

    viewer_id = user["id"]
    view = await storage.create_view(short_code, viewer_id)
    await cpm_engine.credit_new_view(storage, view, link)
    return {"ok": True, "daily_capped": view.daily_capped}


@app.get("/api/link/{short_code}")
async def get_link_destination(
    short_code: str,
    x_telegram_init_data: Optional[str] = Header(default=None, alias="X-Telegram-Init-Data"),
):
    # Only called by viewer.html *after* the view has been logged.
    await _extract_user(x_telegram_init_data)
    link = await storage.get_link(short_code)
    if not link:
        raise HTTPException(status_code=404, detail="link not found")
    return {"destination_url": link.destination_url}


# ---------------------------------------------------------------------------
# Admin: my profile
# ---------------------------------------------------------------------------

@app.get("/api/me")
async def me(admin: Admin = Depends(require_admin)):
    return admin.model_dump()


@app.get("/api/traffic-sources")
async def list_traffic_sources(admin: Admin = Depends(require_admin)):
    return {"traffic_sources": [s.model_dump() for s in admin.traffic_sources]}


@app.post("/api/traffic-sources")
async def add_traffic_source(payload: dict, admin: Admin = Depends(require_admin)):
    """Adds one more traffic source; an Admin can hold several at once
    and add/update/remove them at any time (no longer a single slot).
    """
    platform = (payload.get("platform") or "").strip()
    url = (payload.get("url") or "").strip()
    if not platform:
        raise HTTPException(status_code=400, detail="platform required")
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="url must be a valid http(s) link")
    source = await storage.add_traffic_source(admin.telegram_id, platform, url)
    await storage.append_history(
        "traffic_source_change",
        {"telegram_id": admin.telegram_id, "action": "add", "platform": platform, "url": url},
    )
    return source.model_dump()


@app.put("/api/traffic-sources/{source_id}")
async def edit_traffic_source(source_id: str, payload: dict, admin: Admin = Depends(require_admin)):
    platform = payload.get("platform")
    url = payload.get("url")
    if platform is not None:
        platform = platform.strip()
        if not platform:
            raise HTTPException(status_code=400, detail="platform cannot be empty")
    if url is not None:
        url = url.strip()
        if not url.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="url must be a valid http(s) link")
    updated = await storage.update_traffic_source(admin.telegram_id, source_id, platform=platform, url=url)
    if not updated:
        raise HTTPException(status_code=404, detail="traffic source not found")
    await storage.append_history(
        "traffic_source_change",
        {"telegram_id": admin.telegram_id, "action": "update", "source_id": source_id, "platform": platform, "url": url},
    )
    return updated.model_dump()


@app.delete("/api/traffic-sources/{source_id}")
async def remove_traffic_source(source_id: str, admin: Admin = Depends(require_admin)):
    ok = await storage.delete_traffic_source(admin.telegram_id, source_id)
    if not ok:
        raise HTTPException(status_code=404, detail="traffic source not found")
    await storage.append_history(
        "traffic_source_change",
        {"telegram_id": admin.telegram_id, "action": "delete", "source_id": source_id},
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Admin: links
# ---------------------------------------------------------------------------

def _gen_short_code(length: int = 7) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choices(alphabet, k=length))


def _short_url_for(code: str) -> str:
    if getattr(settings, "MINI_APP_SHORT_NAME", ""):
        # Direct-open Mini App link — Telegram loads GET /r straight away
        # with this code as initDataUnsafe.start_param, no chat step.
        return f"https://t.me/{settings.BOT_USERNAME}/{settings.MINI_APP_SHORT_NAME}?startapp={code}"
    return f"https://t.me/{settings.BOT_USERNAME}?start={code}"


@app.post("/api/links")
async def create_link(payload: dict, admin: Admin = Depends(require_admin)):
    if not admin.traffic_sources:
        raise HTTPException(
            status_code=400,
            detail="Add at least one Traffic Source before creating links (POST /api/traffic-sources)",
        )
    destination_url = (payload.get("destination_url") or "").strip()
    if not destination_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="destination_url must be a valid http(s) URL")

    code = _gen_short_code()
    while await storage.get_link(code):
        code = _gen_short_code()
    # ad_count is never taken from the request here — every new link
    # starts at storage.Storage.DEFAULT_AD_COUNT regardless of who
    # creates it; only the Owner can change it afterward, per-link, via
    # POST /api/admin/links/{short_code}/ad-count.
    link = await storage.create_link(code, admin.telegram_id, destination_url)
    return {"short_code": link.short_code, "short_url": _short_url_for(link.short_code), "ad_count": link.ad_count}


@app.delete("/api/links/{short_code}")
async def delete_link(short_code: str, admin: Admin = Depends(require_admin)):
    ok = await storage.delete_link(short_code, admin.telegram_id, admin.role == Role.OWNER)
    if not ok:
        raise HTTPException(status_code=404, detail="link not found")
    return {"ok": True}


@app.get("/api/links")
async def my_links(admin: Admin = Depends(require_admin)):
    """Per-link stats for the requesting Admin's own "My Links" list.

    `view_count` / `confirmed_views` deliberately exclude any view the
    Anti-Abuse System flagged `daily_capped` — a capped view earned
    nothing, so it must never inflate what an Admin sees as their total
    or confirmed view count. Capped views are Owner-only information
    (see storage.admin_stats' `daily_capped_views` /
    `missed_earnings_trend` / `missed_earnings_by_link`); an Admin simply
    never sees them here, not even as a smaller number — they vanish
    from this endpoint entirely rather than being labelled and shown.

    `ad_count` comes through in `**l.model_dump()` below, so an Admin
    can see the old per-link value — it's legacy and read-only either
    way (see Link.ad_count's docstring). `effective_ad_count` is the
    number that actually matters now: how many ads a viewer of this
    link really watches, i.e. this Admin's own `Admin.ad_count`
    profile override if the Owner set one for them, otherwise
    len(AdNetworkSetting.slot_sequence) — see effective_ad_count()'s
    docstring in models.py. It's the same value for every link in this
    list, since it's a per-Admin setting, not a per-link one.
    """
    ans = await storage.get_ad_network_setting()
    my_ad_count = effective_ad_count(admin, ans)
    links = await storage.list_links_by_owner(admin.telegram_id)
    out = []
    for l in links:
        views = await storage.list_views_by_short_code(l.short_code)
        genuine_views = [v for v in views if not v.daily_capped]
        out.append(
            {
                **l.model_dump(),
                "short_url": _short_url_for(l.short_code),
                "effective_ad_count": my_ad_count,
                "view_count": len(genuine_views),
                "confirmed_views": len(
                    [v for v in genuine_views if v.counted_status == CountedStatus.CONFIRMED]
                ),
                "pending_views": len(
                    [v for v in genuine_views if v.counted_status == CountedStatus.PENDING_PAYOUT]
                ),
            }
        )
    out.sort(key=lambda x: x["created_at"], reverse=True)
    return {"links": out}


# ---------------------------------------------------------------------------
# CPM
# ---------------------------------------------------------------------------

@app.get("/api/cpm")
async def get_cpm(admin: Admin = Depends(require_admin)):
    cs = await storage.get_cpm_setting()
    data = cs.model_dump()
    if cs.mode == CPMMode.SCHEDULED:
        started = datetime.fromisoformat(cs.cycle_started_at)
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        deadline = started + timedelta(hours=cs.cycle_duration_hours)
        data["seconds_to_payout"] = max(0, int((deadline - datetime.now(timezone.utc)).total_seconds()))
        if admin.role != Role.OWNER:
            # Sub-admins see the countdown and pending-view count, but not
            # a pre-calculated rate, since it isn't final until payout (Section 4.5).
            # That includes the per-role overrides below, not just the base rate.
            data.pop("current_cpm", None)
            data.pop("admin_cpm", None)
            data.pop("sub_admin_cpm", None)
    return data


@app.post("/api/admin/cpm")
async def admin_update_cpm(payload: dict, owner: Admin = Depends(require_owner)):
    mode_enum = None
    if payload.get("mode") is not None:
        try:
            mode_enum = CPMMode(payload["mode"])
        except ValueError:
            raise HTTPException(status_code=400, detail="mode must be 'realtime' or 'scheduled'")

    current_cpm = payload.get("current_cpm")
    if current_cpm is not None:
        current_cpm = float(current_cpm)
        if current_cpm < 0:
            raise HTTPException(status_code=400, detail="current_cpm must be >= 0")

    cycle_duration_hours = payload.get("cycle_duration_hours")
    if cycle_duration_hours is not None:
        cycle_duration_hours = float(cycle_duration_hours)
        if cycle_duration_hours <= 0:
            raise HTTPException(status_code=400, detail="cycle_duration_hours must be > 0")

    ad_view_delay_seconds = payload.get("ad_view_delay_seconds")
    if ad_view_delay_seconds is not None:
        ad_view_delay_seconds = float(ad_view_delay_seconds)
        if ad_view_delay_seconds < 0:
            raise HTTPException(status_code=400, detail="ad_view_delay_seconds must be >= 0")

    min_withdraw_amount = payload.get("min_withdraw_amount")
    if min_withdraw_amount is not None:
        min_withdraw_amount = float(min_withdraw_amount)
        if min_withdraw_amount < 0:
            raise HTTPException(status_code=400, detail="min_withdraw_amount must be >= 0")

    max_daily_views_per_admin = payload.get("max_daily_views_per_admin")
    if max_daily_views_per_admin is not None:
        try:
            max_daily_views_per_admin = int(max_daily_views_per_admin)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="max_daily_views_per_admin must be a whole number")
        if max_daily_views_per_admin < 0:
            raise HTTPException(status_code=400, detail="max_daily_views_per_admin must be >= 0")

    # admin_cpm / sub_admin_cpm are per-role platform-wide CPM overrides
    # (distinct from the per-Sub-Admin override on the Admins tab). Unlike
    # the fields above, a blank field here means "clear it back to the
    # base current_cpm rate", not "leave it unchanged" — so, unlike them,
    # we only touch storage's value when the key is actually present in
    # the payload at all (present-but-null clears it; absent leaves it).
    extra: dict = {}
    if "admin_cpm" in payload:
        admin_cpm = payload.get("admin_cpm")
        if admin_cpm is not None:
            admin_cpm = float(admin_cpm)
            if admin_cpm < 0:
                raise HTTPException(status_code=400, detail="admin_cpm must be >= 0 or null")
        extra["admin_cpm"] = admin_cpm
    if "sub_admin_cpm" in payload:
        sub_admin_cpm = payload.get("sub_admin_cpm")
        if sub_admin_cpm is not None:
            sub_admin_cpm = float(sub_admin_cpm)
            if sub_admin_cpm < 0:
                raise HTTPException(status_code=400, detail="sub_admin_cpm must be >= 0 or null")
        extra["sub_admin_cpm"] = sub_admin_cpm
    if "default_sub_admin_auto_delete_months" in payload:
        months = payload.get("default_sub_admin_auto_delete_months")
        if months:
            try:
                months = int(months)
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=400, detail="default_sub_admin_auto_delete_months must be a whole number or null"
                )
            if months not in Storage.SUB_ADMIN_AUTO_DELETE_CHOICES:
                valid = ", ".join(str(m) for m in Storage.SUB_ADMIN_AUTO_DELETE_CHOICES)
                raise HTTPException(
                    status_code=400,
                    detail=f"default_sub_admin_auto_delete_months must be null/0 (never) or one of: {valid}",
                )
        else:
            months = None
        extra["default_sub_admin_auto_delete_months"] = months

    cs = await storage.update_cpm_setting(
        mode=mode_enum,
        current_cpm=current_cpm,
        cycle_duration_hours=cycle_duration_hours,
        ad_view_delay_seconds=ad_view_delay_seconds,
        min_withdraw_amount=min_withdraw_amount,
        max_daily_views_per_admin=max_daily_views_per_admin,
        updated_by=owner.telegram_id,
        **extra,
    )
    return cs.model_dump()


# ---------------------------------------------------------------------------
# Ad networks — Adsgram / Monetag / GigaPub credentials + the Ad1/Ad2/Ad3...
# network sequence, both Owner-only (see webapp/panel.html's Ad Networks tab
# and _ad_slot_sequence() above, which app.py's /r/{short_code} route uses to
# actually apply this at ad-serving time).
# ---------------------------------------------------------------------------

@app.get("/api/ad-networks")
async def get_ad_networks(owner: Admin = Depends(require_owner)):
    ans = await storage.get_ad_network_setting()
    return ans.model_dump()


@app.post("/api/admin/ad-networks")
async def admin_update_ad_networks(payload: dict, owner: Admin = Depends(require_owner)):
    adsgram_block_id = payload.get("adsgram_block_id")
    if adsgram_block_id is not None:
        adsgram_block_id = str(adsgram_block_id).strip()

    monetag_zone_id = payload.get("monetag_zone_id")
    if monetag_zone_id is not None:
        monetag_zone_id = str(monetag_zone_id).strip()

    monetag_sdk_url = payload.get("monetag_sdk_url")
    if monetag_sdk_url is not None:
        monetag_sdk_url = str(monetag_sdk_url).strip()

    gigapub_project_id = payload.get("gigapub_project_id")
    if gigapub_project_id is not None:
        gigapub_project_id = str(gigapub_project_id).strip()

    slot_sequence = None
    if payload.get("slot_sequence") is not None:
        raw_sequence = payload["slot_sequence"]
        if not isinstance(raw_sequence, list) or not raw_sequence:
            raise HTTPException(status_code=400, detail="slot_sequence must be a non-empty list")
        if len(raw_sequence) > Storage.MAX_AD_COUNT:
            raise HTTPException(
                status_code=400,
                detail=f"slot_sequence can have at most {Storage.MAX_AD_COUNT} entries",
            )
        try:
            slot_sequence = [AdNetwork(v) for v in raw_sequence]
        except ValueError:
            valid = ", ".join(n.value for n in AdNetwork)
            raise HTTPException(status_code=400, detail=f"slot_sequence entries must be one of: {valid}")

    ans = await storage.update_ad_network_setting(
        adsgram_block_id=adsgram_block_id,
        monetag_zone_id=monetag_zone_id,
        monetag_sdk_url=monetag_sdk_url,
        gigapub_project_id=gigapub_project_id,
        slot_sequence=slot_sequence,
        updated_by=owner.telegram_id,
    )
    return ans.model_dump()


# ---------------------------------------------------------------------------
# Policy — the Accept/Reject text every user must agree to in the bot
# (see bot.py's PolicyGateMiddleware). Any Admin can read it (so the panel
# can show it to anyone, e.g. on a Terms page); only the Owner can edit it.
# ---------------------------------------------------------------------------

@app.get("/api/policy")
async def get_policy(admin: Admin = Depends(require_admin)):
    ps = await storage.get_policy_setting()
    return ps.model_dump()


@app.post("/api/admin/policy")
async def admin_update_policy(payload: dict, owner: Admin = Depends(require_owner)):
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(status_code=400, detail="text must be a non-empty string")
    ps = await storage.update_policy_text(text.strip(), updated_by=owner.telegram_id)
    return ps.model_dump()


# ---------------------------------------------------------------------------
# Withdrawals
# ---------------------------------------------------------------------------

@app.post("/api/withdraw")
async def request_withdrawal(payload: dict, admin: Admin = Depends(require_admin)):
    try:
        amount = float(payload.get("amount"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="amount must be a number")
    method = payload.get("method")
    account_number_raw = (payload.get("account_number") or "").strip()

    if method not in ("bkash", "nagad"):
        raise HTTPException(status_code=400, detail="method must be 'bkash' or 'nagad'")
    validation_error = bd_mobile_validation_error(account_number_raw)
    if validation_error:
        raise HTTPException(status_code=400, detail=validation_error)
    account_number = normalize_bd_mobile_number(account_number_raw)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="amount must be positive")
    if amount > admin.balance_confirmed:
        raise HTTPException(status_code=400, detail="amount exceeds confirmed balance")

    cs = await storage.get_cpm_setting()
    if amount < cs.min_withdraw_amount:
        raise HTTPException(
            status_code=400,
            detail=f"amount is below the minimum withdrawal amount ({cs.min_withdraw_amount:.2f})",
        )

    req = await storage.create_withdrawal(admin.telegram_id, amount, WithdrawMethod(method), account_number)
    await notify_owner_of_withdrawal(bot, settings, admin, req)
    return req.model_dump()


@app.get("/api/withdrawals/mine")
async def my_withdrawals(admin: Admin = Depends(require_admin)):
    all_w = await storage.list_withdrawals()
    mine = sorted(
        (w.model_dump() for w in all_w if w.admin_telegram_id == admin.telegram_id),
        key=lambda w: w["created_at"],
        reverse=True,
    )
    return {"withdrawals": mine}


@app.get("/api/admin/withdrawals")
async def admin_pending_withdrawals(owner: Admin = Depends(require_owner)):
    pending = await storage.list_withdrawals(status=WithdrawStatus.PENDING)
    pending.sort(key=lambda w: w.created_at)
    out = []
    for w in pending:
        requester = await storage.get_admin(w.admin_telegram_id)
        d = w.model_dump()
        d["admin_username"] = requester.username if requester else None
        d["traffic_sources"] = [s.model_dump() for s in requester.traffic_sources] if requester else []
        out.append(d)
    return {"withdrawals": out}


@app.post("/api/admin/withdrawals/{request_id}/resolve")
async def admin_resolve_withdrawal(request_id: str, payload: dict, owner: Admin = Depends(require_owner)):
    decision = payload.get("decision")
    if decision not in ("paid", "rejected"):
        raise HTTPException(status_code=400, detail="decision must be 'paid' or 'rejected'")
    reason = payload.get("reason")
    status_enum = WithdrawStatus.PAID if decision == "paid" else WithdrawStatus.REJECTED
    req = await storage.resolve_withdrawal(request_id, status_enum, reason)
    if not req:
        raise HTTPException(status_code=404, detail="withdrawal not found or already resolved")
    requester = await storage.get_admin(req.admin_telegram_id)
    if requester:
        await notify_admin_of_withdrawal_resolution(bot, settings, requester, req)
    return req.model_dump()


# ---------------------------------------------------------------------------
# Sub Admin -> Admin promotion requests
# ---------------------------------------------------------------------------

@app.post("/api/admin-request")
async def submit_admin_request(payload: dict, admin: Admin = Depends(require_admin)):
    """A Sub Admin's own request to be promoted to Admin — the panel
    equivalent of the bot's /requestadmin flow. Only reachable by a
    current Role.SUB_ADMIN with no request already pending.
    """
    if admin.role != Role.SUB_ADMIN:
        raise HTTPException(status_code=403, detail="only a Sub Admin can request Admin promotion")
    if admin.admin_request_status == AdminRequestStatus.PENDING:
        raise HTTPException(status_code=400, detail="a request is already pending review")
    note = (payload.get("note") or "").strip() or None
    updated = await storage.submit_admin_request(admin.telegram_id, note)
    stats = await storage.admin_stats(admin.telegram_id)
    await notify_owner_of_admin_request(bot, settings, updated, note, stats)
    return updated.model_dump()


# ---------------------------------------------------------------------------
# Owner: admins list, ban/unban, platform stats
# ---------------------------------------------------------------------------

@app.get("/api/admin/admins")
async def list_all_admins(owner: Admin = Depends(require_owner)):
    admins = await storage.list_admins()
    admins.sort(key=lambda a: a.created_at)
    return {"admins": [a.model_dump() for a in admins]}


@app.get("/api/admin/admins/{telegram_id}")
async def admin_detail(telegram_id: int, owner: Admin = Depends(require_owner)):
    stats = await storage.admin_stats(telegram_id)
    if not stats:
        raise HTTPException(status_code=404, detail="admin not found")
    stats["balance_adjustments"] = await storage.list_balance_adjustments(telegram_id)
    return stats


@app.get("/api/admin/admins/{telegram_id}/links")
async def admin_links(telegram_id: int, owner: Admin = Depends(require_owner)):
    """Every link this Admin/Sub Admin owns — the list the Owner's
    per-Admin detail page shows alongside their profile-level ad count
    control (see POST /api/admin/admins/{telegram_id}/ad-count).
    `effective_ad_count` is the same value repeated on every row (a
    per-Admin setting, not a per-link one), included per-link only so
    the panel doesn't need a second round trip."""
    target = await storage.get_admin(telegram_id)
    if not target or not await storage.admin_stats(telegram_id):
        raise HTTPException(status_code=404, detail="admin not found")
    ans = await storage.get_ad_network_setting()
    my_ad_count = effective_ad_count(target, ans)
    links = await storage.admin_links_detail(telegram_id)
    for l in links:
        l["effective_ad_count"] = my_ad_count
    return {"links": links}


@app.post("/api/admin/links/{short_code}/ad-count")
async def set_link_ad_count(short_code: str, payload: dict, owner: Admin = Depends(require_owner)):
    """Owner-only control over how many sequential ads one specific link
    shows before unlocking. Neither the link's own Admin nor the bot's
    /newlink flow can reach this — see Link.ad_count and
    storage.set_link_ad_count."""
    try:
        ad_count = int(payload.get("ad_count"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="ad_count must be a whole number")
    if not (Storage.MIN_AD_COUNT <= ad_count <= Storage.MAX_AD_COUNT):
        raise HTTPException(
            status_code=400,
            detail=f"ad_count must be between {Storage.MIN_AD_COUNT} and {Storage.MAX_AD_COUNT}",
        )
    link = await storage.set_link_ad_count(short_code, ad_count)
    if not link:
        raise HTTPException(status_code=404, detail="link not found")
    return link.model_dump()


@app.post("/api/admin/admins/{telegram_id}/balance")
async def edit_admin_balance(telegram_id: int, payload: dict, owner: Admin = Depends(require_owner)):
    """Manually corrects an Admin's confirmed balance. Requires the
    literal string "CONFIRM" in `confirm_text` — this mirrors the
    two-step confirmation the panel UI walks the Owner through, enforced
    again here so the safeguard can't be skipped by calling the API
    directly. The change is always logged (see storage.set_admin_balance)
    and the affected Admin is *not* notified — this is a private
    Owner-side correction tool, not a withdrawal action.
    """
    try:
        new_balance = float(payload.get("new_balance"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="new_balance must be a number")
    if new_balance < 0:
        raise HTTPException(status_code=400, detail="new_balance cannot be negative")
    if payload.get("confirm_text") != "CONFIRM":
        raise HTTPException(status_code=400, detail='type CONFIRM to apply this balance change')

    reason = (payload.get("reason") or "").strip() or None
    admin = await storage.set_admin_balance(telegram_id, new_balance, reason, owner.telegram_id)
    if not admin:
        raise HTTPException(status_code=404, detail="admin not found")
    return admin.model_dump()


@app.post("/api/admin/admins/{telegram_id}/status")
async def set_admin_status(telegram_id: int, payload: dict, owner: Admin = Depends(require_owner)):
    status = payload.get("status")
    if status not in ("active", "banned"):
        raise HTTPException(status_code=400, detail="status must be 'active' or 'banned'")
    if telegram_id == owner.telegram_id:
        raise HTTPException(status_code=400, detail="cannot change your own status")
    admin = await storage.set_admin_status(telegram_id, AdminStatus(status))
    if not admin:
        raise HTTPException(status_code=404, detail="admin not found")
    return admin.model_dump()


@app.get("/api/admin/stats")
async def platform_stats(owner: Admin = Depends(require_owner)):
    return await storage.platform_stats()


# ---------------------------------------------------------------------------
# Owner: Sub Admin -> Admin promotion request queue
# ---------------------------------------------------------------------------

@app.get("/api/admin/admin-requests")
async def list_admin_requests(owner: Admin = Depends(require_owner)):
    """Every currently-pending Admin request, each with the same stats
    bundle (links/views/earnings) the Owner's DM notification carries,
    so the panel's queue is just as informative without needing a
    separate round trip per request.
    """
    pending = await storage.list_admin_requests(AdminRequestStatus.PENDING)
    pending.sort(key=lambda a: a.admin_request_at or "")
    out = []
    for a in pending:
        stats = await storage.admin_stats(a.telegram_id)
        out.append(
            {
                "admin": a.model_dump(),
                "total_links": stats["total_links"] if stats else 0,
                "total_views": stats["total_views"] if stats else 0,
                "lifetime_income": stats["lifetime_income"] if stats else 0,
            }
        )
    return {"requests": out}


@app.post("/api/admin/admin-requests/{telegram_id}/resolve")
async def resolve_admin_request(telegram_id: int, payload: dict, owner: Admin = Depends(require_owner)):
    decision = payload.get("decision")
    if decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="decision must be 'approve' or 'reject'")
    reason = (payload.get("reason") or "").strip() or None
    if decision == "reject" and not reason:
        raise HTTPException(status_code=400, detail="a reason is required to reject an Admin request")
    updated = await storage.resolve_admin_request(
        telegram_id, approve=(decision == "approve"), reason=reason, resolved_by=owner.telegram_id
    )
    if not updated:
        raise HTTPException(status_code=404, detail="no pending admin request found for this user")
    await notify_sub_admin_of_admin_request_resolution(bot, updated, approved=(decision == "approve"), reason=reason)
    return updated.model_dump()


# ---------------------------------------------------------------------------
# Owner: direct role management + per-Sub-Admin CPM override / auto-delete
# ---------------------------------------------------------------------------

@app.post("/api/admin/admins/{telegram_id}/role")
async def set_role(telegram_id: int, payload: dict, owner: Admin = Depends(require_owner)):
    """Owner's general promote/demote control (Admins tab), separate
    from the guided request-and-review flow above — e.g. demoting an
    Admin back to Sub Admin, or promoting a Viewer/Sub Admin straight to
    Admin without going through a request at all.
    """
    role_raw = payload.get("role")
    try:
        role = Role(role_raw)
    except ValueError:
        valid = ", ".join(r.value for r in Role if r != Role.OWNER)
        raise HTTPException(status_code=400, detail=f"role must be one of: {valid}")
    if role == Role.OWNER:
        raise HTTPException(status_code=400, detail="cannot assign the Owner role")
    if telegram_id == owner.telegram_id:
        raise HTTPException(status_code=400, detail="cannot change your own role")
    updated = await storage.set_role(telegram_id, role, changed_by=owner.telegram_id)
    if not updated:
        raise HTTPException(status_code=404, detail="admin not found")
    return updated.model_dump()


@app.post("/api/admin/admins/{telegram_id}/sub-admin-cpm")
async def set_sub_admin_cpm(telegram_id: int, payload: dict, owner: Admin = Depends(require_owner)):
    cpm_raw = payload.get("cpm")
    cpm = None
    if cpm_raw is not None:
        try:
            cpm = float(cpm_raw)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="cpm must be a number or null")
        if cpm < 0:
            raise HTTPException(status_code=400, detail="cpm must be >= 0")
    updated = await storage.set_sub_admin_cpm(telegram_id, cpm, changed_by=owner.telegram_id)
    if not updated:
        raise HTTPException(status_code=404, detail="admin not found")
    await notify_sub_admin_of_cpm_change(bot, updated, cpm)
    return updated.model_dump()


@app.post("/api/admin/admins/{telegram_id}/ad-count")
async def set_admin_ad_count(telegram_id: int, payload: dict, owner: Admin = Depends(require_owner)):
    """Owner-only per-Admin/Sub-Admin ad count override — set once on
    this person's profile, it applies in real time to every link they
    own (existing and future), replacing the old per-link
    POST /api/admin/links/{short_code}/ad-count control."""
    raw = payload.get("ad_count")
    ad_count = None
    if raw is not None and raw != "":
        try:
            ad_count = int(raw)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="ad_count must be a whole number or null")
        if not (Storage.MIN_AD_COUNT <= ad_count <= Storage.MAX_AD_COUNT):
            raise HTTPException(
                status_code=400,
                detail=f"ad_count must be between {Storage.MIN_AD_COUNT} and {Storage.MAX_AD_COUNT}",
            )
    updated = await storage.set_admin_ad_count(telegram_id, ad_count, changed_by=owner.telegram_id)
    if not updated:
        raise HTTPException(status_code=404, detail="admin not found")
    await notify_admin_of_ad_count_change(bot, updated, ad_count)
    return updated.model_dump()


@app.post("/api/admin/admins/{telegram_id}/auto-delete")
async def set_link_auto_delete(telegram_id: int, payload: dict, owner: Admin = Depends(require_owner)):
    months_raw = payload.get("months")
    months = None
    if months_raw:
        try:
            months = int(months_raw)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="months must be a whole number or null")
        if months not in Storage.SUB_ADMIN_AUTO_DELETE_CHOICES:
            valid = ", ".join(str(m) for m in Storage.SUB_ADMIN_AUTO_DELETE_CHOICES)
            raise HTTPException(status_code=400, detail=f"months must be null/0 (never) or one of: {valid}")
    updated = await storage.set_link_auto_delete(telegram_id, months, changed_by=owner.telegram_id)
    if not updated:
        raise HTTPException(status_code=404, detail="admin not found")
    await notify_sub_admin_of_auto_delete_change(bot, updated, months)
    return updated.model_dump()


# ---------------------------------------------------------------------------
# API keys (Owner/Admin only) — generate/list/revoke credentials for the
# public REST API below. Management itself still goes through the panel,
# so it's authenticated with the normal Telegram initData header, not an
# API key (you need to already be in the panel to mint your first key).
# ---------------------------------------------------------------------------

@app.post("/api/apikeys")
async def create_api_key(payload: dict, admin: Admin = Depends(require_owner_or_admin)):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required (e.g. 'My site', 'Zapier')")
    if len(name) > 60:
        raise HTTPException(status_code=400, detail="name must be 60 characters or fewer")
    key, raw_key = await storage.create_api_key(admin.telegram_id, name)
    return {
        # `api_key` is the ONLY time this raw secret is ever returned —
        # store it now, it can't be shown again (only key_prefix, below,
        # is kept for future reference).
        "api_key": raw_key,
        "key_id": key.key_id,
        "name": key.name,
        "key_prefix": key.key_prefix,
        "created_at": key.created_at,
    }


@app.get("/api/apikeys")
async def list_api_keys(admin: Admin = Depends(require_owner_or_admin)):
    keys = await storage.list_api_keys(admin.telegram_id)
    return {
        "api_keys": [
            {
                "key_id": k.key_id,
                "name": k.name,
                "key_prefix": k.key_prefix,
                "created_at": k.created_at,
                "last_used_at": k.last_used_at,
                "revoked_at": k.revoked_at,
            }
            for k in keys
        ]
    }


@app.delete("/api/apikeys/{key_id}")
async def revoke_api_key(key_id: str, admin: Admin = Depends(require_owner_or_admin)):
    ok = await storage.revoke_api_key(key_id, admin.telegram_id)
    if not ok:
        raise HTTPException(status_code=404, detail="api key not found (or already revoked)")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Public REST API (/api/v1) — everything here uses `require_api_key`
# instead of Telegram initData, so it can be called from an Owner's or
# Admin's own site/server with a key from POST /api/apikeys above.
# Endpoints mirror the Mini App's own /api/* routes 1:1 in behavior; see
# API_DOCS.md for the full reference and curl examples.
# ---------------------------------------------------------------------------

@app.get("/api/v1/me")
async def v1_me(admin: Admin = Depends(require_api_key)):
    return admin.model_dump(exclude={"traffic_sources"})


@app.post("/api/v1/links")
async def v1_create_link(payload: dict, admin: Admin = Depends(require_api_key)):
    if not admin.traffic_sources:
        raise HTTPException(
            status_code=400,
            detail="Add at least one Traffic Source from the panel before creating links",
        )
    destination_url = (payload.get("destination_url") or "").strip()
    if not destination_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="destination_url must be a valid http(s) URL")

    code = _gen_short_code()
    while await storage.get_link(code):
        code = _gen_short_code()
    link = await storage.create_link(code, admin.telegram_id, destination_url)
    return {"short_code": link.short_code, "short_url": _short_url_for(link.short_code), "ad_count": link.ad_count}


@app.get("/api/v1/links")
async def v1_my_links(admin: Admin = Depends(require_api_key)):
    ans = await storage.get_ad_network_setting()
    my_ad_count = effective_ad_count(admin, ans)
    links = await storage.list_links_by_owner(admin.telegram_id)
    out = []
    for l in links:
        views = await storage.list_views_by_short_code(l.short_code)
        genuine_views = [v for v in views if not v.daily_capped]
        out.append(
            {
                **l.model_dump(),
                "short_url": _short_url_for(l.short_code),
                "effective_ad_count": my_ad_count,
                "view_count": len(genuine_views),
                "confirmed_views": len(
                    [v for v in genuine_views if v.counted_status == CountedStatus.CONFIRMED]
                ),
                "pending_views": len(
                    [v for v in genuine_views if v.counted_status == CountedStatus.PENDING_PAYOUT]
                ),
            }
        )
    out.sort(key=lambda x: x["created_at"], reverse=True)
    return {"links": out}


@app.delete("/api/v1/links/{short_code}")
async def v1_delete_link(short_code: str, admin: Admin = Depends(require_api_key)):
    ok = await storage.delete_link(short_code, admin.telegram_id, admin.role == Role.OWNER)
    if not ok:
        raise HTTPException(status_code=404, detail="link not found")
    return {"ok": True}


@app.get("/api/v1/cpm")
async def v1_get_cpm(admin: Admin = Depends(require_api_key)):
    cs = await storage.get_cpm_setting()
    data = cs.model_dump()
    if cs.mode == CPMMode.SCHEDULED:
        started = datetime.fromisoformat(cs.cycle_started_at)
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        deadline = started + timedelta(hours=cs.cycle_duration_hours)
        data["seconds_to_payout"] = max(0, int((deadline - datetime.now(timezone.utc)).total_seconds()))
        if admin.role != Role.OWNER:
            data.pop("current_cpm", None)
            data.pop("admin_cpm", None)
            data.pop("sub_admin_cpm", None)
    return data


@app.post("/api/v1/withdraw")
async def v1_request_withdrawal(payload: dict, admin: Admin = Depends(require_api_key)):
    try:
        amount = float(payload.get("amount"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="amount must be a number")
    method = payload.get("method")
    account_number_raw = (payload.get("account_number") or "").strip()

    if method not in ("bkash", "nagad"):
        raise HTTPException(status_code=400, detail="method must be 'bkash' or 'nagad'")
    validation_error = bd_mobile_validation_error(account_number_raw)
    if validation_error:
        raise HTTPException(status_code=400, detail=validation_error)
    account_number = normalize_bd_mobile_number(account_number_raw)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="amount must be positive")
    if amount > admin.balance_confirmed:
        raise HTTPException(status_code=400, detail="amount exceeds confirmed balance")

    cs = await storage.get_cpm_setting()
    if amount < cs.min_withdraw_amount:
        raise HTTPException(
            status_code=400,
            detail=f"amount is below the minimum withdrawal amount ({cs.min_withdraw_amount:.2f})",
        )

    req = await storage.create_withdrawal(admin.telegram_id, amount, WithdrawMethod(method), account_number)
    await notify_owner_of_withdrawal(bot, settings, admin, req)
    return req.model_dump()


@app.get("/api/v1/withdrawals")
async def v1_my_withdrawals(admin: Admin = Depends(require_api_key)):
    all_w = await storage.list_withdrawals()
    mine = sorted(
        (w.model_dump() for w in all_w if w.admin_telegram_id == admin.telegram_id),
        key=lambda w: w["created_at"],
        reverse=True,
    )
    return {"withdrawals": mine}


# -- Owner-only public API endpoints ----------------------------------------

@app.get("/api/v1/admins")
async def v1_list_all_admins(owner: Admin = Depends(require_api_key_owner)):
    admins = await storage.list_admins()
    return {"admins": [a.model_dump() for a in admins]}


@app.get("/api/v1/stats")
async def v1_platform_stats(owner: Admin = Depends(require_api_key_owner)):
    return await storage.platform_stats()
