import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("company", "0007_learning_selection"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(name="GatewayCredential", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("reference", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
            ("gateway_id", models.CharField(max_length=128)), ("digest", models.CharField(max_length=64, unique=True)),
            ("scope", models.JSONField()), ("expires_at", models.DateTimeField()), ("revoked_at", models.DateTimeField(null=True)),
            ("company", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="company.company")),
            ("issuer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
        ]),
        migrations.CreateModel(name="DeliveryBinding", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("reference", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
            ("selection_id", models.CharField(max_length=128)), ("digest", models.CharField(max_length=64, unique=True)),
            ("data", models.JSONField()), ("journal", models.JSONField(default=list)),
            ("connector_task", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="delivery", to="company.connectortask")),
            ("gateway", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="company.gatewaycredential")),
            ("runtime", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="company.scopedselectionruntime")),
        ], options={"constraints": [models.UniqueConstraint(fields=("runtime", "selection_id"), name="delivery_one_selection_binding")]}),
    ]
