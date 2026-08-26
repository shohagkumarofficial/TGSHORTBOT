from django.urls import include, path

urlpatterns = [
    path("", include("core.urls")),
    path("admin-api/", include("adminpanel.urls")),
]
