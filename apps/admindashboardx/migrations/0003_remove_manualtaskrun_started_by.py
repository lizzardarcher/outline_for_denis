from django.db import migrations

class Migration(migrations.Migration):
    dependencies = [
        ("admindashboardx", "0002_manualtaskrun_is_dry_run"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="manualtaskrun",
            name="started_by",
        ),
    ]
