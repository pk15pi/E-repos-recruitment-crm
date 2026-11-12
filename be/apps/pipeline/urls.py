from django.urls import path

from apps.pipeline.api import (
    InterviewAIReportView,
    InterviewFeedbackView,
    InterviewInviteView,
    InterviewJoinView,
    InterviewQuestionView,
    InterviewView,
    ShareRevokeView,
    ShareView,
    ShortlistItemView,
    ShortlistView,
    SubmissionDetailView,
    SubmissionListView,
)

urlpatterns = [
    path("submissions/", SubmissionListView.as_view(), name="submissions"),
    path("submissions/<uuid:submission_id>/", SubmissionDetailView.as_view(), name="submission-detail"),
    path("shares/", ShareView.as_view(), name="shares"),
    path("shares/<uuid:share_id>/revoke/", ShareRevokeView.as_view(), name="share-revoke"),
    path("shortlists/", ShortlistView.as_view(), name="shortlists"),
    path("shortlists/<uuid:shortlist_id>/items/", ShortlistItemView.as_view(), name="shortlist-items"),
    path("shortlists/<uuid:shortlist_id>/items/<uuid:candidate_id>/", ShortlistItemView.as_view(), name="shortlist-item"),
    path("interviews/", InterviewView.as_view(), name="interviews"),
    path("interviews/join/<str:token>/", InterviewJoinView.as_view(), name="interview-join"),
    path("interviews/<uuid:interview_id>/feedback/", InterviewFeedbackView.as_view(), name="interview-feedback"),
    path("interviews/<uuid:interview_id>/questions/", InterviewQuestionView.as_view(), name="interview-questions"),
    path("interviews/<uuid:interview_id>/invite/", InterviewInviteView.as_view(), name="interview-invite"),
    path("interviews/<uuid:interview_id>/ai-report/", InterviewAIReportView.as_view(), name="interview-ai-report"),
]
