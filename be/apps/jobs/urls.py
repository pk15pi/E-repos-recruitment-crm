from django.urls import path

from apps.jobs.api import AnalyzeJobView, JobDetailView, JobListView, MatchListView, MatchView, RequirementView

urlpatterns = [
    path("jobs/", JobListView.as_view(), name="jobs"),
    path("jobs/analyze/", AnalyzeJobView.as_view(), name="jobs-analyze"),
    path("jobs/<uuid:job_id>/", JobDetailView.as_view(), name="job-detail"),
    path("jobs/<uuid:job_id>/requirements/", RequirementView.as_view(), name="job-requirements"),
    path("jobs/<uuid:job_id>/match/", MatchView.as_view(), name="job-match"),
    path("jobs/<uuid:job_id>/matches/", MatchListView.as_view(), name="job-matches"),
]
