from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.candidates.api import CandidateViewSet, TaskViewSet

router = DefaultRouter()
router.register("candidates", CandidateViewSet, basename="candidate")
router.register("tasks", TaskViewSet, basename="task")

urlpatterns = router.urls
