"""Initial individual-account and company-configuration storage."""

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name="LoginAttempt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("account_ref", models.CharField(db_index=True, max_length=64)),
                ("timestamp", models.DateTimeField()),
                ("result", models.CharField(max_length=16)),
            ],
        ),
        migrations.CreateModel(
            name="Company",
            fields=[
                ("id", models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
                ("company_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("deployment_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("name", models.CharField(max_length=128)),
                ("revision", models.PositiveIntegerField(default=1)),
                ("policy", models.JSONField()),
                ("repository_refs", models.JSONField()),
                ("collection_fields", models.JSONField()),
                ("company_api_attested", models.BooleanField(default=True)),
                ("retention_policy", models.CharField(default="manual", max_length=16)),
            ],
            options={"constraints": [models.CheckConstraint(condition=models.Q(("id", 1)), name="company_single_installation")]},
        ),
        migrations.CreateModel(
            name="Invitation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("invitation_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("username", models.CharField(max_length=64)),
                ("role", models.CharField(choices=[("junior", "Junior"), ("developer", "Developer"), ("senior", "Senior"), ("admin", "Administrator")], max_length=16)),
                ("participating", models.BooleanField()),
                ("can_manage_company", models.BooleanField()),
                ("can_approve_pilots", models.BooleanField()),
                ("digest", models.CharField(max_length=64, unique=True)),
                ("created_at", models.DateTimeField()),
                ("expires_at", models.DateTimeField()),
                ("consumed_at", models.DateTimeField(null=True)),
                ("revoked_at", models.DateTimeField(null=True)),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="company.company")),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="company_invitations", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="Membership",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("developer_id", models.CharField(max_length=64, unique=True)),
                ("role", models.CharField(choices=[("junior", "Junior"), ("developer", "Developer"), ("senior", "Senior"), ("admin", "Administrator")], max_length=16)),
                ("active", models.BooleanField(default=True)),
                ("participating", models.BooleanField(default=True)),
                ("can_manage_company", models.BooleanField(default=False)),
                ("can_approve_pilots", models.BooleanField(default=False)),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="company.company")),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="CompanyEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("revision", models.PositiveIntegerField()),
                ("actor_username", models.CharField(max_length=64)),
                ("timestamp", models.DateTimeField()),
                ("action", models.CharField(max_length=32)),
                ("details", models.JSONField()),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="company.company")),
            ],
            options={"ordering": ("revision",), "constraints": [models.UniqueConstraint(fields=("company", "revision"), name="company_event_revision")]},
        ),
    ]
