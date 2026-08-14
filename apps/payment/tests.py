from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from django.conf import settings
from decimal import Decimal
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import hashlib

from bot.models import (
    TelegramUser, Transaction, IncomeInfo, Logging, Prices,
    TelegramReferral, ReferralSettings, ReferralTransaction, UserProfile
)


from apps.payment.robokassa_subscription import (
    classify_robokassa_opstate,
    parse_robokassa_opstate_xml,
    robokassa_md5 as subscription_robokassa_md5,
)
from apps.payment.views.robokassa import (
    robokassa_md5,
    CreateRobokassaPaymentView,
    RobokassaSiteResultView,
    RobokassaBotResultView,
    RobokassaSuccessView,
    RobokassaFailView,
    get_robokassa_payment_info,
)


User = get_user_model()


class RobokassaMD5Test(TestCase):
    """Тесты для функции создания MD5 подписи RoboKassa"""

    def test_robokassa_md5_basic(self):
        """Проверка базовой работы функции"""
        print("\n[TEST] Проверка базовой работы robokassa_md5...")
        test_input = "test_string"
        result = robokassa_md5(test_input)
        print(f"  Входная строка: {test_input}")
        print(f"  Результат MD5: {result}")
        print(f"  Длина: {len(result)} символов")
        
        self.assertEqual(len(result), 32)  # MD5 всегда 32 символа
        print("  ✓ Длина корректна (32 символа)")
        
        self.assertTrue(result.isupper())  # Должно быть в верхнем регистре
        print("  ✓ Регистр корректный (верхний)")
        
        self.assertTrue(all(c in '0123456789ABCDEF' for c in result))  # Только hex символы
        print("  ✓ Формат корректный (только hex символы)")

    def test_robokassa_md5_consistency(self):
        """Проверка консистентности - одинаковый вход = одинаковый выход"""
        print("\n[TEST] Проверка консистентности robokassa_md5...")
        input_str = "merchant:100.00:123:password"
        print(f"  Входная строка: {input_str}")
        
        result1 = robokassa_md5(input_str)
        print(f"  Первый вызов: {result1}")
        
        result2 = robokassa_md5(input_str)
        print(f"  Второй вызов: {result2}")
        
        self.assertEqual(result1, result2)
        print("  ✓ Результаты идентичны (консистентность подтверждена)")

    def test_robokassa_md5_signature_format(self):
        """Проверка формата подписи для ResultURL"""
        print("\n[TEST] Проверка формата подписи для ResultURL...")
        out_sum = "100.00"
        inv_id = "123"
        password_2 = "test_password"
        signature_string = f"{out_sum}:{inv_id}:{password_2}"
        print(f"  Формируем строку для подписи: {signature_string}")
        
        result = robokassa_md5(signature_string)
        print(f"  Подпись RoboKassa: {result}")
        
        # Проверяем, что это валидный MD5
        expected_md5 = hashlib.md5(signature_string.encode('utf-8')).hexdigest().upper()
        print(f"  Ожидаемый MD5: {expected_md5}")
        
        self.assertEqual(result, expected_md5)
        print("  ✓ Подпись соответствует стандартному MD5")


