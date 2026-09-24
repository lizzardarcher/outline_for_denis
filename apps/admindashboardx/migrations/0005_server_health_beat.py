
from django.db import migrations


def ensure_health_check_task(apps, schema_editor):
    from django_celery_beat.models import IntervalSchedule, PeriodicTask

    schedule = IntervalSchedule.objects.filter(every=30, period=IntervalSchedule.MINUTES).first()
    if schedule is None:
        schedule = IntervalSchedule.objects.create(every=30, period=IntervalSchedule.MINUTES)
    PeriodicTask.objects.get_or_create(
        name="Проверка доступности VPN-серверов",
        defaults={
            "task": "admindashboardx.check_server_health",
            "interval": schedule,
            "enabled": True,
        },
    )


def remove_health_check_task(apps, schema_editor):
    from django_celery_beat.models import PeriodicTask

    PeriodicTask.objects.filter(name="Проверка доступности VPN-серверов").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("admindashboardx", "0004_server_health_log"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [
        migrations.RunPython(ensure_health_check_task, remove_health_check_task),
    ]
