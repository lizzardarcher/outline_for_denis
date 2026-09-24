from django.db import models
from django.utils import timezone

class ManualTaskRun(models.Model):
    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = (
        (STATUS_PENDING, "Ожидание"),
        (STATUS_RUNNING, "В процессе"),
        (STATUS_COMPLETED, "Завершено"),
        (STATUS_FAILED, "Ошибка"),
    )

    task_key = models.CharField(max_length=128, db_index=True, verbose_name="Ключ задачи")
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
        verbose_name="Статус",
    )
    celery_task_id = models.CharField(max_length=255, blank=True, default="", verbose_name="Celery task id")
    started_at = models.DateTimeField(null=True, blank=True, verbose_name="Начало")
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name="Конец")
    summary = models.TextField(blank=True, default="", verbose_name="Итог")
    error_message = models.TextField(blank=True, default="", verbose_name="Ошибка")
    is_dry_run = models.BooleanField(default=False, verbose_name="Пробный запуск (dry-run)")

    class Meta:
        verbose_name = "Ручной запуск задачи"
        verbose_name_plural = "Ручные запуски задач"
        ordering = ("-id",)


    def __str__(self):
        return f"{self.task_key} #{self.pk} ({self.status})"

    @property
    def task_title(self):
        from .manual_tasks import MANUAL_TASKS

        return MANUAL_TASKS.get(self.task_key, {}).get("title", self.task_key)

    def mark_running(self, celery_task_id=""):
        self.status = self.STATUS_RUNNING
        self.celery_task_id = celery_task_id or ""
        self.started_at = timezone.now()
        self.save(update_fields=["status", "celery_task_id", "started_at"])

    def mark_completed(self, summary=""):
        self.status = self.STATUS_COMPLETED
        self.finished_at = timezone.now()
        self.summary = summary or ""
        self.save(update_fields=["status", "finished_at", "summary"])

    def mark_failed(self, error_message=""):
        self.status = self.STATUS_FAILED
        self.finished_at = timezone.now()
        self.error_message = error_message or ""
        self.save(update_fields=["status", "finished_at", "error_message"])


class ManualTaskLog(models.Model):
    LOG_LEVEL = (
        ("TRACE", "TRACE"),
        ("DEBUG", "DEBUG"),
        ("INFO", "INFO"),
        ("WARNING", "WARNING"),
        ("FATAL", "FATAL"),
        ("SUCCESS", "SUCCESS"),
    )

    run = models.ForeignKey(
        ManualTaskRun,
        on_delete=models.CASCADE,
        related_name="logs",
        verbose_name="Запуск",
    )
    log_level = models.CharField(max_length=16, choices=LOG_LEVEL, default="INFO", verbose_name="Уровень")
    message = models.TextField(verbose_name="Сообщение")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Время")

    class Meta:
        verbose_name = "Лог ручного запуска"
        verbose_name_plural = "Логи ручных запусков"
        ordering = ("id",)

    def __str__(self):
        return f"[{self.log_level}] {self.message[:80]}"



class ServerHealthState(models.Model):
    CHANNEL_PANEL = "panel"
    CHANNEL_PING = "ping"
    CHANNEL_CHOICES = (
        (CHANNEL_PANEL, "Панели"),
        (CHANNEL_PING, "Сеть"),
    )

    server = models.ForeignKey(
        "bot.Server",
        on_delete=models.CASCADE,
        related_name="health_states",
        verbose_name="Сервер",
    )
    channel = models.CharField(max_length=16, choices=CHANNEL_CHOICES, verbose_name="Канал")
    status = models.CharField(max_length=16, verbose_name="Статус")
    detail = models.CharField(max_length=300, blank=True, default="", verbose_name="Детали")
    streak_started_at = models.DateTimeField(verbose_name="Статус с")
    last_checked_at = models.DateTimeField(verbose_name="Последняя проверка")
    last_ok_at = models.DateTimeField(null=True, blank=True, verbose_name="Последний успешный ответ")

    class Meta:
        verbose_name = "Состояние доступности сервера"
        verbose_name_plural = "Состояния доступности серверов"
        constraints = [
            models.UniqueConstraint(fields=["server", "channel"], name="admx_server_health_state_uniq"),
        ]

    def __str__(self):
        return f"{self.server_id} {self.channel} {self.status}"


class ServerHealthSample(models.Model):
    server = models.ForeignKey(
        "bot.Server",
        on_delete=models.CASCADE,
        related_name="health_samples",
        verbose_name="Сервер",
    )
    checked_at = models.DateTimeField(db_index=True, verbose_name="Время проверки")
    panel_status = models.CharField(max_length=16, verbose_name="Статус панелей")
    panel_detail = models.CharField(max_length=300, blank=True, default="", verbose_name="Детали панелей")
    ping_status = models.CharField(max_length=16, verbose_name="Статус ping")
    ping_detail = models.CharField(max_length=300, blank=True, default="", verbose_name="Детали ping")
    ping_ms = models.PositiveIntegerField(null=True, blank=True, verbose_name="Ping, мс")

    class Meta:
        verbose_name = "Проба доступности сервера"
        verbose_name_plural = "Пробы доступности серверов"
        ordering = ("-checked_at", "-id")
        indexes = [
            models.Index(fields=["server", "checked_at"]),
        ]

    def __str__(self):
        return f"{self.server_id} {self.checked_at:%Y-%m-%d %H:%M} panel={self.panel_status} ping={self.ping_status}"
