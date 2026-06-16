from .manual_tasks import MANUAL_TASKS
from .models import ManualTaskLog, ManualTaskRun
from .task_run_logging import TaskRunLogger
from .ukassa_recurring import run_ukassa_bot_recurring, run_ukassa_site_recurring

_TASK_RUNNERS = {
    "ukassa_bot_attempt_recurring_payment": (
        lambda logger, dry_run: run_ukassa_bot_recurring(logger, dry_run=dry_run),
        "BOT",
    ),
    "ukassa_site_attempt_recurring_payment": (
        lambda logger, dry_run: run_ukassa_site_recurring(logger, dry_run=dry_run),
        "SITE",
    ),
}

def execute_manual_task_run(run_id: int, *, celery_task_id=""):
    run = ManualTaskRun.objects.get(pk=run_id)
    if run.status not in (ManualTaskRun.STATUS_PENDING,):
        return run.summary or ""

    runner_entry = _TASK_RUNNERS.get(run.task_key)
    if not runner_entry:
        run.mark_failed(f"Неизвестная задача: {run.task_key}")
        ManualTaskLog.objects.create(
            run_id=run_id,
            log_level="FATAL",
            message=run.error_message,
        )
        return ""

    run_fn, channel = runner_entry
    run.mark_running(celery_task_id)
    worker_note = "синхронно в панели" if celery_task_id == "sync" else "воркером Celery"
    ManualTaskLog.objects.create(
        run_id=run_id,
        log_level="INFO",
        message=f"Задача принята {worker_note}.",
    )

    try:
        summary = run_fn(TaskRunLogger(run_id=run_id, channel=channel), run.is_dry_run)
        run.mark_completed(summary=summary)
        return summary
    except Exception as exc:
        run.mark_failed(str(exc))
        ManualTaskLog.objects.create(
            run_id=run_id,
            log_level="FATAL",
            message=f"Критическая ошибка задачи: {exc}",
        )
        raise


def queue_manual_task_run(run: ManualTaskRun):
    meta = MANUAL_TASKS.get(run.task_key) or {}
    celery_task_name = meta.get("celery_task_name")
    if not celery_task_name:
        raise ValueError(f"Для задачи {run.task_key} не задан celery_task_name")

    from celery import current_app

    current_app.send_task(celery_task_name, args=[run.id])