class CreateRobokassaPaymentViewTest(TestCase):
    """Тесты для создания платежа через RoboKassa на сайте"""

    def setUp(self):
        """Настройка тестовых данных"""
        self.client = Client()
        
        # Создаём пользователя Django
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Создаём TelegramUser
        self.telegram_user = TelegramUser.objects.create(
            user_id=123456789,
            username='testuser',
            first_name='Test',
            last_name='User',
            subscription_status=False,
        )
        
        # Создаём UserProfile и связываем
        self.user_profile = UserProfile.objects.create(
            user=self.user,
            telegram_user=self.telegram_user
        )
        
        # Создаём необходимые объекты
        IncomeInfo.objects.create(id=1, total_amount=Decimal('0.00'))
        Prices.objects.create(
            id=1,
            price_1=500,
            price_2=1400,
            price_3=2500,
            price_4=4500,
            price_5=25
        )
        

    def test_create_payment_requires_login(self):
        """Проверка, что требуется авторизация"""
        print("\n[TEST] Проверка требования авторизации для создания платежа...")
        response = self.client.post(reverse('create_payment_robokassa'), {
            'subscription': '500'
        })
        print(f"  Статус ответа: {response.status_code}")
        print(f"  Редирект на: {response.url if hasattr(response, 'url') else 'логин'}")
        self.assertEqual(response.status_code, 302)  # Редирект на логин
        print("  ✓ Требуется авторизация (редирект 302)")

    @patch('apps.payment.views.robokassa.settings.ROBOKASSA_MERCHANT_LOGIN_SITE', 'test_merchant')
    @patch('apps.payment.views.robokassa.settings.ROBOKASSA_PASSWORD_1_SITE', 'test_password')
    @patch('apps.payment.views.robokassa.settings.ROBOKASSA_ENDPOINT', 'https://auth.robokassa.ru/Merchant/Index.aspx')
    @patch('apps.payment.views.robokassa.settings.ROBOKASSA_IS_TEST', False)
    def test_create_payment_creates_transaction(self):
        """Проверка создания транзакции при создании платежа"""
        print("\n[TEST] Проверка создания транзакции при создании платежа...")
        self.client.force_login(self.user)
        
        initial_count = Transaction.objects.count()
        print(f"  Начальное количество транзакций: {initial_count}")
        
        response = self.client.post(reverse('create_payment_robokassa'), {
            'subscription': '500'
        })
        print(f"  Статус ответа: {response.status_code}")
        print(f"  Редирект на RoboKassa: {response.url if hasattr(response, 'url') else 'N/A'}")
        
        # Проверяем, что транзакция создана
        final_count = Transaction.objects.count()
        print(f"  Финальное количество транзакций: {final_count}")
        self.assertEqual(final_count, initial_count + 1)
        print("  ✓ Транзакция создана")
        
        transaction = Transaction.objects.latest('id')
        print(f"  ID транзакции: {transaction.id}")
        print(f"  Статус: {transaction.status}")
        print(f"  Сумма: {transaction.amount}")
        print(f"  Пользователь: {transaction.user}")
        print(f"  Валюта: {transaction.currency}")
        
        self.assertEqual(transaction.status, 'pending')
        self.assertEqual(transaction.paid, False)
        self.assertEqual(transaction.amount, Decimal('500'))
        self.assertEqual(transaction.user, self.telegram_user)
        self.assertEqual(transaction.currency, 'RUB')
        print("  ✓ Все поля транзакции корректны")

    @patch('apps.payment.views.robokassa.settings.ROBOKASSA_MERCHANT_LOGIN_SITE', 'test_merchant')
    @patch('apps.payment.views.robokassa.settings.ROBOKASSA_PASSWORD_1_SITE', 'test_password')
    @patch('apps.payment.views.robokassa.settings.ROBOKASSA_ENDPOINT', 'https://auth.robokassa.ru/Merchant/Index.aspx')
    @patch('apps.payment.views.robokassa.settings.ROBOKASSA_IS_TEST', False)
    def test_create_payment_redirects_to_robokassa(self):
        """Проверка редиректа на RoboKassa"""
        
        self.client.force_login(self.user)
        
        response = self.client.post(reverse('create_payment_robokassa'), {
            'subscription': '500'
        })
        
        # Проверяем редирект
        self.assertEqual(response.status_code, 302)
        self.assertTrue('auth.robokassa.ru' in response.url)
        self.assertTrue('MerchantLogin=test_merchant' in response.url)
        self.assertTrue('OutSum=500.00' in response.url)

    @patch('apps.payment.views.robokassa.settings.ROBOKASSA_MERCHANT_LOGIN_SITE', 'test_merchant')
    @patch('apps.payment.views.robokassa.settings.ROBOKASSA_PASSWORD_1_SITE', 'test_password')
    @patch('apps.payment.views.robokassa.settings.ROBOKASSA_ENDPOINT', 'https://auth.robokassa.ru/Merchant/Index.aspx')
    @patch('apps.payment.views.robokassa.settings.ROBOKASSA_IS_TEST', False)
    def test_create_payment_different_subscriptions(self):
        """Проверка создания платежей для разных тарифов"""
        
        self.client.force_login(self.user)
        
        test_cases = [
            ('500', 31),   # 1 месяц
            ('1400', 93),  # 3 месяца
            ('2500', 184), # 6 месяцев
            ('4500', 366), # 1 год
            ('25', 3),     # 3 дня
        ]
        
        for subscription, expected_days in test_cases:
            with self.subTest(subscription=subscription):
                response = self.client.post(reverse('create_payment_robokassa'), {
                    'subscription': subscription
                })
                
                transaction = Transaction.objects.latest('id')
                self.assertIn(f'{expected_days} дн.', transaction.description)


