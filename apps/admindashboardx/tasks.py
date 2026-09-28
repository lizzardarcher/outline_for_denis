from celery import shared_task

from bot.main.server_provision import provision_marzban_then_celerity
from bot.models import Server


@shared_task(name="admindashboardx.check_server_health")
def check_server_health():
    from apps.admindashboardx.panel_health import collect_and_store

    payload = collect_and_store()
    summary = payload.get("summary") or {}
    return {
        "checked_at": payload.get("checked_at"),
        "servers": summary.get("servers", 0),
        "ok": summary.get("ok", 0),
        "down": summary.get("down", 0),
        "ping_ok": summary.get("ping_ok", 0),
        "ping_down": summary.get("ping_down", 0),
    }

@shared_task(name="admindashboardx.initialize_server_task")
def initialize_server_task(server_id: int):
    """Кнопка инициализации: ss/vless (marzban-node), затем hysteria (Celerity + pinSHA256)."""
    server = Server.objects.select_related("country").get(id=server_id)
    provision_marzban_then_celerity(server, log_prefix="[ADMIN]")
    return None


@shared_task(bind=True, name="apps.admindashboardx.tasks.manual_ukassa_bot_attempt_recurring_payment")
def manual_ukassa_bot_attempt_recurring_payment(self, run_id: int):
    from .manual_task_runner import execute_manual_task_run

    return execute_manual_task_run(run_id, celery_task_id=self.request.id or "")


@shared_task(bind=True, name="apps.admindashboardx.tasks.manual_ukassa_site_attempt_recurring_payment")
def manual_ukassa_site_attempt_recurring_payment(self, run_id: int):
    from .manual_task_runner import execute_manual_task_run

    return execute_manual_task_run(run_id, celery_task_id=self.request.id or "")



@shared_task(bind=True, name="apps.admindashboardx.tasks.manual_cloudpayments_bot_attempt_recurring_payment")
def manual_cloudpayments_bot_attempt_recurring_payment(self, run_id: int):
    from .manual_task_runner import execute_manual_task_run

    return execute_manual_task_run(run_id, celery_task_id=self.request.id or "")


@shared_task(bind=True, name="apps.admindashboardx.tasks.manual_cloudpayments_site_attempt_recurring_payment")
def manual_cloudpayments_site_attempt_recurring_payment(self, run_id: int):
    from .manual_task_runner import execute_manual_task_run

    return execute_manual_task_run(run_id, celery_task_id=self.request.id or "")



@shared_task(bind=True, name="apps.admindashboardx.tasks.manual_cryptocloud_bot_attempt_recurring_payment")
def manual_cryptocloud_bot_attempt_recurring_payment(self, run_id: int):
    from .manual_task_runner import execute_manual_task_run

    return execute_manual_task_run(run_id, celery_task_id=self.request.id or "")


@shared_task(bind=True, name="apps.admindashboardx.tasks.manual_cryptocloud_site_attempt_recurring_payment")
def manual_cryptocloud_site_attempt_recurring_payment(self, run_id: int):
    from .manual_task_runner import execute_manual_task_run

    return execute_manual_task_run(run_id, celery_task_id=self.request.id or "")
