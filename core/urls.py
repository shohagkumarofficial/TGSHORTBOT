from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("api/auth/", views.api_auth, name="api_auth"),
    path("api/tasks/", views.api_tasks, name="api_tasks"),
    path("api/me/", views.api_me, name="api_me"),
    path("api/tasks/<str:task_id>/claim/", views.api_claim, name="api_claim"),
    path("api/withdraw/", views.api_withdraw, name="api_withdraw"),
    path("api/withdrawals/", views.api_my_withdrawals, name="api_my_withdrawals"),
]
