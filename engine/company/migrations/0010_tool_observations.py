import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("company", "0009_operational_controls")]
    operations = [migrations.CreateModel(name="ToolObservation", fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("event_id", models.UUIDField()), ("sequence", models.PositiveIntegerField()),
        ("received_at", models.DateTimeField()), ("actor_snapshot", models.JSONField()),
        ("payload", models.JSONField()), ("missing_before", models.PositiveIntegerField(default=0)),
        ("binding", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="tool_observations", to="company.deliverybinding")),
    ], options={"ordering": ("sequence",), "constraints": [
        models.UniqueConstraint(fields=("binding", "event_id"), name="tool_observation_event_identity"),
        models.UniqueConstraint(fields=("binding", "sequence"), name="tool_observation_sequence"),
    ]})]
