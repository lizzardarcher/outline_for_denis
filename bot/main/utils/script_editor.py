"""
Утилитарные одноразовые/отчётные скрипты (Django ORM).

Отчёт по логам Celery/YooKassa: «This payment_method_id doesn't exist».
Запуск из корня проекта:

    python manage.py shell -c \\
        "from bot.main.utils.script_editor import run_invalid_payment_method_report; run_invalid_payment_method_report()"
"""
from __future__ import annotations

import os
import re
from datetime import timedelta

import django
from django.utils import timezone


def _setup_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "outline_for_denis.settings")
    django.setup()


USER_ID_RE = re.compile(r"пользователя\s+(\d+)")
PAYMENT_METHOD_ID_RE = re.compile(r"Payment Method ID:\s*([0-9a-fA-F-]+)", re.I)



def run_invalid_payment_method_report(
    days: int = 60,
    needle: str = "This payment_method_id doesn't exist",
) -> None:
    """
    Логи за последние ``days`` дней (~2 месяца), содержащие ``needle``.
    Для каждого telegram user_id из лога:
      - берём самую свежую запись лога (чтобы один Payment Method ID);
      - оставляем только тех, у кого последняя *успешная* покупка (приход)
        была через ЮKassa Сайт.
    Печатает количество записей, затем по строке: пользователь, ID операции во внешней ПС,
    Payment Method ID из лога.
    """
    _setup_django()

    from bot.models import Logging, TelegramUser, Transaction

    since = timezone.now() - timedelta(days=days)
    logs = (
        Logging.objects.filter(datetime__gte=since, message__icontains=needle, log_level='FATAL')
        .order_by("-datetime")
        .iterator(chunk_size=500)
    )

    # user_id (Telegram) -> последняя по времени запись лога
    latest_by_uid: dict[int, Logging] = {}
    for log in logs:
        msg = log.message or ""
        um = USER_ID_RE.search(msg)
        pm = PAYMENT_METHOD_ID_RE.search(msg)
        if not um or not pm:
            continue
        uid = int(um.group(1))
        if uid not in latest_by_uid or log.datetime > latest_by_uid[uid].datetime:
            latest_by_uid[uid] = log

    if not latest_by_uid:
        print("Нет подходящих записей в логах за период.")
        print("Количество: 0")
        return

    rows: list[tuple[str, str, str]] = []

    counter = 1

    for tg_uid in sorted(latest_by_uid.keys()):
        log = latest_by_uid[tg_uid]
        msg = log.message or ""
        pm_match = PAYMENT_METHOD_ID_RE.search(msg)
        pm_from_log = (pm_match.group(1).strip() if pm_match else "").strip()

        try:
            user = TelegramUser.objects.get(user_id=tg_uid, permission_revoked=False, payment_method_id='')
        except TelegramUser.DoesNotExist:
            continue

        last_buy = (
            Transaction.objects.filter(
                user=user,
                side="Приход средств",
                status="succeeded",
                paid=True,
            )
            .order_by("-timestamp")
            .first()
        )
        if not last_buy or last_buy.payment_system != "YooKassaSite":
            continue

        user_label = f"{user}"
        ext_id = last_buy.payment_id or "—"
        rows.append((user_label, ext_id, pm_from_log))

    # print(f"Количество: {len(rows)}")
    # for user_label, ext_id, pm_from_log in rows:
        print(f"{counter} {user_label} | {ext_id == pm_from_log}")
        # user.payment_method_id = pm_from_log
        # user.save()
        counter += 1


if __name__ == "__main__":
    run_invalid_payment_method_report()
