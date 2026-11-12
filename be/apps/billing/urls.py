from django.urls import path

from apps.billing.api import (
    OrganizationSubscriptionView,
    PlanDetailView,
    PlanListView,
    PromoCodeDetailView,
    PromoCodeListView,
)

urlpatterns = [
    path("admin/plans/", PlanListView.as_view(), name="plans"),
    path("admin/plans/<uuid:plan_id>/", PlanDetailView.as_view(), name="plan-detail"),
    path("admin/promo-codes/", PromoCodeListView.as_view(), name="promo-codes"),
    path("admin/promo-codes/<uuid:promo_id>/", PromoCodeDetailView.as_view(), name="promo-code-detail"),
    path(
        "admin/organizations/<uuid:org_id>/subscription/",
        OrganizationSubscriptionView.as_view(),
        name="organization-subscription",
    ),
]
