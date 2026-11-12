import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_organization_status'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='contact_email',
            field=models.EmailField(blank=True, default='', max_length=254),
        ),
        migrations.CreateModel(
            name='GlobalDataGrant',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('scope', models.CharField(choices=[('resumes', 'Global resumes'), ('clients', 'Global clients'), ('customers', 'Global customers'), ('jds', 'Global job descriptions')], max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('granted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='global_grants', to='accounts.organization')),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('organization', 'scope'), name='uniq_global_grant_scope')],
            },
        ),
    ]
