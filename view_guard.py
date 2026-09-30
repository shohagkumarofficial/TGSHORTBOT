"""Server-side gate for the ad-lock flow.

The ad SDKs (Adsgram / Monetag / GigaPub) run entirely in the viewer's
browser, so the server can't literally see an ad being watched. What it
CAN do is make the two endpoints that pay out and reveal the destination
impossible to use without going through the page's flow:

  1. When viewer.html loads it calls POST /api/view-session and gets a
     signed, viewer-and-link-bound token (`issue`).
  2. POST /api/log-view must present that token, and it is only accepted
     after the minimum time a real viewer needs for that link's ads has
     passed (`redeem`). Each token is single use; re-sending the same
     token (network retry) is recognised and does NOT create a second
     View.
  3. GET /api/link/{code} only returns the destination for a viewer who
     just had a view logged for that link (`has_viewed`).

Tokens are stateless (HMAC signed with a key derived from BOT_TOKEN), so
they survive a restart; only the used-token / recent-view memory is in
RAM, which is fine for a single-instance deployment.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from typing import Dict, Optional, Tuple


class GuardError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class ViewGuard:
    def __init__(
        self,
        secret: str,
        token_ttl_seconds: int = 3600,
        max_active_per_viewer: int = 10,
        recent_view_window_seconds: int = 900,
    ):
        self._key = hashlib.sha256(b"tgshortbot-view-guard:" + secret.encode("utf-8")).digest()
        self.token_ttl = token_ttl_seconds
        self.max_active = max_active_per_viewer
        self.recent_window = recent_view_window_seconds
        self._active: Dict[int, Dict[str, float]] = {}
        self._used: Dict[str, float] = {}
        self._viewed: Dict[Tuple[int, str], float] = {}
        self._ops = 0

    # -- internals ---------------------------------------------------
    def _sign(self, payload: bytes) -> str:
        return hmac.new(self._key, payload, hashlib.sha256).hexdigest()[:32]

    def _prune(self, now: float) -> None:
        self._ops += 1
        if self._ops % 200:
            return
        self._used = {n: exp for n, exp in self._used.items() if exp > now}
        self._viewed = {k: t for k, t in self._viewed.items() if now - t <= self.recent_window}
        for viewer in list(self._active):
            live = {n: t for n, t in self._active[viewer].items() if now - t <= self.token_ttl}
            if live:
                self._active[viewer] = live
            else:
                del self._active[viewer]

    # -- public API --------------------------------------------------
    def issue(self, viewer_id: int, short_code: str, now: Optional[float] = None) -> str:
        now = time.time() if now is None else now
        self._prune(now)
        active = {n: t for n, t in self._active.get(viewer_id, {}).items() if now - t <= self.token_ttl}
        if len(active) >= self.max_active:
            raise GuardError("too_many_sessions", "too many open view sessions — finish or wait")
        nonce = secrets.token_hex(8)
        active[nonce] = now
        self._active[viewer_id] = active
        payload = f"{viewer_id}|{short_code}|{int(now)}|{nonce}".encode("utf-8")
        return _b64e(payload) + "." + self._sign(payload)

    def redeem(
        self,
        token: str,
        viewer_id: int,
        short_code: str,
        min_seconds: float,
        now: Optional[float] = None,
    ) -> str:
        """Returns "ok" for a fresh redemption or "replay" if this exact
        token was already redeemed (caller must not create another View).
        Raises GuardError otherwise."""
        now = time.time() if now is None else now
        self._prune(now)
        try:
            body, sig = token.split(".", 1)
            payload = _b64d(body)
            if not hmac.compare_digest(sig, self._sign(payload)):
                raise ValueError("bad signature")
            t_viewer, t_code, t_issued, nonce = payload.decode("utf-8").split("|", 3)
            t_viewer_i, t_issued_i = int(t_viewer), int(t_issued)
        except Exception:
            raise GuardError("bad_token", "invalid view session")
        if t_viewer_i != viewer_id or t_code != short_code:
            raise GuardError("bad_token", "view session does not match this viewer/link")

        age = now - t_issued_i
        if age > self.token_ttl:
            raise GuardError("expired", "view session expired — reopen the link")
        if nonce in self._used:
            return "replay"
        if age < min_seconds:
            raise GuardError("too_fast", "ads not finished yet")

        self._used[nonce] = t_issued_i + self.token_ttl
        self._active.get(viewer_id, {}).pop(nonce, None)
        return "ok"

    def mark_viewed(self, viewer_id: int, short_code: str, now: Optional[float] = None) -> None:
        self._viewed[(viewer_id, short_code)] = time.time() if now is None else now

    def has_viewed(self, viewer_id: int, short_code: str, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        t = self._viewed.get((viewer_id, short_code))
        return t is not None and now - t <= self.recent_window
