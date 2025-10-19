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
    # ids = [8827810291215,]
    # users_to_charge = TelegramUser.objects.filter(user_id__in=ids)

    Logging.objects.create(log_level="INFO",
                           message=f'[CELERY] [Списание] [Начало] [количество пользователей: {users_to_charge.count()}]',
                           datetime=datetime.now())
    success = 0
    canceled = 0
    failed = 0
    unknown = 0

    for user in users_to_charge:
        if user.payment_method_id.__len__() > 10 and '000' in user.payment_method_id:
            try:
                # Сумма списания
                amount_to_charge = Decimal(Prices.objects.get(pk=1).price_1)
                currency = 'RUB'

                # Настройка ЮKassa
                Configuration.account_id = settings.YOOKASSA_SHOP_ID_BOT
                Configuration.secret_key = settings.YOOKASSA_SECRET_BOT

                try:
                    email = user.user_profile.user.email if user.user_profile.user.email else "noemail@noemail.ru"
                except:
                    email = "noemail@noemail.ru"

                payment = Payment.create({
                    "amount": {
                        "value": str(amount_to_charge),
                        "currency": currency
                    },
                    "capture": True,
                    "payment_method_id": user.payment_method_id,
                    "payment_method": {
                        "saved": True
                    },
                    "description": f"Рекуррентный платеж для пользователя {user.user_id} Подписка DomVPN",
                    "receipt": {
                        "customer": {
                            "email": email,
                        },
                        "items": [
                            {
                                "description": "Рекуррентный платеж",
                                "quantity": "1.00",
                                "amount": {
                                    "value": str(amount_to_charge),
                                    "currency": currency
                                },
                                "vat_code": 4,
                                "payment_subject": "service",
                                "payment_mode": "full_payment"
                            }
                        ]
                    }
                })

                if payment.status == 'succeeded':
                    success += 1
                    # Успешный платеж
                    user.subscription_status = True
                    user.subscription_expiration = timezone.now().date() + timedelta(days=31)
                    user.save()
                    Transaction.objects.create(user=user, amount=amount_to_charge, currency=currency,
                                               side='Приход средств', status='succeeded', paid=True,
                                               payment_id=payment.id,
                                               income_info=IncomeInfo.objects.get(pk=1),
                                               description='Рекуррентный платеж')
                    msg = (
                        f"[CELERY] Автосписание успешно! Пользователь {user.user_id} оплатил с {str(amount_to_charge)} {currency}. "
                        f""f"Подписка активирована до {user.subscription_expiration}"
                    )

                    REFERRAL_PERCENTAGES = {
                        1: ReferralSettings.objects.get(pk=1).level_1_percentage,
                        2: ReferralSettings.objects.get(pk=1).level_2_percentage,
                        3: ReferralSettings.objects.get(pk=1).level_3_percentage,
                        4: ReferralSettings.objects.get(pk=1).level_4_percentage,
                        5: ReferralSettings.objects.get(pk=1).level_5_percentage,
                    }

                    referred_list = TelegramReferral.objects.filter(referred=user).select_related('referrer')
                    if referred_list:
                        user_ids_to_pay = [r.referrer.user_id for r in referred_list]
                        users_to_pay = {u.user_id: u for u in TelegramUser.objects.filter(user_id__in=user_ids_to_pay)}

                        for r in referred_list:
                            level = r.level
                            user_to_pay = users_to_pay.get(r.referrer.user_id)
                            if not user_to_pay:
                                continue
                            percent = REFERRAL_PERCENTAGES.get(level)
                            if percent:
                                income = Decimal(user_to_pay.income) + (
                                            Decimal(amount_to_charge) * Decimal(percent) / 100)
                                user_to_pay.income = income
                                user_to_pay.save()

                    Logging.objects.create(log_level="SUCCESS", message=msg, datetime=datetime.now(), user=user)

                elif payment.status == 'waiting_for_capture' or payment.status == 'pending':
                    msg = f"[CELERY] Платеж для пользователя {user.user_id} в статусе {payment.status}. Требуется дополнительная проверка."
                    Logging.objects.create(log_level="WARNING", message=msg, datetime=datetime.now(), user=user)

                elif payment.status == 'canceled':
                    canceled += 1
                    cancellation_details = payment.cancellation_details
                    reason = cancellation_details.reason if cancellation_details else "Unknown reason"

                    message = f"[CELERY] Платеж отменен для пользователя {user.user_id}. Причина: {reason}. "

                    if reason == 'insufficient_funds':
                        message += "Недостаточно средств для списания. Пополните баланс."

                    elif reason == 'payment_method_restricted':
                        user.payment_method_id = ''
                        user.save()
                        message += "Операции с платежным средством запрещены (карта заблокирована и т.п.). Обратитесь в банк."

                    elif reason == 'permission_revoked':
                        user.payment_method_id = ''
                        user.permission_revoked = True
                        user.save()
                        message += "Вы отозвали разрешение на подписку. Подтвердите подписку заново."

                    elif reason == 'card_expired':
                        user.payment_method_id = ''
                        user.save()
                        message += "Истек срок действия карты. Обновите данные карты."

                    elif reason == 'country_forbidden':
                        user.payment_method_id = ''
                        user.save()
                        message += "Нельзя заплатить банковской картой, выпущенной в этой стране. Используйте другую карту."

                    elif reason == 'fraud_suspected':
                        user.payment_method_id = ''
                        user.save()
                        message += "Платеж заблокирован из-за подозрения в мошенничестве. Свяжитесь с банком."

                    elif reason == 'issuer_unavailable':
                        user.save()
                        message += "Организация, выпустившая платежное средство, недоступна. Повторите попытку позже."

                    elif reason == 'payment_method_limit_exceeded':
                        user.save()
                        message += "Исчерпан лимит платежей для данного платежного средства или вашего магазина. Повторите попытку позже или используйте другое средство."

                    elif reason == 'invalid_card_number':
                        user.payment_method_id = ''
                        user.save()
                        message += "Неправильно указан номер карты. Обновите данные карты."

                    elif reason == 'invalid_csc':
                        user.payment_method_id = ''
                        user.save()
                        message += "Неправильно указан код CVV2 (CVC2, CID). Обновите данные карты."

                    elif reason == 'call_issuer':
                        user.payment_method_id = ''
                        user.save()
                        message += "Оплата отклонена по неизвестным причинам. Обратитесь в банк."

                    elif reason == '3d_secure_failed':
                        user.payment_method_id = ''
                        user.save()
                        message += "Не пройдена аутентификация по 3-D Secure. Повторите попытку, используя другое устройство или обратитесь в банк."

                    elif reason == 'general_decline':
                        user.payment_method_id = ''
                        user.save()
                        message += "Платеж отклонен. Обратитесь в банк."

                    elif reason == 'expired_on_capture':
                        message += "Истек срок списания оплаты. Повторите попытку."

                    elif reason == 'expired_on_confirmation':
                        message += "Истек срок оплаты: вы не подтвердили платеж. Повторите попытку."

                    elif reason == 'deal_expired':
                        message += "Закончился срок жизни сделки. Создайте новую сделку и повторите оплату."

                    elif reason == 'identification_required':
                        user.payment_method_id = ''
                        user.save()
                        message += "Превышены ограничения на платежи для кошелька ЮMoney. Идентифицируйте кошелек или используйте другое средство."

                    elif reason == 'internal_timeout':
                        message += "Технические неполадки. Повторите попытку позже."

                    elif reason == 'canceled_by_merchant':
                        message += "Платеж отменен. Свяжитесь с поддержкой."

                    else:
                        message += f"Неизвестная причина: {reason}"

                    msg = message
                    Logging.objects.create(log_level="WARNING", message=msg, datetime=datetime.now(), user=user)

                else:
                    unknown += 1
                    msg = f"[CELERY] Неизвестный статус платежа {payment.status} для пользователя {user.user_id}."
                    user.payment_method_id = ''
                    user.save()
                    Logging.objects.create(log_level="WARNING", message=msg, datetime=datetime.now(), user=user)

            except Exception as e:
                failed += 1
                msg = f"[CELERY] Ошибка при списании с пользователя {user.user_id}: {e}\nPayment Method ID:{user.payment_method_id}"
                if "This payment_method_id doesn't exist" in msg:
                    user.payment_method_id = ''
                    user.save()
                elif 'Payment method is not available' in msg:
                    user.payment_method_id = ''
                    user.save()
                Logging.objects.create(log_level="FATAL", message=msg, datetime=datetime.now(), user=user)

    Logging.objects.create(
        log_level="INFO",
        message=f"[CELERY] [Списание] [Конец] [успешно: {str(success)} | отменено: {str(canceled)} | ошибка: {str(failed)} | неизвестно: {str(unknown)}]",
        datetime=datetime.now()
    )
