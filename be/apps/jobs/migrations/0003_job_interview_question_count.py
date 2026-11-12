from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("jobs", "0002_job_interview_levels"),
    ]

    operations = [
        migrations.AddField(
            model_name="job",
            name="interview_question_count",
            field=models.PositiveSmallIntegerField(default=5),
        ),
    ]
