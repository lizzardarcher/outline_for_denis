#!/usr/bin/env python
"""
Скрипт для получения информации о платеже RoboKassa по payment_id.

Использование:
    python check.py <payment_id>

Где payment_id может быть:
    - InvId (внутренний ID транзакции в системе)
    - ID Robox (ID платежа в системе RoboKassa)
"""

import sys
import os
import django
from pathlib import Path

# Добавляем корневую директорию проекта в путь
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

# Инициализация Django
os.environ['DJANGO_SETTINGS_MODULE'] = 'outline_for_denis.settings'
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
django.setup()

from django.conf import settings
from bot.models import Transaction


def get_robokassa_payment_info(inv_id: str, merchant_login: str, password_2: str):
    """Информация о платеже через общий OpStateExt-парсер."""
    from apps.payment.robokassa_subscription import fetch_robokassa_opstate

    print("  Запрос к API RoboKassa (OpStateExt)...")
    print(f"    MerchantLogin: {merchant_login}")
    print(f"    InvoiceID: {inv_id}")
    result = fetch_robokassa_opstate(inv_id, merchant_login, password_2)
    if result:
        print(f"  ✓ XML успешно распарсен: {result}")
    else:
        print("  ❌ Не удалось получить OpState")
    return result



def get_state_description(state: str) -> str:
    """Описание State.Code из документации RoboKassa OpStateExt."""
    states = {
        "5": "Инициализирована, оплата не подтверждена",
        "10": "Отменена",
        "20": "HOLD",
        "50": "Средства получены, зачисление",
        "60": "Отказ в зачислении, деньги возвращены",
        "80": "Приостановлена",
        "100": "Оплачен",
    }
    return states.get(state, f"Неизвестное состояние ({state})")


