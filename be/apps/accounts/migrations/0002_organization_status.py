from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="status",
            field=models.CharField(
                choices=[
                    ("active", "Active"),
                    ("past_due", "Payment past due"),
                    ("inactive", "Inactive"),
                ],
                default="active",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="organization",
            name="status_reason",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="organization",
            name="status_changed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
