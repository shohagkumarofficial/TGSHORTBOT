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
from datetime import datetime, timedelta, timezone

_lock = threading.RLock()

_data = {
    "users": {},        # tg_id(str) -> {...}
    "tasks": {},         # task_id(str) -> {...}
    "withdrawals": {},   # withdrawal_id(str) -> {...}
}

# বাংলাদেশ টাইমজোন (UTC+6, DST নেই) — ডেইলি রিসেট/চেক-ইন এই তারিখ অনুযায়ী হিসাব হয়
BD_TZ = timezone(timedelta(hours=6))

# ৭ দিনের চেক-ইন স্ট্রিক সাইকেল — reward বাড়তে থাকে, ৭ দিন পর আবার ঘোরে
CHECKIN_REWARDS = [10, 15, 20, 25, 30, 40, 60]


def _now():
    return int(time.time())


def _today_str():
    return datetime.now(BD_TZ).strftime("%Y-%m-%d")


def _yesterday_str():
    return (datetime.now(BD_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")


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
                "daily_claims": {},      # task_id -> "YYYY-MM-DD" (সর্বশেষ যেদিন claim হয়েছে)
                "last_checkin": None,    # "YYYY-MM-DD"
                "checkin_streak": 0,
                "total_checkins": 0,
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
            "daily": bool(kwargs.get("daily", False)),  # True হলে প্রতি ২৪ ঘন্টায় আবার claim করা যায়
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
            "verify_type", "chat_id", "ad_provider", "max_claims", "daily",
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
    """
    সাধারণ টাস্কের জন্য permanent completed_tasks লিস্ট চেক করে।
    ডেইলি টাস্কের জন্য আজকের তারিখে already claim হয়েছে কিনা চেক করে।
    """
    user = get_user(tg_id)
    task = _data["tasks"].get(task_id)
    if not user or not task:
        return False
    if task.get("daily"):
        return user.get("daily_claims", {}).get(task_id) == _today_str()
    return task_id in user.get("completed_tasks", [])


def mark_task_completed(tg_id, task_id):
    tg_id = str(tg_id)
    with _lock:
        user = _data["users"].get(tg_id)
        task = _data["tasks"].get(task_id)
        if not user or not task:
            return False

        if task.get("daily"):
            daily_claims = user.setdefault("daily_claims", {})
            today = _today_str()
            if daily_claims.get(task_id) == today:
                return False
            if task.get("max_claims") and task["claims_count"] >= task["max_claims"]:
                return False
            daily_claims[task_id] = today
            task["claims_count"] += 1
            return True

        if task_id in user["completed_tasks"]:
            return False
        if task.get("max_claims") and task["claims_count"] >= task["max_claims"]:
            return False
        user["completed_tasks"].append(task_id)
        task["claims_count"] += 1
        return True


# ---------------------------------------------------------------------------
# DAILY CHECK-IN
# ---------------------------------------------------------------------------

def get_checkin_status(tg_id):
    """একবার claim না করেই বর্তমান স্ট্রিক/পরবর্তী রিওয়ার্ড দেখানোর জন্য।"""
    user = get_user(tg_id)
    if not user:
        return None
    today = _today_str()
    checked_today = user.get("last_checkin") == today
    streak = user.get("checkin_streak", 0)
    if checked_today:
        next_streak = streak
    elif user.get("last_checkin") == _yesterday_str():
        next_streak = streak + 1
    else:
        next_streak = 1
    idx = min(next_streak - 1, len(CHECKIN_REWARDS) - 1)
    return {
        "checked_today": checked_today,
        "streak": streak,
        "total_checkins": user.get("total_checkins", 0),
        "next_reward": CHECKIN_REWARDS[idx],
    }


def checkin(tg_id):
    """আজকের চেক-ইন claim করে; আগে থেকেই করা থাকলে already=True রিটার্ন করে।"""
    tg_id = str(tg_id)
    with _lock:
        user = _data["users"].get(tg_id)
        if not user:
            return None
        today = _today_str()
        if user.get("last_checkin") == today:
            return {"already": True, "user": user}

        if user.get("last_checkin") == _yesterday_str():
            streak = user.get("checkin_streak", 0) + 1
        else:
            streak = 1

        idx = min(streak - 1, len(CHECKIN_REWARDS) - 1)
        reward = CHECKIN_REWARDS[idx]

        user["checkin_streak"] = streak
        user["last_checkin"] = today
        user["total_checkins"] = user.get("total_checkins", 0) + 1
        user["coins"] = user.get("coins", 0) + reward
        return {"already": False, "reward": reward, "streak": streak, "user": user}


# ---------------------------------------------------------------------------
# DEFAULT / SEED ডাটা
# ---------------------------------------------------------------------------

def seed_default_tasks():
    """
    প্রসেস প্রথম চালু হওয়ার সময় (in-memory স্টোর খালি থাকলে) একটা ডিফল্ট
    ডেইলি টাস্ক যোগ করে, যাতে অ্যাডমিন প্যানেলে কিছু না করেই ইউজাররা প্রথম
    থেকেই একটা কাজ করে কয়েন ইনকাম শুরু করতে পারে। App restart/redeploy হলে
    RAM খালি হয়ে যায় বলে এটা প্রতিবার process start এ আবার বসে যায়।
    """
    with _lock:
        if _data["tasks"]:
            return
        create_task(
            title="🎬 প্রতিদিন অ্যাড দেখে কয়েন নিন",
            description="প্রতি ২৪ ঘন্টায় একবার অ্যাড দেখে ফ্রি কয়েন নিতে পারবেন",
            type="ad",
            reward=20,
            verify_type="ad_watch",
            ad_provider="monetag",
            daily=True,
        )


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
