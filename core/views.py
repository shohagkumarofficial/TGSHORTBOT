import json
import os

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from . import store, telegram_bot
from .telegram_auth import authenticate_request, is_owner


def index(request):
    context = {
        "monetag_zone": os.environ.get("MONETAG_ZONE_ID", "11646009"),
        "gigapub_id": os.environ.get("GIGAPUB_PROJECT_ID", "7860"),
    }
    return render(request, "core/index.html", context)


def _require_user(request):
    """Verified Telegram user dict রিটার্ন করে, নাহলে (None, error_response)।"""
    user = authenticate_request(request)
    if not user or "id" not in user:
        return None, JsonResponse(
            {"ok": False, "error": "invalid_init_data"}, status=401
        )
    return user, None


@require_POST
def api_auth(request):
    user, err = _require_user(request)
    if err:
        return err
    name = " ".join(filter(None, [user.get("first_name"), user.get("last_name")]))
    record = store.get_or_create_user(
        user["id"], name=name or user.get("username", "User"),
        username=user.get("username", ""),
    )
    return JsonResponse({"ok": True, "user": record, "is_owner": is_owner(user)})


@require_GET
def api_tasks(request):
    return JsonResponse({"ok": True, "tasks": store.list_tasks(active_only=True)})


@require_GET
def api_me(request):
    user, err = _require_user(request)
    if err:
        return err
    record = store.get_user(user["id"])
    if not record:
        return JsonResponse({"ok": False, "error": "not_found"}, status=404)
    return JsonResponse({"ok": True, "user": record, "is_owner": is_owner(user)})


@require_POST
def api_claim(request, task_id):
    user, err = _require_user(request)
    if err:
        return err
    tg_id = user["id"]

    task = store.get_task(task_id)
    if not task or not task.get("active"):
        return JsonResponse({"ok": False, "error": "task_not_found"}, status=404)
    if store.has_completed(tg_id, task_id):
        return JsonResponse({"ok": False, "error": "already_claimed"}, status=400)
    if task.get("max_claims") and task["claims_count"] >= task["max_claims"]:
        return JsonResponse({"ok": False, "error": "task_full"}, status=400)

    verify_type = task.get("verify_type", "manual")
    if verify_type == "channel_join":
        chat_id = task.get("chat_id")
        if not chat_id or not telegram_bot.check_channel_membership(chat_id, tg_id):
            return JsonResponse({"ok": False, "error": "not_joined"}, status=400)
    # manual ও ad_watch টাইপে ফ্রন্টএন্ড নিজেই (ad SDK এর success callback এর পরে) claim কল করে

    if not store.mark_task_completed(tg_id, task_id):
        return JsonResponse({"ok": False, "error": "claim_failed"}, status=400)

    record = store.add_coins(tg_id, task["reward"])
    return JsonResponse(
        {"ok": True, "coins": record["coins"], "reward": task["reward"]}
    )


@require_GET
def api_my_withdrawals(request):
    user, err = _require_user(request)
    if err:
        return err
    return JsonResponse(
        {"ok": True, "withdrawals": store.list_user_withdrawals(user["id"])}
    )


@require_POST
def api_withdraw(request):
    user, err = _require_user(request)
    if err:
        return err
    try:
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        body = {}

    try:
        amount = int(body.get("amount", 0))
    except (TypeError, ValueError):
        amount = 0
    payment_info = (body.get("payment_info") or "").strip()

    if amount <= 0 or not payment_info:
        return JsonResponse({"ok": False, "error": "invalid_input"}, status=400)

    tg_id = user["id"]
    record = store.get_user(tg_id)
    if not record or record["coins"] < amount:
        return JsonResponse({"ok": False, "error": "insufficient_coins"}, status=400)
    if not store.deduct_coins(tg_id, amount):
        return JsonResponse({"ok": False, "error": "insufficient_coins"}, status=400)

    w = store.create_withdrawal(tg_id, amount, payment_info)
    return JsonResponse(
        {"ok": True, "withdrawal": w, "coins": store.get_user(tg_id)["coins"]}
    )
