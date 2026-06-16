"""Реестр задач, доступных для ручного запуска из панели."""

MANUAL_TASKS = {
    "ukassa_bot_attempt_recurring_payment": {
        "title": "YooKassa Bot — рекуррентное списание",
        "description": (
            "Списание с пользователей бота (YooKassa Bot), у которых подписка неактивна "
            "и сохранён payment_method_id."
        ),
        "icon": "bi-robot",
        "celery_task_name": "apps.admindashboardx.tasks.manual_ukassa_bot_attempt_recurring_payment",
    },
    "ukassa_site_attempt_recurring_payment": {
        "title": "YooKassa Site — рекуррентное списание",
        "description": (
            "Списание с пользователей сайта (YooKassa Site), у которых подписка неактивна "
            "и сохранён payment_method_id."
        ),
        "icon": "bi-globe2",
        "celery_task_name": "apps.admindashboardx.tasks.manual_ukassa_site_attempt_recurring_payment",
    },
}

