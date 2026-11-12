from django.urls import path

from apps.clients.api import ClientDetailView, ClientListView, ContactView

urlpatterns = [
    path("clients/", ClientListView.as_view(), name="clients"),
    path("clients/<uuid:company_id>/", ClientDetailView.as_view(), name="client-detail"),
    path("clients/<uuid:company_id>/contacts/", ContactView.as_view(), name="client-contacts"),
    path("clients/<uuid:company_id>/contacts/<uuid:contact_id>/", ContactView.as_view(), name="client-contact"),
]
