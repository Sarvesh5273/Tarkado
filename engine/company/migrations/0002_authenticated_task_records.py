"""Add task history without replacing existing company accounts or configuration."""

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("company", "0001_initial"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(
            name="CompanyTask",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reference", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("task_id", models.CharField(max_length=128)),
                ("session_id", models.CharField(max_length=128)),
                ("repository_ref", models.CharField(max_length=1024)),
                ("source_kind", models.CharField(max_length=16)),
                ("request", models.JSONField()),
                ("policy_snapshot", models.JSONField()),
                ("revision", models.PositiveIntegerField(default=1)),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="company.company")),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="TaskEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sequence", models.PositiveIntegerField()),
                ("kind", models.CharField(max_length=16)),
                ("actor_snapshot", models.JSONField()),
                ("company_revision", models.PositiveIntegerField()),
                ("timestamp", models.DateTimeField()),
                ("payload", models.JSONField()),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ("task", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="events", to="company.companytask")),
            ],
            options={"ordering": ("sequence",)},
        ),
        migrations.AddConstraint(model_name="companytask", constraint=models.UniqueConstraint(
            fields=("company", "owner", "session_id", "task_id"), name="company_owned_task_identity")),
        migrations.AddConstraint(model_name="taskevent", constraint=models.UniqueConstraint(
            fields=("task", "sequence"), name="company_task_event_sequence")),
    ]
