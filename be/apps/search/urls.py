from django.urls import path

from apps.search.api import (
    BooleanSearchView,
    HybridSearchView,
    InterpretView,
    SavedSearchDetailView,
    SavedSearchRunView,
    SavedSearchView,
    SearchHistoryView,
    StructuredSearchView,
)

urlpatterns = [
    path("search/structured/", StructuredSearchView.as_view(), name="search-structured"),
    path("search/boolean/", BooleanSearchView.as_view(), name="search-boolean"),
    path("search/interpret/", InterpretView.as_view(), name="search-interpret"),
    path("search/hybrid/", HybridSearchView.as_view(), name="search-hybrid"),
    path("search/saved/", SavedSearchView.as_view(), name="search-saved"),
    path("search/saved/<uuid:search_id>/", SavedSearchDetailView.as_view(), name="search-saved-detail"),
    path("search/saved/<uuid:search_id>/run/", SavedSearchRunView.as_view(), name="search-saved-run"),
    path("search/history/", SearchHistoryView.as_view(), name="search-history"),
]
