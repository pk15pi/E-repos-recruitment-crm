import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("pipeline", "0002_interview_level_interview_outcome"),
    ]

    operations = [
        migrations.AddField(
            model_name="interview",
            name="kind",
            field=models.CharField(
                choices=[("manual", "Manual interview"), ("ai", "AI interview")],
                default="manual",
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="interview",
            name="question_source",
            field=models.CharField(
                blank=True,
                choices=[("random", "Generated from the requisition"), ("manual", "Written by the recruiter")],
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="interview",
            name="question_count",
            field=models.PositiveSmallIntegerField(default=5),
        ),
        migrations.AddField(
            model_name="interview",
            name="meeting_provider",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="interview",
            name="meeting_url",
            field=models.URLField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="interview",
            name="invited_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="interview",
            name="started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="interview",
            name="completed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="interview",
            name="ai_status",
            field=models.CharField(blank=True, max_length=16),
        ),
        migrations.AddField(
            model_name="interview",
            name="ai_feedback",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="interview",
            name="ai_recommendation",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="interview",
            name="ai_score",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="interview",
            name="ai_generated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="InterviewQuestion",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("prompt", models.TextField()),
                ("focus", models.CharField(blank=True, max_length=120)),
                ("source", models.CharField(default="manual", max_length=12)),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                ("answer", models.TextField(blank=True)),
                ("answered_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "interview",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="questions",
                        to="pipeline.interview",
                    ),
                ),
            ],
            options={"ordering": ["sort_order", "created_at"]},
        ),
    ]