class RobokassaSiteResultViewTest(TestCase):
    """Тесты для обработки вебхука RoboKassa (сайт)"""

    def setUp(self):
        """Настройка тестовых данных"""
        self.client = Client()
        
        # Создаём TelegramUser
        self.telegram_user = TelegramUser.objects.create(
            user_id=123456789,
            username='testuser',
            first_name='Test',
            subscription_status=False,
            subscription_expiration=datetime.now().date() - timedelta(days=1)
        )
        
        # Создаём необходимые объекты
        IncomeInfo.objects.create(id=1, total_amount=Decimal('0.00'))
        Prices.objects.create(
            id=1,
            price_1=500,
            price_2=1400,
            price_3=2500,
            price_4=4500,
            price_5=25
        )
        ReferralSettings.objects.create(
            id=1,
            level_1_percentage=10,
            level_2_percentage=5,
            level_3_percentage=3,
            level_4_percentage=2,
            level_5_percentage=1
        )
        
        # Создаём транзакцию
        self.transaction = Transaction.objects.create(
            id=12345,
            status='pending',
            paid=False,
            amount=Decimal('500'),
            user=self.telegram_user,
            currency='RUB',
            income_info=IncomeInfo.objects.get(pk=1),
            side='Приход средств',
            description='Тестовая транзакция',
        )
        opstate_patcher = patch(
            'apps.payment.views.robokassa.get_robokassa_payment_info',
            return_value=None,
        )
        self.addCleanup(opstate_patcher.stop)
        opstate_patcher.start()
        

    @patch('apps.payment.views.robokassa.settings.ROBOKASSA_PASSWORD_2_SITE', 'test_password_2')
    def test_result_webhook_valid_signature(self):
        """Проверка обработки вебхука с валидной подписью"""
        print("\n[TEST] Проверка обработки вебхука с валидной подписью...")
        out_sum = "500.00"
        inv_id = str(self.transaction.id)
        signature = robokassa_md5(f"{out_sum}:{inv_id}:test_password_2")
        
        print(f"  Параметры вебхука:")
        print(f"    OutSum: {out_sum}")
        print(f"    InvId: {inv_id}")
        print(f"    SignatureValue: {signature}")
        
        response = self.client.post(reverse('robokassa_result_site'), {
            'OutSum': out_sum,
            'InvId': inv_id,
            'SignatureValue': signature,
        })
        
        # Проверяем ответ
        print(f"  Статус ответа: {response.status_code}")
        print(f"  Тело ответа: {response.content.decode()}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), f"OK{inv_id}")
        print("  ✓ Ответ корректный (OK{InvId})")
        
        # Проверяем обновление транзакции
        self.transaction.refresh_from_db()
        print(f"  Статус транзакции после обработки: {self.transaction.status}")
        print(f"  Оплачено: {self.transaction.paid}")
        print(f"  Сумма: {self.transaction.amount}")
        
        self.assertEqual(self.transaction.status, 'succeeded')
        self.assertEqual(self.transaction.paid, True)
        self.assertEqual(self.transaction.amount, Decimal('500.00'))
        print("  ✓ Транзакция обновлена корректно")
        
        # Проверяем обновление подписки
        self.telegram_user.refresh_from_db()
        print(f"  Статус подписки: {self.telegram_user.subscription_status}")
        print(f"  Дата окончания: {self.telegram_user.subscription_expiration}")
        
        self.assertEqual(self.telegram_user.subscription_status, True)
        self.assertGreater(self.telegram_user.subscription_expiration, datetime.now().date())
        print("  ✓ Подписка активирована")

    @patch('apps.payment.views.robokassa.settings.ROBOKASSA_PASSWORD_2_SITE', 'test_password_2')
    def test_result_webhook_accepts_get(self):
        out_sum = "500.00"
        inv_id = str(self.transaction.id)
        signature = robokassa_md5(f"{out_sum}:{inv_id}:test_password_2")
        response = self.client.get(
            reverse('robokassa_result_site'),
            {
                'OutSum': out_sum,
                'InvId': inv_id,
                'SignatureValue': signature,
            },
            secure=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), f"OK{inv_id}")
        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.status, 'succeeded')

    @patch('apps.payment.views.robokassa._complete_robokassa_result_payment', side_effect=RuntimeError('boom'))
    @patch('apps.payment.views.robokassa.settings.ROBOKASSA_PASSWORD_2_SITE', 'test_password_2')
    def test_result_webhook_processing_error_does_not_ack(self, _mock_complete):
        out_sum = "500.00"
        inv_id = str(self.transaction.id)
        signature = robokassa_md5(f"{out_sum}:{inv_id}:test_password_2")
        response = self.client.post(
            reverse('robokassa_result_site'),
            {
                'OutSum': out_sum,
                'InvId': inv_id,
                'SignatureValue': signature,
            },
            secure=True,
        )
        self.assertEqual(response.status_code, 500)
        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.status, 'pending')

    @patch('apps.payment.views.robokassa.settings.ROBOKASSA_PASSWORD_2_SITE', 'test_password_2')
    def test_result_webhook_invalid_signature(self):
        """Проверка отклонения вебхука с невалидной подписью"""
        print("\n[TEST] Проверка отклонения вебхука с невалидной подписью...")
        out_sum = "500.00"
        inv_id = str(self.transaction.id)
        wrong_signature = "INVALID_SIGNATURE"
        
        print(f"  Параметры вебхука:")
        print(f"    OutSum: {out_sum}")
        print(f"    InvId: {inv_id}")
        print(f"    SignatureValue: {wrong_signature} (невалидная)")
        
        response = self.client.post(reverse('robokassa_result_site'), {
            'OutSum': out_sum,
            'InvId': inv_id,
            'SignatureValue': wrong_signature,
        })
        
        # Проверяем, что запрос отклонён
        print(f"  Статус ответа: {response.status_code}")
        print(f"  Тело ответа: {response.content.decode()}")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.content.decode(), 'bad sign')
        print("  ✓ Запрос отклонён (403 bad sign)")
        
        # Транзакция не должна быть обновлена
        self.transaction.refresh_from_db()
        print(f"  Статус транзакции (не должен измениться): {self.transaction.status}")
        print(f"  Оплачено (не должно измениться): {self.transaction.paid}")
        self.assertEqual(self.transaction.status, 'pending')
        self.assertEqual(self.transaction.paid, False)
        print("  ✓ Транзакция не изменена (безопасность работает)")

    @patch('apps.payment.views.robokassa.settings.ROBOKASSA_PASSWORD_2_SITE', 'test_password_2')
    def test_result_webhook_missing_parameters(self):
        """Проверка обработки вебхука с отсутствующими параметрами"""
        print("\n[TEST] Проверка обработки вебхука с отсутствующими параметрами...")
        
        # Отсутствует OutSum
        print("  Тест 1: Отсутствует OutSum")
        response = self.client.post(reverse('robokassa_result_site'), {
            'InvId': '12345',
            'SignatureValue': 'test_signature',
        })
        print(f"    Статус ответа: {response.status_code}")
        self.assertEqual(response.status_code, 400)
        print("    ✓ Запрос отклонён (400)")
        
        # Отсутствует InvId
        print("  Тест 2: Отсутствует InvId")
        response = self.client.post(reverse('robokassa_result_site'), {
            'OutSum': '500.00',
            'SignatureValue': 'test_signature',
        })
        print(f"    Статус ответа: {response.status_code}")
        self.assertEqual(response.status_code, 400)
        print("    ✓ Запрос отклонён (400)")

    @patch('apps.payment.views.robokassa.settings.ROBOKASSA_PASSWORD_2_SITE', 'test_password_2')
    def test_result_webhook_nonexistent_transaction(self):
        """Проверка обработки вебхука для несуществующей транзакции"""
        print("\n[TEST] Проверка обработки вебхука для несуществующей транзакции...")
        out_sum = "500.00"
        inv_id = "99999"  # Несуществующий ID
        signature = robokassa_md5(f"{out_sum}:{inv_id}:test_password_2")
        
        print(f"  Параметры вебхука:")
        print(f"    OutSum: {out_sum}")
        print(f"    InvId: {inv_id} (несуществующий)")
        print(f"    SignatureValue: {signature}")
        
        response = self.client.post(reverse('robokassa_result_site'), {
            'OutSum': out_sum,
            'InvId': inv_id,
            'SignatureValue': signature,
        })
        
        # Должен вернуть OK, но транзакция не найдена
        print(f"  Статус ответа: {response.status_code}")
        print(f"  Тело ответа: {response.content.decode()}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), f"OK{inv_id}")
        print("  ✓ Ответ OK (транзакция не найдена, но подпись валидна)")

    @patch('apps.payment.views.robokassa.settings.ROBOKASSA_PASSWORD_2_SITE', 'test_password_2')
    def test_result_webhook_idempotency(self):
        """Проверка идемпотентности - повторная обработка не должна менять статус"""
        print("\n[TEST] Проверка идемпотентности вебхука...")
        
        # Первая обработка
        out_sum = "500.00"
        inv_id = str(self.transaction.id)
        signature = robokassa_md5(f"{out_sum}:{inv_id}:test_password_2")
        
        print("  Первая обработка вебхука...")
        response1 = self.client.post(reverse('robokassa_result_site'), {
            'OutSum': out_sum,
            'InvId': inv_id,
            'SignatureValue': signature,
        })
        print(f"    Статус ответа: {response1.status_code}")
        self.assertEqual(response1.status_code, 200)
        
        self.transaction.refresh_from_db()
        first_status = self.transaction.status
        first_paid = self.transaction.paid
        print(f"    Статус после первой обработки: {first_status}, оплачено: {first_paid}")
        
        # Вторая обработка (повторный запрос)
        print("  Вторая обработка вебхука (повторный запрос)...")
        response2 = self.client.post(reverse('robokassa_result_site'), {
            'OutSum': out_sum,
            'InvId': inv_id,
            'SignatureValue': signature,
        })
        print(f"    Статус ответа: {response2.status_code}")
        self.assertEqual(response2.status_code, 200)
        
        # Статус не должен измениться
        self.transaction.refresh_from_db()
        print(f"    Статус после второй обработки: {self.transaction.status}, оплачено: {self.transaction.paid}")
        self.assertEqual(self.transaction.status, first_status)
        self.assertEqual(self.transaction.paid, first_paid)
        print("  ✓ Идемпотентность подтверждена (статус не изменился)")

    @patch('apps.payment.views.robokassa.settings.ROBOKASSA_PASSWORD_2_SITE', 'test_password_2')
    def test_result_webhook_subscription_extension(self):
        """Проверка продления подписки при успешном платеже"""
        print("\n[TEST] Проверка продления подписки при успешном платеже...")
        
        # Устанавливаем активную подписку
        self.telegram_user.subscription_status = True
        self.telegram_user.subscription_expiration = datetime.now().date() + timedelta(days=10)
        self.telegram_user.save()
        
        old_expiration = self.telegram_user.subscription_expiration
        print(f"  Начальная дата окончания подписки: {old_expiration}")
        
        out_sum = "500.00"
        inv_id = str(self.transaction.id)
        signature = robokassa_md5(f"{out_sum}:{inv_id}:test_password_2")
        
        response = self.client.post(reverse('robokassa_result_site'), {
            'OutSum': out_sum,
            'InvId': inv_id,
            'SignatureValue': signature,
        })
        
        print(f"  Статус ответа: {response.status_code}")
        self.assertEqual(response.status_code, 200)
        
        # Проверяем, что подписка продлена на 31 день
        self.telegram_user.refresh_from_db()
        expected_expiration = old_expiration + timedelta(days=31)
        actual_expiration = self.telegram_user.subscription_expiration
        print(f"  Ожидаемая дата окончания: {expected_expiration}")
        print(f"  Фактическая дата окончания: {actual_expiration}")
        self.assertEqual(actual_expiration, expected_expiration)
        print("  ✓ Подписка продлена корректно (+31 день)")


class RobokassaBotResultViewTest(TestCase):
    """Тесты для обработки вебхука RoboKassa (бот)"""

    def setUp(self):
        """Настройка тестовых данных"""
        self.client = Client()
        
        # Создаём TelegramUser
        self.telegram_user = TelegramUser.objects.create(
            user_id=123456789,
            username='testuser',
            first_name='Test',
            subscription_status=False,
        )
        
        # Создаём необходимые объекты
        IncomeInfo.objects.create(id=1, total_amount=Decimal('0.00'))
        Prices.objects.create(
            id=1,
            price_1=500,
            price_2=1400,
            price_3=2500,
            price_4=4500,
            price_5=25
        )
        ReferralSettings.objects.create(
            id=1,
            level_1_percentage=10,
            level_2_percentage=5,
            level_3_percentage=3,
            level_4_percentage=2,
            level_5_percentage=1
        )
        
        # Создаём транзакцию
        self.transaction = Transaction.objects.create(
            id=12345,
            status='pending',
            paid=False,
            amount=Decimal('500'),
            user=self.telegram_user,
            currency='RUB',
            income_info=IncomeInfo.objects.get(pk=1),
            side='Приход средств',
            description='Тестовая транзакция',
        )
        

    @patch('apps.payment.views.robokassa.get_robokassa_payment_info')
    @patch('apps.payment.views.robokassa.settings.ROBOKASSA_PASSWORD_2_BOT', 'test_password_2_bot')
    @patch('apps.payment.views.robokassa.settings.ROBOKASSA_MERCHANT_LOGIN_BOT', 'test_merchant_bot')
    def test_bot_result_webhook_valid(self, mock_get_payment_info):
        """Проверка обработки вебхука бота с валидной подписью"""
        print("\n[TEST] Проверка обработки вебхука бота с валидной подписью...")
        
        # Мокаем API вызов - возвращаем None (ID Robox не получен)
        mock_get_payment_info.return_value = None
        print("  API вызов замокан (ID Robox не получен)")
        
        out_sum = "500.00"
        inv_id = str(self.transaction.id)
        signature = robokassa_md5(f"{out_sum}:{inv_id}:test_password_2_bot")
        
        print(f"  Параметры вебхука:")
        print(f"    OutSum: {out_sum}")
        print(f"    InvId: {inv_id}")
        print(f"    SignatureValue: {signature}")
        
        response = self.client.post(reverse('robokassa_result_bot'), {
            'OutSum': out_sum,
            'InvId': inv_id,
            'SignatureValue': signature,
        })
        
        # Проверяем ответ
        print(f"  Статус ответа: {response.status_code}")
        print(f"  Тело ответа: {response.content.decode()}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), f"OK{inv_id}")
        print("  ✓ Ответ корректный")
        
        # Проверяем обновление транзакции
        self.transaction.refresh_from_db()
        print(f"  Статус транзакции: {self.transaction.status}")
        print(f"  Оплачено: {self.transaction.paid}")
        print(f"  Payment ID: {self.transaction.payment_id}")
        self.assertEqual(self.transaction.status, 'succeeded')
        self.assertEqual(self.transaction.paid, True)
        self.assertTrue(self.transaction.payment_id.startswith('ROBOX_INV_'))
        print("  ✓ Транзакция обновлена (использован fallback ID)")

    @patch('apps.payment.views.robokassa.get_robokassa_payment_info')
    @patch('apps.payment.views.robokassa.settings.ROBOKASSA_PASSWORD_2_BOT', 'test_password_2_bot')
    @patch('apps.payment.views.robokassa.settings.ROBOKASSA_MERCHANT_LOGIN_BOT', 'test_merchant_bot')
    def test_bot_result_webhook_with_robox_id(self, mock_get_payment_info):
        """Проверка сохранения ID Robox из API"""
        print("\n[TEST] Проверка сохранения ID Robox из API...")
        
        # Мокаем API вызов - возвращаем ID Robox
        mock_get_payment_info.return_value = {
            'RoboxID': '479920410',
            'State': '5'
        }
        print("  API вызов замокан (ID Robox получен: 479920410)")
        
        out_sum = "500.00"
        inv_id = str(self.transaction.id)
        signature = robokassa_md5(f"{out_sum}:{inv_id}:test_password_2_bot")
        
        response = self.client.post(reverse('robokassa_result_bot'), {
            'OutSum': out_sum,
            'InvId': inv_id,
            'SignatureValue': signature,
        })
        
        print(f"  Статус ответа: {response.status_code}")
        self.assertEqual(response.status_code, 200)
        
        # Проверяем, что ID Robox сохранён
        self.transaction.refresh_from_db()
        print(f"  Payment ID в транзакции: {self.transaction.payment_id}")
        self.assertEqual(self.transaction.payment_id, '479920410')
        print("  ✓ ID Robox сохранён корректно")

    @patch('apps.payment.views.robokassa.settings.ROBOKASSA_PASSWORD_2_BOT', 'test_password_2_bot')
    def test_bot_result_webhook_invalid_signature(self):
        """Проверка отклонения вебхука бота с невалидной подписью"""
        print("\n[TEST] Проверка отклонения вебхука бота с невалидной подписью...")
        out_sum = "500.00"
        inv_id = str(self.transaction.id)
        wrong_signature = "INVALID_SIGNATURE"
        
        print(f"  Параметры вебхука:")
        print(f"    OutSum: {out_sum}")
        print(f"    InvId: {inv_id}")
        print(f"    SignatureValue: {wrong_signature} (невалидная)")
        
        response = self.client.post(reverse('robokassa_result_bot'), {
            'OutSum': out_sum,
            'InvId': inv_id,
            'SignatureValue': wrong_signature,
        })
        
        print(f"  Статус ответа: {response.status_code}")
        print(f"  Тело ответа: {response.content.decode()}")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.content.decode(), 'bad sign')
        print("  ✓ Запрос отклонён (403 bad sign)")


class RobokassaSuccessFailViewTest(TestCase):
    """Тесты для страниц успеха и ошибки"""

    def setUp(self):
        """Настройка тестовых данных"""
        self.client = Client()

    def test_success_view_renders(self):
        """Проверка отображения страницы успеха"""
        print("\n[TEST] Проверка отображения страницы успеха...")
        response = self.client.get(reverse('robokassa_success'))
        print(f"  Статус ответа: {response.status_code}")
        print(f"  Используемый шаблон: {response.template_name if hasattr(response, 'template_name') else 'N/A'}")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'payments/payment_success.html')
        print("  ✓ Страница успеха отображается корректно")

    def test_fail_view_renders(self):
        """Проверка отображения страницы ошибки"""
        print("\n[TEST] Проверка отображения страницы ошибки...")
        response = self.client.get(reverse('robokassa_fail'))
        print(f"  Статус ответа: {response.status_code}")
        print(f"  Используемый шаблон: {response.template_name if hasattr(response, 'template_name') else 'N/A'}")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'payments/payment_failure.html')
        print("  ✓ Страница ошибки отображается корректно")


