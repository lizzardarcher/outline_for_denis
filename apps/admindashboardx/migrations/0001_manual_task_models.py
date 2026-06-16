# Generated manually for admindashboardx manual task models

import django.conf
import django.db.models.deletion
from django.db import migrations, models



class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(django.conf.settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ManualTaskRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("task_key", models.CharField(db_index=True, max_length=128, verbose_name="Ключ задачи")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Ожидание"),
                            ("running", "В процессе"),
                            ("completed", "Завершено"),
                            ("failed", "Ошибка"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=16,
                        verbose_name="Статус",
                    ),
                ),
                ("celery_task_id", models.CharField(blank=True, default="", max_length=255, verbose_name="Celery task id")),
                ("started_at", models.DateTimeField(blank=True, null=True, verbose_name="Начало")),
                ("finished_at", models.DateTimeField(blank=True, null=True, verbose_name="Конец")),
                ("summary", models.TextField(blank=True, default="", verbose_name="Итог")),
                ("error_message", models.TextField(blank=True, default="", verbose_name="Ошибка")),
                (
                    "started_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="manual_task_runs",
                        to=django.conf.settings.AUTH_USER_MODEL,
                        verbose_name="Запустил",
                    ),
                ),
            ],
            options={
                "verbose_name": "Ручной запуск задачи",
                "verbose_name_plural": "Ручные запуски задач",
                "ordering": ("-id",),
            },
        ),
        migrations.CreateModel(
            name="ManualTaskLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "log_level",
                    models.CharField(
                        choices=[
                            ("TRACE", "TRACE"),
                            ("DEBUG", "DEBUG"),
                            ("INFO", "INFO"),
                            ("WARNING", "WARNING"),
                            ("FATAL", "FATAL"),
                            ("SUCCESS", "SUCCESS"),
                        ],
                        default="INFO",
                        max_length=16,
                        verbose_name="Уровень",
                    ),
                ),
                ("message", models.TextField(verbose_name="Сообщение")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Время")),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="logs",
                        to="admindashboardx.manualtaskrun",
                        verbose_name="Запуск",
                    ),
                ),
            ],
            options={
                "verbose_name": "Лог ручного запуска",
                "verbose_name_plural": "Логи ручных запусков",
                "ordering": ("id",),
            },
        ),
    ]
