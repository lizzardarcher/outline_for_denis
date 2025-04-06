from datetime import timedelta, datetime
from decimal import Decimal

from celery import shared_task
from django.conf import settings
from django.utils import timezone
from yookassa import Payment, Configuration

from bot.models import TelegramUser, Prices, Logging, Transaction, IncomeInfo, TelegramReferral, ReferralSettings


@shared_task
def attempt_recurring_payment():
    """
    Периодическая задача для списания средств с пользователей,
    у которых статус подписки False и есть payment_method_id.
    """
    users_to_charge = TelegramUser.objects.filter(
        subscription_status=False,
        payment_method_id__isnull=False,
        payment_method_id__gt='',
        permission_revoked=False
    )

    for user in users_to_charge:
        try:
            # Сумма списания
            amount_to_charge = Decimal(Prices.objects.get(pk=1).price_1)
            currency = 'RUB'

            # Настройка ЮKassa
            Configuration.account_id = settings.YOOKASSA_SHOP_ID_BOT
            Configuration.secret_key = settings.YOOKASSA_SECRET_BOT

            payment = Payment.create({
                "amount": {
                    "value": str(amount_to_charge),
                    "currency": currency
                },
                "capture": True,
                "payment_method_id": user.payment_method_id,
                "description": f"Рекуррентный платеж для пользователя {user.user_id}"
            })

            if payment.status == 'succeeded':

                # Успешный платеж
                user.subscription_status = True
                user.subscription_expiration = timezone.now().date() + timedelta(days=31)
                user.save()
                Transaction.objects.create(user=user, amount=amount_to_charge, currency=currency,
                                           side='Приход средств', status='succeeded', paid=True,
                                           income_info=IncomeInfo.objects.get(pk=1))
                msg = (
                    f"Автосписание успешно! Пользователь {user.user_id} оплатил с {str(amount_to_charge)} {currency}. "
                    f"Подписка активирована до {user.subscription_expiration}")

                referred_list = [x for x in TelegramReferral.objects.filter(referred=user)]
                if referred_list:
                    for r in referred_list:
                        user_to_pay = TelegramUser.objects.filter(user_id=r.referrer.user_id).first()
                        level = r.level
                        percent = None
                        if level == 1:
                            percent = ReferralSettings.objects.get(pk=1).level_1_percentage
                        elif level == 2:
                            percent = ReferralSettings.objects.get(pk=1).level_2_percentage
                        elif level == 3:
                            percent = ReferralSettings.objects.get(pk=1).level_3_percentage
                        elif level == 4:
                            percent = ReferralSettings.objects.get(pk=1).level_4_percentage
                        elif level == 5:
                            percent = ReferralSettings.objects.get(pk=1).level_5_percentage
                        if percent:
                            income = float(TelegramUser.objects.get(user_id=user_to_pay.user_id).income) + (
                                    float(amount_to_charge) * float(percent) / 100)
                            user.income = income
                            user.save()

                Logging.objects.create(log_level="SUCCESS", message=msg, datetime=datetime.now(), user=user)

            elif payment.status == 'waiting_for_capture' or payment.status == 'pending':
                # Платеж в процессе обработки
                msg = f"Платеж для пользователя {user.user_id} в статусе {payment.status}. Требуется дополнительная проверка."
                Logging.objects.create(log_level="WARNING", message=msg, datetime=datetime.now(), user=user)

            elif payment.status == 'canceled':
                # Платеж отменен
                cancellation_details = payment.cancellation_details
                reason = cancellation_details.reason if cancellation_details else "Unknown reason"

                # Обработка различных причин отмены
                message = f"Платеж отменен для пользователя {user.user_id}. Причина: {reason}. "  # Базовое сообщение

                if reason == 'insufficient_funds':
                    message += "Недостаточно средств для списания. Пополните баланс."

                elif reason == 'payment_method_restricted':
                    message += "Операции с платежным средством запрещены (карта заблокирована и т.п.). Обратитесь в банк."
                    user.payment_method_id = None
                    user.save()

                elif reason == 'permission_revoked':
                    message += "Вы отозвали разрешение на подписку. Подтвердите подписку заново."
                    user.payment_method_id = None
                    user.permission_revoked = True
                    user.save()

                elif reason == 'card_expired':
                    message += "Истек срок действия карты. Обновите данные карты."
                    user.payment_method_id = None
                    user.save()

                elif reason == 'country_forbidden':
                    message += "Нельзя заплатить банковской картой, выпущенной в этой стране. Используйте другую карту."
                    user.payment_method_id = None
                    user.save()

                elif reason == 'fraud_suspected':
                    message += "Платеж заблокирован из-за подозрения в мошенничестве. Свяжитесь с банком."

                elif reason == 'issuer_unavailable':
                    message += "Организация, выпустившая платежное средство, недоступна. Повторите попытку позже."

                elif reason == 'payment_method_limit_exceeded':
                    message += "Исчерпан лимит платежей для данного платежного средства или вашего магазина. Повторите попытку позже или используйте другое средство."

                elif reason == 'invalid_card_number':
                    message += "Неправильно указан номер карты. Обновите данные карты."

                elif reason == 'invalid_csc':
                    message += "Неправильно указан код CVV2 (CVC2, CID). Обновите данные карты."

                elif reason == 'call_issuer':
                    message += "Оплата отклонена по неизвестным причинам. Обратитесь в банк."

                elif reason == '3d_secure_failed':
                    message += "Не пройдена аутентификация по 3-D Secure. Повторите попытку, используя другое устройство или обратитесь в банк."

                elif reason == 'general_decline':
                    message += "Платеж отклонен. Обратитесь в банк."

                elif reason == 'expired_on_capture':
                    message += "Истек срок списания оплаты. Повторите попытку."

                elif reason == 'expired_on_confirmation':
                    message += "Истек срок оплаты: вы не подтвердили платеж. Повторите попытку."

                elif reason == 'deal_expired':
                    message += "Закончился срок жизни сделки. Создайте новую сделку и повторите оплату."

                elif reason == 'identification_required':
                    message += "Превышены ограничения на платежи для кошелька ЮMoney. Идентифицируйте кошелек или используйте другое средство."

                elif reason == 'internal_timeout':
                    message += "Технические неполадки. Повторите попытку позже."

                elif reason == 'canceled_by_merchant':
                    message += "Платеж отменен. Свяжитесь с поддержкой."
                else:
                    message += f"Неизвестная причина: {reason}"

                msg = message
                #  Отправляем сообщение пользователю
                # send_telegram_message(user.user_id, message) # Отправляем сообщение пользователю
                Logging.objects.create(log_level="WARNING", message=msg, datetime=datetime.now(), user=user)

            else:  # Другие статусы (например, 'waiting_for_capture')
                msg = f"Неизвестный статус платежа {payment.status} для пользователя {user.user_id}."
                Logging.objects.create(log_level="WARNING", message=msg, datetime=datetime.now(), user=user)

        except Exception as e:
            msg = f"Ошибка при списании с пользователя {user.user_id}: {e}"
            Logging.objects.create(log_level="FATAL", message=msg, datetime=datetime.now(), user=user)
