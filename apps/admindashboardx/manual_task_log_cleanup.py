from datetime import timedelta


from django.db.models import Count
from django.utils import timezone

from .models import ManualTaskLog, ManualTaskRun

LOG_COUNT_LIMIT = 10_000
AGE_PRESET_DAYS = (3, 5, 10)

PURGE_MODES = {
    "logs_older_than_3d": ("Логи старше 3 дней", "logs_by_age", 3),
    "logs_older_than_5d": ("Логи старше 5 дней", "logs_by_age", 5),
    "logs_older_than_10d": ("Логи старше 10 дней", "logs_by_age", 10),
    "trim_logs_to_10000": ("Сократить до 10 000 записей", "trim_to_limit", LOG_COUNT_LIMIT),
    "runs_completed_older_than_3d": ("Запуски (завершённые) старше 3 дней", "runs_by_age", 3),
    "runs_completed_older_than_5d": ("Запуски (завершённые) старше 5 дней", "runs_by_age", 5),
    "runs_completed_older_than_10d": ("Запуски (завершённые) старше 10 дней", "runs_by_age", 10),
    "orphan_runs": ("Пустые запуски без логов", "orphan_runs", None),
}


def get_manual_task_log_stats():
    now = timezone.now()
    total_logs = ManualTaskLog.objects.count()
    total_runs = ManualTaskRun.objects.count()
    age_counts = {
        days: ManualTaskLog.objects.filter(created_at__lt=now - timedelta(days=days)).count()
        for days in AGE_PRESET_DAYS
    }
    runs_age_counts = {
        days: ManualTaskRun.objects.filter(
            finished_at__lt=now - timedelta(days=days),
            status__in=(ManualTaskRun.STATUS_COMPLETED, ManualTaskRun.STATUS_FAILED),
        ).count()
        for days in AGE_PRESET_DAYS
    }
    orphan_runs = (
        ManualTaskRun.objects.annotate(log_count=Count("logs"))
        .filter(log_count=0)
        .exclude(status=ManualTaskRun.STATUS_RUNNING)
        .count()
    )
    return {
        "total_logs": total_logs,
        "total_runs": total_runs,
        "logs_over_limit": max(0, total_logs - LOG_COUNT_LIMIT),
        "logs_older_than": age_counts,
        "runs_completed_older_than": runs_age_counts,
        "orphan_runs": orphan_runs,
        "log_count_limit": LOG_COUNT_LIMIT,
    }


def _purge_orphan_runs():
    return ManualTaskRun.objects.annotate(log_count=Count("logs")).filter(
        log_count=0,
    ).exclude(
        status=ManualTaskRun.STATUS_RUNNING,
    ).delete()[0]


def purge_logs_older_than_days(days: int) -> dict:
    cutoff = timezone.now() - timedelta(days=days)
    deleted_logs, _ = ManualTaskLog.objects.filter(created_at__lt=cutoff).delete()
    deleted_runs = _purge_orphan_runs()
    return {
        "deleted_logs": deleted_logs,
        "deleted_runs": deleted_runs,
        "message": f"Удалено логов: {deleted_logs}, пустых запусков: {deleted_runs}",
    }


def trim_logs_to_limit(limit: int = LOG_COUNT_LIMIT) -> dict:
    total = ManualTaskLog.objects.count()
    if total <= limit:
        return {
            "deleted_logs": 0,
            "deleted_runs": 0,
            "message": f"Логов {total} — лимит {limit} не превышен",
        }
    to_delete = total - limit
    oldest_ids = list(
        ManualTaskLog.objects.order_by("created_at", "id").values_list("id", flat=True)[:to_delete]
    )
    deleted_logs, _ = ManualTaskLog.objects.filter(id__in=oldest_ids).delete()
    deleted_runs = _purge_orphan_runs()
    return {
        "deleted_logs": deleted_logs,
        "deleted_runs": deleted_runs,
        "message": f"Удалено логов: {deleted_logs}, пустых запусков: {deleted_runs}",
    }


def purge_completed_runs_older_than_days(days: int) -> dict:
    cutoff = timezone.now() - timedelta(days=days)
    deleted, breakdown = ManualTaskRun.objects.filter(
        finished_at__lt=cutoff,
        status__in=(ManualTaskRun.STATUS_COMPLETED, ManualTaskRun.STATUS_FAILED),
    ).delete()
    deleted_logs = breakdown.get("admindashboardx.ManualTaskLog", 0)
    deleted_runs = breakdown.get("admindashboardx.ManualTaskRun", 0)
    return {
        "deleted_logs": deleted_logs,
        "deleted_runs": deleted_runs,
        "message": f"Удалено запусков: {deleted_runs}, логов: {deleted_logs}",
    }


def purge_orphan_runs() -> dict:
    deleted_runs = _purge_orphan_runs()
    return {
        "deleted_logs": 0,
        "deleted_runs": deleted_runs,
        "message": f"Удалено пустых запусков: {deleted_runs}",
    }


def execute_purge(mode: str) -> dict:
    if mode not in PURGE_MODES:
        raise ValueError(f"Неизвестный режим очистки: {mode}")

    _label, action, param = PURGE_MODES[mode]
    if action == "logs_by_age":
        return purge_logs_older_than_days(param)
    if action == "trim_to_limit":
        return trim_logs_to_limit(param)
    if action == "runs_by_age":
        return purge_completed_runs_older_than_days(param)
    if action == "orphan_runs":
        return purge_orphan_runs()
    raise ValueError(f"Неизвестное действие: {action}")


def purge_mode_available(mode: str, stats: dict) -> bool:
    if mode not in PURGE_MODES:
        return False
    _label, action, param = PURGE_MODES[mode]
    if action == "logs_by_age":
        return stats["logs_older_than"].get(param, 0) > 0
    if action == "trim_to_limit":
        return stats["logs_over_limit"] > 0
    if action == "runs_by_age":
        return stats["runs_completed_older_than"].get(param, 0) > 0
    if action == "orphan_runs":
        return stats["orphan_runs"] > 0
    return False
