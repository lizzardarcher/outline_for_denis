from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admindashboardx", "0001_manual_task_models"),
    ]

    operations = [
        migrations.AddField(
            model_name="manualtaskrun",
            name="is_dry_run",
            field=models.BooleanField(default=False, verbose_name="Пробный запуск (dry-run)"),
        ),
    ]
