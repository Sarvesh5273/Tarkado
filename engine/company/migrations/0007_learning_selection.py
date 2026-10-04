from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [("company", "0006_connector_records"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AddField(model_name="companytask", name="learning_snapshot", field=models.JSONField(null=True)),
        migrations.AddField(model_name="companytask", name="suggestion_context", field=models.JSONField(default=dict)),
        migrations.CreateModel(name="LearningPublication", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("reference", models.UUIDField(default=uuid.uuid4, unique=True, editable=False)),
            ("source_kind", models.CharField(max_length=16)), ("sequence", models.PositiveIntegerField()),
            ("created_at", models.DateTimeField()), ("data", models.JSONField()),
            ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ("company", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="company.company")),
            ("review", models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, to="company.evidencereview")),
        ], options={"ordering": ("sequence",)}),
        migrations.AddConstraint(model_name="learningpublication", constraint=models.UniqueConstraint(fields=("company", "source_kind", "sequence"), name="company_learner_publication_sequence")),
        migrations.CreateModel(name="ScopedSelectionRuntime", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("journal", models.JSONField()),
            ("authorization", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, to="company.pilotauthorization")),
        ]),
    ]
