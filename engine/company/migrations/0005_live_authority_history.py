"""Preserve immutable live decisions and ordered withdrawal without changing old journals."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("company", "0004_recovery_authorization"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AddField(model_name="pilotauthorization", name="authorization_revision", field=models.PositiveIntegerField(default=1)),
        migrations.CreateModel(
            name="AuthorizationEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sequence", models.PositiveIntegerField()),
                ("action", models.CharField(max_length=16)),
                ("timestamp", models.DateTimeField()),
                ("payload", models.JSONField()),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ("authorization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="authority_events", to="company.pilotauthorization")),
            ],
            options={"ordering": ("sequence",), "constraints": [models.UniqueConstraint(
                fields=("authorization", "sequence"), name="company_live_authority_event_sequence")]},
        ),
    ]
