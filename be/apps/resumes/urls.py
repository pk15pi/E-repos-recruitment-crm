from django.urls import path

from apps.resumes.api import (
    ResumeConfirmView,
    ResumeDetailView,
    ResumeDownloadView,
    ResumeDraftView,
    ResumeRetryView,
    ResumeStatusView,
    ResumeTextView,
    ResumeUploadView,
    SignedDownloadView,
)

urlpatterns = [
    path("resumes/upload/", ResumeUploadView.as_view(), name="resume-upload"),
    path("resumes/bulk/", ResumeUploadView.as_view(), name="resume-bulk"),
    path("resumes/signed/<str:token>/", SignedDownloadView.as_view(), name="resume-signed"),
    path("resumes/<uuid:resume_id>/", ResumeDetailView.as_view(), name="resume-detail"),
    path("resumes/<uuid:resume_id>/status/", ResumeStatusView.as_view(), name="resume-status"),
    path("resumes/<uuid:resume_id>/draft/", ResumeDraftView.as_view(), name="resume-draft"),
    path("resumes/<uuid:resume_id>/correct/", ResumeDraftView.as_view(), name="resume-correct"),
    path("resumes/<uuid:resume_id>/confirm/", ResumeConfirmView.as_view(), name="resume-confirm"),
    path("resumes/<uuid:resume_id>/retry/", ResumeRetryView.as_view(), name="resume-retry"),
    path("resumes/<uuid:resume_id>/download/", ResumeDownloadView.as_view(), name="resume-download"),
    path("resumes/<uuid:resume_id>/text/", ResumeTextView.as_view(), name="resume-text"),
]