class RobokassaReferralTest(TestCase):
    """Тесты для реферальных начислений при платежах RoboKassa"""

    def setUp(self):
        """Настройка тестовых данных"""
        self.client = Client()
        
        # Создаём пользователей
        self.referrer = TelegramUser.objects.create(
            user_id=111111111,
            username='referrer',
            first_name='Referrer',
            income=Decimal('0.00'),
        )
        
        self.referred = TelegramUser.objects.create(
            user_id=222222222,
            username='referred',
            first_name='Referred',
            subscription_status=False,
        )
        
        # Создаём реферальную связь
        self.referral = TelegramReferral.objects.create(
            referrer=self.referrer,
            referred=self.referred,
            level=1
        )
        
        # Создаём необходимые объекты
        IncomeInfo.objects.create(id=1, total_amount=Decimal('0.00'))
        Prices.objects.create(
            id=1,
            price_1=500,
            price_2=1400,
            price_3=2500,
            price_4=4500,
            price_5=25
        )
        ReferralSettings.objects.create(
            id=1,
            level_1_percentage=10,
            level_2_percentage=5,
            level_3_percentage=3,
            level_4_percentage=2,
            level_5_percentage=1
        )
        
        # Создаём транзакцию
        self.transaction = Transaction.objects.create(
            id=12345,
            status='pending',
            paid=False,
            amount=Decimal('500'),
            user=self.referred,
            currency='RUB',
            income_info=IncomeInfo.objects.get(pk=1),
            side='Приход средств',
            description='Тестовая транзакция',
        )
        opstate_patcher = patch(
            'apps.payment.views.robokassa.get_robokassa_payment_info',
            return_value=None,
        )
        self.addCleanup(opstate_patcher.stop)
        opstate_patcher.start()

    @patch('apps.payment.views.robokassa.get_robokassa_payment_info')
    @patch('apps.payment.views.robokassa.settings.ROBOKASSA_PASSWORD_2_BOT', 'test_password_2_bot')
    @patch('apps.payment.views.robokassa.settings.ROBOKASSA_MERCHANT_LOGIN_BOT', 'test_merchant_bot')
    def test_referral_income_calculation(self, mock_get_payment_info):
        """Проверка начисления реферального дохода"""
        print("\n[TEST] Проверка начисления реферального дохода...")
        mock_get_payment_info.return_value = None
        
        out_sum = "500.00"
        inv_id = str(self.transaction.id)
        signature = robokassa_md5(f"{out_sum}:{inv_id}:test_password_2_bot")
        
        initial_income = self.referrer.income
        print(f"  Начальный доход реферера: {initial_income}")
        print(f"  Сумма платежа: {out_sum}")
        print(f"  Процент реферала (уровень 1): 10%")
        
        response = self.client.post(reverse('robokassa_result_bot'), {
            'OutSum': out_sum,
            'InvId': inv_id,
            'SignatureValue': signature,
        })
        
        print(f"  Статус ответа: {response.status_code}")
        self.assertEqual(response.status_code, 200)
        
        # Проверяем начисление реферального дохода
        self.referrer.refresh_from_db()
        expected_income = initial_income + (Decimal('500') * Decimal('10') / 100)  # 10% от 500
        actual_income = self.referrer.income
        print(f"  Ожидаемый доход: {expected_income}")
        print(f"  Фактический доход: {actual_income}")
        self.assertEqual(actual_income, expected_income)
        print("  ✓ Реферальный доход начислен корректно")
        
        # Проверяем создание ReferralTransaction
        referral_transactions = ReferralTransaction.objects.filter(
            referral=self.referral,
            transaction=self.transaction
        )
        print(f"  Количество ReferralTransaction: {referral_transactions.count()}")
        if referral_transactions.exists():
            print(f"  Сумма ReferralTransaction: {referral_transactions.first().amount}")
        self.assertEqual(referral_transactions.count(), 1)
        self.assertEqual(referral_transactions.first().amount, Decimal('50.00'))
        print("  ✓ ReferralTransaction создана корректно")


