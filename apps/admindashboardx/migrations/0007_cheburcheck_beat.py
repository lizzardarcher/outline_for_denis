
from django.db import migrations


def ensure_chebur_task(apps, schema_editor):
    from django_celery_beat.models import IntervalSchedule, PeriodicTask

    schedule = IntervalSchedule.objects.filter(every=30, period=IntervalSchedule.MINUTES).first()
    if schedule is None:
        schedule = IntervalSchedule.objects.create(every=30, period=IntervalSchedule.MINUTES)
    PeriodicTask.objects.get_or_create(
        name="Проверка Cheburcheck",
        defaults={
            "task": "admindashboardx.check_cheburcheck",
            "interval": schedule,
            "enabled": True,
        },
    )


def remove_chebur_task(apps, schema_editor):
    from django_celery_beat.models import PeriodicTask

    PeriodicTask.objects.filter(name="Проверка Cheburcheck").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("admindashboardx", "0006_server_health_chebur"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [
        migrations.RunPython(ensure_chebur_task, remove_chebur_task),
    ]
