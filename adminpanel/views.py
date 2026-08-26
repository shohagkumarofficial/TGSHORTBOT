import json

from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_GET, require_POST

from core import store
from core.telegram_auth import authenticate_request, is_owner


def _require_owner(request):
    """OWNER_TELEGRAM_ID এর সাথে মিললে user dict, নাহলে (None, 403 response)।"""
    user = authenticate_request(request)
    if not is_owner(user):
        return None, JsonResponse({"ok": False, "error": "forbidden"}, status=403)
    return user, None


@require_POST
def create_task(request):
    _, err = _require_owner(request)
    if err:
        return err
    try:
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "invalid_json"}, status=400)
    task = store.create_task(**body)
    return JsonResponse({"ok": True, "task": task})


@require_POST
def update_task(request, task_id):
    _, err = _require_owner(request)
    if err:
        return err
    try:
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "invalid_json"}, status=400)
    task = store.update_task(task_id, **body)
    if not task:
        return JsonResponse({"ok": False, "error": "not_found"}, status=404)
    return JsonResponse({"ok": True, "task": task})


@require_POST
def delete_task(request, task_id):
    _, err = _require_owner(request)
    if err:
        return err
    task = store.delete_task(task_id)
    return JsonResponse({"ok": True, "deleted": bool(task)})


@require_GET
def list_all_tasks(request):
    _, err = _require_owner(request)
    if err:
        return err
    return JsonResponse({"ok": True, "tasks": store.list_tasks()})


@require_GET
def list_users(request):
    _, err = _require_owner(request)
    if err:
        return err
    return JsonResponse({"ok": True, "users": store.list_users()})


@require_GET
def list_withdrawals(request):
    _, err = _require_owner(request)
    if err:
        return err
    status = request.GET.get("status")
    return JsonResponse({"ok": True, "withdrawals": store.list_withdrawals(status)})


@require_POST
def approve_withdrawal(request, wid):
    _, err = _require_owner(request)
    if err:
        return err
    w = store.update_withdrawal_status(wid, "approved")
    if not w:
        return JsonResponse({"ok": False, "error": "not_found"}, status=404)
    return JsonResponse({"ok": True, "withdrawal": w})


@require_POST
def reject_withdrawal(request, wid):
    _, err = _require_owner(request)
    if err:
        return err
    w = store.get_withdrawal(wid)
    if not w:
        return JsonResponse({"ok": False, "error": "not_found"}, status=404)
    if w["status"] == "pending":
        store.add_coins(w["tg_id"], w["amount"])  # কয়েন ফেরত
    w = store.update_withdrawal_status(wid, "rejected")
    return JsonResponse({"ok": True, "withdrawal": w})


@require_GET
def stats(request):
    _, err = _require_owner(request)
    if err:
        return err
    return JsonResponse({"ok": True, "stats": store.stats()})


@require_GET
def backup(request):
    _, err = _require_owner(request)
    if err:
        return err
    data = store.export_data()
    resp = HttpResponse(
        json.dumps(data, ensure_ascii=False, indent=2),
        content_type="application/json",
    )
    resp["Content-Disposition"] = 'attachment; filename="tgshort_backup.json"'
    return resp


@require_POST
def restore(request):
    _, err = _require_owner(request)
    if err:
        return err
    f = request.FILES.get("file")
    if not f:
        return JsonResponse({"ok": False, "error": "no_file"}, status=400)
    try:
        payload = json.loads(f.read().decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "invalid_json"}, status=400)
    store.import_data(payload)
    return JsonResponse({"ok": True, "stats": store.stats()})