def main():
    if len(sys.argv) < 2:
        print("Использование: python check.py <payment_id>")
        print("\nГде payment_id может быть:")
        print("  - InvId (внутренний ID транзакции в системе)")
        print("  - ID Robox (ID платежа в системе RoboKassa)")
        sys.exit(1)

    payment_id = sys.argv[1]
    print(f"\n{'=' * 60}")
    print(f"Проверка платежа RoboKassa: {payment_id}")
    print(f"{'=' * 60}\n")

    # Пытаемся найти транзакцию по payment_id
    transaction = None

    # Сначала пробуем найти по payment_id (может быть ID Robox)
    transaction = Transaction.objects.filter(payment_id=payment_id).first()

    if transaction:
        print(f"✓ Транзакция найдена по payment_id:")
        print(f"  ID транзакции: {transaction.id}")
        print(f"  Payment ID: {transaction.payment_id}")
        print(f"  Статус: {transaction.status}")
        print(f"  Оплачено: {transaction.paid}")
        print(f"  Сумма: {transaction.amount} {transaction.currency}")
        print(f"  Пользователь: {transaction.user}")
        print(f"  Payment System: {transaction.payment_system}")
        inv_id = str(transaction.id)
    else:
        # Пробуем найти по ID транзакции (InvId)
        try:
            inv_id_int = int(payment_id)
            transaction = Transaction.objects.filter(id=inv_id_int).first()

            if transaction:
                print(f"✓ Транзакция найдена по ID:")
                print(f"  ID транзакции: {transaction.id}")
                print(f"  Payment ID: {transaction.payment_id}")
                print(f"  Статус: {transaction.status}")
                print(f"  Оплачено: {transaction.paid}")
                print(f"  Сумма: {transaction.amount} {transaction.currency}")
                print(f"  Пользователь: {transaction.user}")
                print(f"  Payment System: {transaction.payment_system}")
                inv_id = str(transaction.id)
            else:
                print(f"⚠ Транзакция не найдена в базе данных.")
                print(f"  Пробуем запросить информацию напрямую по InvId: {payment_id}")
                inv_id = payment_id
        except ValueError:
            print(f"⚠ Не удалось найти транзакцию и payment_id не является числом.")
            print(f"  Пробуем запросить информацию напрямую по InvId: {payment_id}")
            inv_id = payment_id

    print(f"\n{'─' * 60}")
    print("Запрос информации через API RoboKassa")
    print(f"{'─' * 60}\n")

    # Определяем, какой магазин использовать
    if transaction and transaction.payment_system in ['RoboKassaBot', 'RoboKassaSite']:
        if 'Bot' in transaction.payment_system:
            merchant_login = getattr(settings, 'ROBOKASSA_MERCHANT_LOGIN_BOT', None)
            password_2 = getattr(settings, 'ROBOKASSA_PASSWORD_2_BOT', None)
            store_type = "Bot"
        else:
            merchant_login = getattr(settings, 'ROBOKASSA_MERCHANT_LOGIN_SITE', None)
            password_2 = getattr(settings, 'ROBOKASSA_PASSWORD_2_SITE', None)
            store_type = "Site"
    else:
        # Если транзакция не найдена или payment_system не указан, пробуем оба
        print("  ⚠ Не удалось определить магазин, пробуем Bot магазин...")
        merchant_login = getattr(settings, 'ROBOKASSA_MERCHANT_LOGIN_BOT', None)
        password_2 = getattr(settings, 'ROBOKASSA_PASSWORD_2_BOT', None)
        store_type = "Bot"

    if not merchant_login or not password_2:
        print(f"  ❌ Ошибка: не найдены настройки для магазина {store_type}")
        print(f"    ROBOKASSA_MERCHANT_LOGIN_{store_type.upper()}: {merchant_login}")
        print(f"    ROBOKASSA_PASSWORD_2_{store_type.upper()}: {'установлен' if password_2 else 'не установлен'}")
        sys.exit(1)

    print(f"  Используется магазин: {store_type}")
    print(f"  MerchantLogin: {merchant_login}")

    # Запрашиваем информацию через API
    payment_info = get_robokassa_payment_info(
        inv_id=inv_id,
        merchant_login=merchant_login,
        password_2=password_2,
    )

    print(f"\n{'─' * 60}")
    print("Результат запроса")
    print(f"{'─' * 60}\n")

    if payment_info:
        print("✓ Информация получена успешно:\n")

        # Выводим все поля
        for key, value in payment_info.items():
            if key == "State":
                state_desc = get_state_description(value)
                print(f"  {key:20s}: {value} ({state_desc})")
            elif key == "RoboxID":
                print(f"  {key:20s}: {value} ⭐")
            else:
                print(f"  {key:20s}: {value}")

        # Дополнительная информация
        if payment_info.get("RoboxID"):
            print(f"\n  ⭐ ID Robox (PaymentID): {payment_info['RoboxID']}")

        state = payment_info.get("State")
        if state:
            print(f"\n  Статус платежа: {get_state_description(state)}")

        # Если есть транзакция, проверяем соответствие
        if transaction:
            print(f"\n{'─' * 60}")
            print("Сравнение с данными в базе")
            print(f"{'─' * 60}\n")

            if transaction.payment_id:
                if payment_info.get("RoboxID"):
                    if transaction.payment_id == payment_info["RoboxID"]:
                        print("  ✓ Payment ID в базе совпадает с ID Robox из API")
                    elif transaction.payment_id.startswith("ROBOX_INV_"):
                        print(f"  ⚠ Payment ID в базе: {transaction.payment_id} (fallback)")
                        print(f"     ID Robox из API: {payment_info['RoboxID']}")
                        print(f"     Рекомендуется обновить payment_id в базе на {payment_info['RoboxID']}")
                    else:
                        print(f"  ⚠ Payment ID в базе: {transaction.payment_id}")
                        print(f"     ID Robox из API: {payment_info['RoboxID']}")
                else:
                    print(f"  ⚠ ID Robox не получен из API, но в базе есть: {transaction.payment_id}")
            else:
                if payment_info.get("RoboxID"):
                    print(f"  ⚠ Payment ID в базе не установлен")
                    print(f"     ID Robox из API: {payment_info['RoboxID']}")
                    print(f"     Рекомендуется установить payment_id = {payment_info['RoboxID']}")
    else:
        print("❌ Не удалось получить информацию о платеже")
        print("\nВозможные причины:")
        print("  - Неверный InvId")
        print("  - Неверные настройки магазина (MerchantLogin/Password2)")
        print("  - Платеж не существует в системе RoboKassa")
        print("  - Проблемы с сетью или API RoboKassa")
        sys.exit(1)

    print(f"\n{'=' * 60}\n")


if __name__ == "__main__":
    main()

