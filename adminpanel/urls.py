from django.urls import path

from . import views

urlpatterns = [
    path("tasks/", views.list_all_tasks, name="admin_list_tasks"),
    path("tasks/create/", views.create_task, name="admin_create_task"),
    path("tasks/<str:task_id>/update/", views.update_task, name="admin_update_task"),
    path("tasks/<str:task_id>/delete/", views.delete_task, name="admin_delete_task"),
    path("users/", views.list_users, name="admin_list_users"),
    path("withdrawals/", views.list_withdrawals, name="admin_list_withdrawals"),
    path(
        "withdrawals/<str:wid>/approve/",
        views.approve_withdrawal,
        name="admin_approve_withdrawal",
    ),
    path(
        "withdrawals/<str:wid>/reject/",
        views.reject_withdrawal,
        name="admin_reject_withdrawal",
    ),
    path("stats/", views.stats, name="admin_stats"),
    path("backup/", views.backup, name="admin_backup"),
    path("restore/", views.restore, name="admin_restore"),
]
