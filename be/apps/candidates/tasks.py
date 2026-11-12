from celery import shared_task

from apps.accounts.models import Organization
from apps.candidates.models import Candidate
from apps.candidates.services import purge_candidate
from django.utils import timezone


@shared_task
def retention_sweep():
    now = timezone.now()
    for organization in Organization.objects.all():
        cutoff = now - timezone.timedelta(days=organization.retention_days)
        doomed = Candidate.objects.filter(
            organization=organization,
            deletion_requested_at__isnull=False,
            deletion_requested_at__lte=cutoff,
        )
        for candidate in list(doomed):
            purge_candidate(candidate)