OPSTATE_PAID_XML = '''<?xml version="1.0" encoding="utf-8"?>
<OperationStateResponse xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns="http://merchant.roboxchange.com/WebService/">
  <Result>
    <Code>0</Code>
  </Result>
  <State>
    <Code>100</Code>
    <RequestDate>2026-08-13T12:00:00</RequestDate>
    <StateDate>2026-08-13T12:00:00</StateDate>
  </State>
  <Info>
    <OutSum>500.00</OutSum>
    <OpKey>479920410</OpKey>
  </Info>
</OperationStateResponse>'''

OPSTATE_INIT_XML = '''<?xml version="1.0" encoding="utf-8"?>
<OperationStateResponse xmlns="http://merchant.roboxchange.com/WebService/">
  <Result><Code>0</Code></Result>
  <State><Code>5</Code></State>
</OperationStateResponse>'''


class ParseRobokassaOpStateTest(TestCase):
    def test_nested_namespace_paid_state_100(self):
        parsed = parse_robokassa_opstate_xml(OPSTATE_PAID_XML)
        self.assertEqual(parsed.get('ResultCode'), '0')
        self.assertEqual(parsed.get('State'), '100')
        self.assertEqual(parsed.get('OpKey'), '479920410')
        self.assertEqual(parsed.get('RoboxID'), '479920410')
        self.assertEqual(classify_robokassa_opstate(parsed), 'paid')

    def test_state_5_is_pending_not_paid(self):
        parsed = parse_robokassa_opstate_xml(OPSTATE_INIT_XML)
        self.assertEqual(parsed.get('State'), '5')
        self.assertEqual(classify_robokassa_opstate(parsed), 'pending')

    def test_flat_state_fallback(self):
        parsed = parse_robokassa_opstate_xml(
            '''<?xml version="1.0" encoding="utf-8"?>
            <OperationStateResponse>
                <State>100</State>
                <PaymentID>111</PaymentID>
            </OperationStateResponse>'''
        )
        self.assertEqual(parsed.get('State'), '100')
        self.assertEqual(parsed.get('RoboxID'), '111')
        self.assertEqual(classify_robokassa_opstate(parsed), 'paid')

    def test_canceled_and_error(self):
        canceled = parse_robokassa_opstate_xml(
            '''<?xml version="1.0"?><OperationStateResponse xmlns="http://merchant.roboxchange.com/WebService/">
            <Result><Code>0</Code></Result><State><Code>10</Code></State>
            </OperationStateResponse>'''
        )
        self.assertEqual(classify_robokassa_opstate(canceled), 'canceled')
        not_found = parse_robokassa_opstate_xml(
            '''<?xml version="1.0"?><OperationStateResponse xmlns="http://merchant.roboxchange.com/WebService/">
            <Result><Code>3</Code></Result>
            </OperationStateResponse>'''
        )
        self.assertEqual(classify_robokassa_opstate(not_found), 'error')

    def test_utf8_bom_bytes(self):
        payload = b'\xef\xbb\xbf' + OPSTATE_PAID_XML.encode('utf-8')
        parsed = parse_robokassa_opstate_xml(payload)
        self.assertEqual(parsed.get('State'), '100')
        self.assertEqual(classify_robokassa_opstate(parsed), 'paid')

    def test_misdecoded_bom_string(self):
        # requests иногда декодирует BOM как latin-1 → 'ï»¿'
        payload = 'ï»¿' + OPSTATE_PAID_XML
        parsed = parse_robokassa_opstate_xml(payload)
        self.assertEqual(parsed.get('State'), '100')

    @patch('apps.payment.robokassa_subscription.requests.get')
    def test_get_payment_info_uses_opstate_ext(self, mock_get):
        mock_response = MagicMock()
        mock_response.content = b'\xef\xbb\xbf' + OPSTATE_PAID_XML.encode('utf-8')
        mock_response.text = 'ï»¿' + OPSTATE_PAID_XML  # как бывает у requests
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response
        result = get_robokassa_payment_info('12345', 'test_merchant', 'test_password')
        self.assertIsNotNone(result)
        self.assertEqual(result.get('State'), '100')
        self.assertEqual(result.get('RoboxID'), '479920410')
        mock_get.assert_called()
        url = mock_get.call_args[0][0]
        self.assertIn('OpStateExt', url)
        params = mock_get.call_args[1]['params']
        self.assertEqual(params['InvoiceID'], '12345')
        self.assertEqual(
            params['Signature'],
            subscription_robokassa_md5('test_merchant:12345:test_password'),
        )

    @patch('apps.payment.robokassa_subscription.requests.get')
    def test_get_payment_info_api_error(self, mock_get):
        mock_get.side_effect = Exception('API Error')
        result = get_robokassa_payment_info('12345', 'test_merchant', 'test_password')
        self.assertIsNone(result)


