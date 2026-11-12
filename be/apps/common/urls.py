from django.urls import path

from apps.common.views import DashboardView, HealthView, OrganizationSettingsView, ReportsView

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("reports/", ReportsView.as_view(), name="reports"),
    path("settings/organization/", OrganizationSettingsView.as_view(), name="org-settings"),
]
