"""
ইন-মেমরি ডাটা স্টোর।

কোনো ডাটাবেজ ব্যবহার করা হয়নি — সব ডাটা এই প্রসেসের RAM-এ থাকে, তাই
Render রিস্টার্ট/রি-ডিপ্লয় হলে সব ডাটা হারিয়ে যাবে। এজন্যই admin panel
এ Backup (ডাউনলোড) ও Restore (আপলোড) বাটন রাখা হয়েছে (দেখুন adminpanel/views.py)।

পরে সত্যিকারের DB (যেমন PostgreSQL + Django ORM) যোগ করতে চাইলে শুধু এই
ফাইলের ফাংশনগুলোর ভেতরের implementation বদলালেই হবে — বাকি কোড
(views.py) এই একই ফাংশন নাম/সিগনেচার ব্যবহার করে, তাই অক্ষত থাকবে।
"""

import threading
import time
import uuid

_lock = threading.RLock()

_data = {
    "users": {},        # tg_id(str) -> {...}
    "tasks": {},         # task_id(str) -> {...}
    "withdrawals": {},   # withdrawal_id(str) -> {...}
}


def _now():
    return int(time.time())


# ---------------------------------------------------------------------------
# USERS
# ---------------------------------------------------------------------------

def get_user(tg_id):
    with _lock:
        return _data["users"].get(str(tg_id))


def get_or_create_user(tg_id, name="", username=""):
    tg_id = str(tg_id)
    with _lock:
        user = _data["users"].get(tg_id)
        if user is None:
            user = {
                "tg_id": tg_id,
                "name": name,
                "username": username,
                "coins": 0,
                "completed_tasks": [],
                "joined_at": _now(),
            }
            _data["users"][tg_id] = user
        else:
            if name:
                user["name"] = name
            if username:
                user["username"] = username
        return user


def add_coins(tg_id, amount):
    tg_id = str(tg_id)
    with _lock:
        user = _data["users"].get(tg_id)
        if not user:
            return None
        user["coins"] = user.get("coins", 0) + int(amount)
        return user


def deduct_coins(tg_id, amount):
    tg_id = str(tg_id)
    with _lock:
        user = _data["users"].get(tg_id)
        if not user or user.get("coins", 0) < amount:
            return False
        user["coins"] -= int(amount)
        return True


def list_users():
    with _lock:
        return sorted(
            _data["users"].values(), key=lambda u: u["joined_at"], reverse=True
        )


# ---------------------------------------------------------------------------
# TASKS
# ---------------------------------------------------------------------------

def create_task(**kwargs):
    with _lock:
        task_id = uuid.uuid4().hex[:8]
        task = {
            "id": task_id,
            "title": kwargs.get("title", ""),
            "description": kwargs.get("description", ""),
            "type": kwargs.get("type", "link"),          # link | channel | ad | custom
            "link": kwargs.get("link", ""),
            "reward": int(kwargs.get("reward", 0) or 0),
            "active": bool(kwargs.get("active", True)),
            # manual | channel_join | ad_watch
            "verify_type": kwargs.get("verify_type", "manual"),
            "chat_id": kwargs.get("chat_id", ""),          # channel_join এর জন্য
            "ad_provider": kwargs.get("ad_provider", ""),  # monetag | gigapub
            "max_claims": kwargs.get("max_claims") or None,
            "claims_count": 0,
            "created_at": _now(),
        }
        _data["tasks"][task_id] = task
        return task


def update_task(task_id, **kwargs):
    with _lock:
        task = _data["tasks"].get(task_id)
        if not task:
            return None
        allowed = {
            "title", "description", "type", "link", "reward", "active",
            "verify_type", "chat_id", "ad_provider", "max_claims",
        }
        for k, v in kwargs.items():
            if k in allowed:
                task[k] = v
        return task


def delete_task(task_id):
    with _lock:
        return _data["tasks"].pop(task_id, None)


def get_task(task_id):
    with _lock:
        return _data["tasks"].get(task_id)


def list_tasks(active_only=False):
    with _lock:
        tasks = list(_data["tasks"].values())
    if active_only:
        tasks = [t for t in tasks if t.get("active")]
    return sorted(tasks, key=lambda t: t["created_at"], reverse=True)


def has_completed(tg_id, task_id):
    user = get_user(tg_id)
    return bool(user and task_id in user.get("completed_tasks", []))


def mark_task_completed(tg_id, task_id):
    tg_id = str(tg_id)
    with _lock:
        user = _data["users"].get(tg_id)
        task = _data["tasks"].get(task_id)
        if not user or not task:
            return False
        if task_id in user["completed_tasks"]:
            return False
        if task.get("max_claims") and task["claims_count"] >= task["max_claims"]:
            return False
        user["completed_tasks"].append(task_id)
        task["claims_count"] += 1
        return True


# ---------------------------------------------------------------------------
# WITHDRAWALS
# ---------------------------------------------------------------------------

def create_withdrawal(tg_id, amount, payment_info):
    with _lock:
        wid = uuid.uuid4().hex[:8]
        w = {
            "id": wid,
            "tg_id": str(tg_id),
            "amount": int(amount),
            "payment_info": payment_info,
            "status": "pending",   # pending | approved | rejected
            "requested_at": _now(),
        }
        _data["withdrawals"][wid] = w
        return w


def get_withdrawal(wid):
    with _lock:
        return _data["withdrawals"].get(wid)


def list_withdrawals(status=None):
    with _lock:
        ws = list(_data["withdrawals"].values())
    if status:
        ws = [w for w in ws if w["status"] == status]
    return sorted(ws, key=lambda w: w["requested_at"], reverse=True)


def list_user_withdrawals(tg_id):
    tg_id = str(tg_id)
    with _lock:
        ws = [w for w in _data["withdrawals"].values() if w["tg_id"] == tg_id]
    return sorted(ws, key=lambda w: w["requested_at"], reverse=True)


def update_withdrawal_status(wid, status):
    with _lock:
        w = _data["withdrawals"].get(wid)
        if not w:
            return None
        w["status"] = status
        return w


# ---------------------------------------------------------------------------
# BACKUP / RESTORE  (admin panel থেকে ব্যবহৃত হয়)
# ---------------------------------------------------------------------------

def export_data():
    with _lock:
        return {
            "exported_at": _now(),
            "users": _data["users"],
            "tasks": _data["tasks"],
            "withdrawals": _data["withdrawals"],
        }


def import_data(payload):
    with _lock:
        _data["users"] = payload.get("users", {}) or {}
        _data["tasks"] = payload.get("tasks", {}) or {}
        _data["withdrawals"] = payload.get("withdrawals", {}) or {}
    return True


def stats():
    with _lock:
        return {
            "total_users": len(_data["users"]),
            "total_tasks": len(_data["tasks"]),
            "active_tasks": len([t for t in _data["tasks"].values() if t.get("active")]),
            "pending_withdrawals": len(
                [w for w in _data["withdrawals"].values() if w["status"] == "pending"]
            ),
            "total_coins_in_circulation": sum(
                u.get("coins", 0) for u in _data["users"].values()
            ),
        }