class RobokassaPendingCheckTest(TestCase):
    def setUp(self):
        self.telegram_user = TelegramUser.objects.create(
            user_id=123456789,
            username='testuser',
            first_name='Test',
            subscription_status=False,
        )
        IncomeInfo.objects.create(id=1, total_amount=Decimal('0.00'))
        Prices.objects.create(
            id=1, price_1=500, price_2=1400, price_3=2500, price_4=4500, price_5=25
        )
        ReferralSettings.objects.create(
            id=1,
            level_1_percentage=10,
            level_2_percentage=5,
            level_3_percentage=3,
            level_4_percentage=2,
            level_5_percentage=1,
        )
        self.transaction = Transaction.objects.create(
            status='pending',
            paid=False,
            amount=Decimal('500'),
            user=self.telegram_user,
            currency='RUB',
            income_info=IncomeInfo.objects.get(pk=1),
            side='Приход средств',
            description='Рекуррентный платёж (RoboKassa BOT)',
            payment_system='RoboKassaBot',
            robokassa_invoice_id='12345',
            robokassa_recurring_previous_inv_id='100',
        )
        self.transaction.robokassa_invoice_id = str(self.transaction.id)
        self.transaction.save(update_fields=['robokassa_invoice_id'])

    def _run_pending_check(self):
        from apps.payment.tasks import _check_robokassa_pending_transactions

        _check_robokassa_pending_transactions(
            payment_system='RoboKassaBot',
            merchant_login='test_merchant_bot',
            password_2='test_password_2_bot',
            source_label='BOT/ROBO',
        )

    @patch('apps.payment.tasks.fetch_robokassa_opstate')
    def test_pending_check_closes_paid_state_100(self, mock_fetch):
        mock_fetch.return_value = {
            'ResultCode': '0',
            'State': '100',
            'RoboxID': '479920410',
            'OpKey': '479920410',
        }
        self._run_pending_check()
        self.transaction.refresh_from_db()
        self.telegram_user.refresh_from_db()
        self.assertEqual(self.transaction.status, 'succeeded')
        self.assertTrue(self.transaction.paid)
        self.assertEqual(self.transaction.payment_id, '479920410')
        self.assertTrue(self.telegram_user.subscription_status)

    @patch('apps.payment.tasks.fetch_robokassa_opstate')
    def test_pending_check_does_not_close_state_5(self, mock_fetch):
        mock_fetch.return_value = {'ResultCode': '0', 'State': '5'}
        self._run_pending_check()
        self.transaction.refresh_from_db()
        self.telegram_user.refresh_from_db()
        self.assertEqual(self.transaction.status, 'pending')
        self.assertFalse(self.telegram_user.subscription_status)

    @patch('apps.payment.tasks.fetch_robokassa_opstate')
    def test_pending_check_cancels_state_10(self, mock_fetch):
        mock_fetch.return_value = {'ResultCode': '0', 'State': '10'}
        self._run_pending_check()
        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.status, 'canceled')
        self.assertFalse(self.transaction.paid)


