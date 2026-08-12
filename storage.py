"""JSON-backed storage layer.

Single-process, file-locked read/write. The interface is intentionally
narrow so the SQLite swap later is mechanical: replace `_load` / `_save`
and the in-memory mutations; the public methods stay the same.

All mutations go through a module-level `_lock` (asyncio) so concurrent
webhook + API requests can't clobber each other.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import string
from datetime import datetime
from pathlib import Path
from typing import Optional

from models import (
    Admin,
    AdminStatus,
    CPMSetting,
    Link,
    Role,
    Store,
    View,
    ViewCountedStatus,
    VerificationStatus,
    WithdrawRequest,
    WithdrawStatus,
)


_lock = asyncio.Lock()


def _short_code(n: int = 6) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


def _id(n: int = 12) -> str:
    return secrets.token_hex(n)


# --------------------------------------------------------------------------
# disk IO
# --------------------------------------------------------------------------

_store: Optional[Store] = None


def _path() -> str:
    from config import settings
    return settings.store_path


def _load_from_disk() -> Store:
    p = Path(_path())
    if not p.exists():
        return Store()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return Store.model_validate(raw)
    except Exception:
        # corrupt file — back it up and start fresh rather than crash
        backup = p.with_suffix(f".corrupt.{int(datetime.utcnow().timestamp())}.json")
        try:
            p.rename(backup)
        except Exception:
            pass
        return Store()


def _save_to_disk(store: Store) -> None:
    p = Path(_path())
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(store.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, p)


def get_store() -> Store:
    global _store
    if _store is None:
        _store = _load_from_disk()
    return _store


async def save() -> None:
    async with _lock:
        _save_to_disk(get_store())


# --------------------------------------------------------------------------
# audit
# --------------------------------------------------------------------------

def audit(event: str, **fields) -> None:
    s = get_store()
    s.audit_log.append({"ts": datetime.utcnow().isoformat(), "event": event, **fields})


# --------------------------------------------------------------------------
# admin
# --------------------------------------------------------------------------

async def get_or_create_admin(telegram_id: int, username: str = "") -> Admin:
    from config import settings
    s = get_store()
    key = str(telegram_id)
    if key not in s.admins:
        role = Role.OWNER if telegram_id == settings.owner_telegram_id else Role.ADMIN
        s.admins[key] = Admin(
            telegram_id=telegram_id,
            username=username,
            role=role,
            created_at=datetime.utcnow(),
        )
        await save()
    return s.admins[key]


def get_admin(telegram_id: int) -> Optional[Admin]:
    return get_store().admins.get(str(telegram_id))


def list_admins() -> list[Admin]:
    return list(get_store().admins.values())


async def set_admin_status(telegram_id: int, status: AdminStatus) -> None:
    s = get_store()
    a = s.admins.get(str(telegram_id))
    if not a:
        return
    a.status = status
    await save()


# --------------------------------------------------------------------------
# links
# --------------------------------------------------------------------------

async def create_link(owner_telegram_id: int, destination_url: str) -> Link:
    s = get_store()
    code = _short_code()
    # extremely unlikely collision, but guard anyway
    while code in s.links:
        code = _short_code()
    link = Link(
        short_code=code,
        owner_telegram_id=owner_telegram_id,
        destination_url=destination_url,
        created_at=datetime.utcnow(),
    )
    s.links[code] = link
    await save()
    return link


def get_link(short_code: str) -> Optional[Link]:
    return get_store().links.get(short_code)


def list_links(owner_telegram_id: Optional[int] = None) -> list[Link]:
    s = get_store()
    links = list(s.links.values())
    if owner_telegram_id is not None:
        links = [l for l in links if l.owner_telegram_id == owner_telegram_id]
    return links


def list_pending_proof_links() -> list[Link]:
    return [l for l in get_store().links.values()
            if l.proof_url and l.verification_status == VerificationStatus.PENDING]


async def set_link_proof(short_code: str, proof_url: str) -> Optional[Link]:
    s = get_store()
    link = s.links.get(short_code)
    if not link:
        return None
    link.proof_url = proof_url
    # re-enters pending review each time the proof changes
    link.verification_status = VerificationStatus.PENDING
    await save()
    return link


async def set_link_verification(short_code: str, status: VerificationStatus) -> Optional[Link]:
    s = get_store()
    link = s.links.get(short_code)
    if not link:
        return None
    link.verification_status = status
    # cascade to views
    if status == VerificationStatus.REJECTED:
        for v in s.views.values():
            if v.short_code == short_code:
                v.counted_status = ViewCountedStatus.REJECTED
    elif status == VerificationStatus.VERIFIED:
        from cpm_engine import on_link_verified
        await on_link_verified(short_code)
    await save()
    return link


# --------------------------------------------------------------------------
# views
# --------------------------------------------------------------------------

async def has_viewer_seen(short_code: str, viewer_telegram_id: int) -> bool:
    s = get_store()
    return any(
        v.short_code == short_code and v.viewer_telegram_id == viewer_telegram_id
        for v in s.views.values()
    )


async def record_view(short_code: str, viewer_telegram_id: int) -> View:
    from cpm_engine import classify_view
    s = get_store()
    v = View(
        view_id=_id(),
        short_code=short_code,
        viewer_telegram_id=viewer_telegram_id,
        created_at=datetime.utcnow(),
        counted_status=ViewCountedStatus.UNVERIFIED,
        cpm_cycle_id=get_store().cpm.cycle_id or None,
    )
    v.counted_status = classify_view(get_store().cpm)
    s.views[v.view_id] = v
    await save()
    return v


def list_views_for_link(short_code: str) -> list[View]:
    return [v for v in get_store().views.values() if v.short_code == short_code]


def list_views_in_cycle(cycle_id: str) -> list[View]:
    return [v for v in get_store().views.values() if v.cpm_cycle_id == cycle_id]


# --------------------------------------------------------------------------
# withdrawals
# --------------------------------------------------------------------------

async def create_withdraw(
    admin_telegram_id: int, amount: float, method: str, account_number: str
) -> WithdrawRequest:
    s = get_store()
    from models import WithdrawMethod
    w = WithdrawRequest(
        request_id=_id(),
        admin_telegram_id=admin_telegram_id,
        amount=amount,
        method=WithdrawMethod(method),
        account_number=account_number,
        created_at=datetime.utcnow(),
    )
    s.withdrawals[w.request_id] = w
    await save()
    return w


def list_withdrawals(status: Optional[WithdrawStatus] = None) -> list[WithdrawRequest]:
    ws = list(get_store().withdrawals.values())
    if status is not None:
        ws = [w for w in ws if w.status == status]
    return ws


async def resolve_withdraw(request_id: str, decision: str) -> Optional[WithdrawRequest]:
    s = get_store()
    w = s.withdrawals.get(request_id)
    if not w or w.status != WithdrawStatus.PENDING:
        return None
    if decision == "paid":
        admin = s.admins.get(str(w.admin_telegram_id))
        if admin and admin.balance_confirmed >= w.amount:
            admin.balance_confirmed -= w.amount
            w.status = WithdrawStatus.PAID
            w.resolved_at = datetime.utcnow()
        else:
            return None
    elif decision == "rejected":
        w.status = WithdrawStatus.REJECTED
        w.resolved_at = datetime.utcnow()
    await save()
    return w


# --------------------------------------------------------------------------
# CPM
# --------------------------------------------------------------------------

def get_cpm() -> CPMSetting:
    return get_store().cpm


async def update_cpm(mode: str, current_cpm: float, cycle_duration_hours: int,
                     updated_by: int) -> CPMSetting:
    from models import CPMMode
    s = get_store()
    s.cpm = CPMSetting(
        mode=CPMMode(mode),
        current_cpm=current_cpm,
        cycle_duration_hours=cycle_duration_hours,
        cycle_started_at=datetime.utcnow(),
        cycle_id=_id(),
        updated_at=datetime.utcnow(),
        updated_by=updated_by,
    )
    audit("cpm_updated", **{"mode": mode, "current_cpm": current_cpm,
                            "cycle_duration_hours": cycle_duration_hours,
                            "updated_by": updated_by})
    await save()
    return s.cpm
