from django.contrib.postgres.operations import CreateExtension
from django.db import migrations
from pgvector.django import VectorExtension


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        CreateExtension("pg_trgm"),
        VectorExtension(),
    ]
