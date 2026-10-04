from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [("company", "0005_live_authority_history"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(name="ConnectorCredential", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("reference", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
            ("digest", models.CharField(max_length=64, unique=True)), ("name", models.CharField(max_length=128)),
            ("scope", models.JSONField()), ("issued_at", models.DateTimeField()), ("expires_at", models.DateTimeField()),
            ("revoked_at", models.DateTimeField(null=True)),
            ("company", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="company.company")),
            ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
        ]),
        migrations.CreateModel(name="ConnectorTask", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("reference", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
            ("client_task_id", models.UUIDField()), ("session_ref", models.CharField(max_length=64)),
            ("closed_at", models.DateTimeField(null=True)), ("sequence", models.PositiveIntegerField(default=0)),
            ("credential", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="company.connectorcredential")),
            ("task", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="connector_link", to="company.companytask")),
        ]),
        migrations.CreateModel(name="ConnectorObservation", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("event_id", models.UUIDField()), ("sequence", models.PositiveIntegerField()),
            ("received_at", models.DateTimeField()), ("actor_snapshot", models.JSONField()),
            ("payload", models.JSONField()), ("missing_before", models.PositiveIntegerField(default=0)),
            ("task", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="observations", to="company.connectortask")),
        ], options={"ordering": ("sequence",)}),
        migrations.AddConstraint(model_name="connectortask", constraint=models.UniqueConstraint(fields=("credential", "client_task_id"), name="connector_task_retry_identity")),
        migrations.AddConstraint(model_name="connectorobservation", constraint=models.UniqueConstraint(fields=("task", "event_id"), name="connector_event_retry_identity")),
        migrations.AddConstraint(model_name="connectorobservation", constraint=models.UniqueConstraint(fields=("task", "sequence"), name="connector_event_sequence")),
    ]
