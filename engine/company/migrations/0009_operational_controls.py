import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("company", "0008_delivery_records")]
    operations = [migrations.CreateModel(name="OperationalControl", fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("journal", models.JSONField(default=list)),
        ("company", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, to="company.company")),
    ])]
