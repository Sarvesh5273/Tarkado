"""Add authoritative recovery/review/approval state; preserve existing data."""

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("company", "0003_mfa_security_state"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(name="EvidenceReview", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("reference", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
            ("created_at", models.DateTimeField()), ("data", models.JSONField()),
            ("company", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="company.company")),
            ("creator", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
        ]),
        migrations.CreateModel(name="PilotAuthorization", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("reference", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
            ("pilot_id", models.CharField(max_length=128)), ("data", models.JSONField()), ("revoked_at", models.DateTimeField(null=True)),
            ("approver", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ("company", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="company.company")),
            ("review", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="company.evidencereview")),
        ]),
        migrations.CreateModel(name="AuthorizedPilot", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("journal", models.JSONField()), ("activation_reason", models.CharField(max_length=1024)),
            ("activation_actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ("authorization", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, to="company.pilotauthorization")),
        ]),
        migrations.CreateModel(name="RecoveryGrant", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("reference", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
            ("kind", models.CharField(max_length=16)), ("digest", models.CharField(max_length=64, unique=True)),
            ("password_ref", models.CharField(max_length=64)), ("issued_at", models.DateTimeField()),
            ("expires_at", models.DateTimeField(null=True)), ("consumed_at", models.DateTimeField(null=True)),
            ("revoked_at", models.DateTimeField(null=True)),
            ("company", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="company.company")),
            ("issuer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="issued_recovery_grants", to=settings.AUTH_USER_MODEL)),
            ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="recovery_grants", to=settings.AUTH_USER_MODEL)),
        ]),
        migrations.AddConstraint(model_name="pilotauthorization", constraint=models.UniqueConstraint(
            fields=("company", "pilot_id"), name="company_unique_authorized_pilot")),
    ]