class RobokassaRecurringChargeGuardTest(TestCase):
    def setUp(self):
        self.user = TelegramUser.objects.create(
            user_id=555,
            username='recurring',
            first_name='Recurring',
            subscription_status=False,
            subscription_expiration=timezone.now().date() - timedelta(days=1),
            robokassa_recurring_parent_inv_id='100',
            permission_revoked=False,
        )
        IncomeInfo.objects.create(id=1, total_amount=Decimal('0.00'))
        Prices.objects.create(
            id=1, price_1=500, price_2=1400, price_3=2500, price_4=4500, price_5=25
        )
        ReferralSettings.objects.create(
            id=1,
            level_1_percentage=10,
            level_2_percentage=5,
            level_3_percentage=3,
            level_4_percentage=2,
            level_5_percentage=1,
        )
        self.parent = Transaction.objects.create(
            status='succeeded',
            paid=True,
            amount=Decimal('500'),
            user=self.user,
            currency='RUB',
            income_info=IncomeInfo.objects.get(pk=1),
            side='Приход средств',
            payment_system='RoboKassaBot',
            robokassa_invoice_id='100',
            robokassa_is_recurring_parent=True,
            timestamp=timezone.now() - timedelta(days=40),
        )
        Transaction.objects.filter(pk=self.parent.pk).update(
            timestamp=timezone.now() - timedelta(days=40),
        )

    def test_old_pending_blocks_new_charge(self):
        from apps.payment.robokassa_subscription import (
            RECURRING_SKIP,
            evaluate_robokassa_recurring_charge,
        )

        pending = Transaction.objects.create(
            status='pending',
            paid=False,
            amount=Decimal('500'),
            user=self.user,
            currency='RUB',
            income_info=IncomeInfo.objects.get(pk=1),
            side='Приход средств',
            payment_system='RoboKassaBot',
            robokassa_invoice_id='200',
            robokassa_recurring_previous_inv_id='100',
        )
        Transaction.objects.filter(pk=pending.pk).update(
            timestamp=timezone.now() - timedelta(hours=80),
        )
        action, reason = evaluate_robokassa_recurring_charge(self.user, 'RoboKassaBot')
        self.assertEqual(action, RECURRING_SKIP)
        self.assertEqual(reason, 'есть pending рекуррент')

    @patch('apps.payment.tasks.fetch_robokassa_opstate')
    @patch('apps.payment.tasks.post_robokassa_bot_recurring_invoice')
    def test_ok_and_state_100_closes_immediately(self, mock_post, mock_fetch):
        from apps.payment.tasks import _run_robokassa_recurring

        mock_post.return_value = (True, 'OK')
        mock_fetch.return_value = {
            'ResultCode': '0',
            'State': '100',
            'RoboxID': 'op-1',
            'OpKey': 'op-1',
        }
        _run_robokassa_recurring(
            channel='BOT',
            payment_system='RoboKassaBot',
            merchant_login='login',
            password_1='p1',
            password_2='p2',
            is_test=False,
            recurring_description='Рекуррентный платёж (RoboKassa BOT)',
            success_log_message='отправлен успешно',
        )
        tx = Transaction.objects.filter(
            user=self.user,
            robokassa_recurring_previous_inv_id='100',
        ).latest('id')
        self.user.refresh_from_db()
        self.assertEqual(tx.status, 'succeeded')
        self.assertTrue(self.user.subscription_status)
        mock_post.assert_called_once()

    @patch('apps.payment.tasks.fetch_robokassa_opstate')
    @patch('apps.payment.tasks.post_robokassa_bot_recurring_invoice')
    def test_timeout_keeps_pending_and_does_not_retry(self, mock_post, mock_fetch):
        from apps.payment.robokassa_subscription import (
            RECURRING_SKIP,
            evaluate_robokassa_recurring_charge,
        )
        from apps.payment.tasks import _run_robokassa_recurring

        mock_post.return_value = (None, 'timeout: read timed out')
        mock_fetch.return_value = {'ResultCode': '0', 'State': '5'}
        _run_robokassa_recurring(
            channel='BOT',
            payment_system='RoboKassaBot',
            merchant_login='login',
            password_1='p1',
            password_2='p2',
            is_test=False,
            recurring_description='Рекуррентный платёж (RoboKassa BOT)',
            success_log_message='отправлен успешно',
        )
        txs = Transaction.objects.filter(
            user=self.user,
            robokassa_recurring_previous_inv_id='100',
            status='pending',
        )
        self.assertEqual(txs.count(), 1)
        mock_post.assert_called_once()

        action, reason = evaluate_robokassa_recurring_charge(self.user, 'RoboKassaBot')
        self.assertEqual(action, RECURRING_SKIP)
        self.assertEqual(reason, 'есть pending рекуррент')

        _run_robokassa_recurring(
            channel='BOT',
            payment_system='RoboKassaBot',
            merchant_login='login',
            password_1='p1',
            password_2='p2',
            is_test=False,
            recurring_description='Рекуррентный платёж (RoboKassa BOT)',
            success_log_message='отправлен успешно',
        )
        self.assertEqual(mock_post.call_count, 1)
        self.assertEqual(
            Transaction.objects.filter(
                user=self.user,
                robokassa_recurring_previous_inv_id='100',
            ).count(),
            1,
        )


