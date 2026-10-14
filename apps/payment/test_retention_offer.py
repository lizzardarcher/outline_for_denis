from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.payment.retention_offer import (
    add_calendar_months,
    days_for_amount,
    is_retention_offer_available,
    mark_retention_offer_used_if_amount,
    resolve_purchase_for_user,
)
from bot.models import IncomeInfo, Prices, TelegramUser, Transaction, UserProfile



@override_settings(RETENTION_OFFER_COOLDOWN_MONTHS=3)
class RetentionOfferTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='retention-user', password='secret')
        self.telegram_user = TelegramUser.objects.create(
            user_id=990001,
            username='retention-user',
            first_name='Test',
            subscription_status=True,
        )
        UserProfile.objects.create(user=self.user, telegram_user=self.telegram_user)
        IncomeInfo.objects.create(id=1, total_amount=Decimal('0.00'))
        self.prices = Prices.objects.create(
            id=1,
            price_1=250,
            price_2=720,
            price_3=1350,
            price_4=2500,
            price_5=25,
            price_special=100,
        )

    def test_special_amount_is_one_month(self):
        self.assertEqual(days_for_amount(100, self.prices), 31)
        self.assertEqual(days_for_amount(250, self.prices), 31)
        self.assertEqual(days_for_amount(25, self.prices), 3)

    def test_offer_hidden_until_cooldown_ends(self):
        self.assertTrue(is_retention_offer_available(self.telegram_user, self.prices))
        mark_retention_offer_used_if_amount(self.telegram_user, 100)
        self.telegram_user.refresh_from_db()
        self.assertIsNotNone(self.telegram_user.last_special_month_offer_at)
        self.assertFalse(is_retention_offer_available(self.telegram_user, self.prices))
        self.assertEqual(resolve_purchase_for_user(100, self.telegram_user, self.prices), (0.0, 0))

        self.telegram_user.last_special_month_offer_at = add_calendar_months(timezone.now(), -3)
        self.telegram_user.save(update_fields=['last_special_month_offer_at'])
        self.assertTrue(is_retention_offer_available(self.telegram_user, self.prices))
        self.assertEqual(resolve_purchase_for_user('100', self.telegram_user, self.prices), (100.0, 31))

    def test_regular_payment_does_not_consume_offer(self):
        mark_retention_offer_used_if_amount(self.telegram_user, 250)
        self.telegram_user.refresh_from_db()
        self.assertIsNone(self.telegram_user.last_special_month_offer_at)

    def test_recent_use_stays_blocked_inside_window(self):
        self.telegram_user.last_special_month_offer_at = timezone.now() - timedelta(days=80)
        self.telegram_user.save(update_fields=['last_special_month_offer_at'])
        self.assertFalse(is_retention_offer_available(self.telegram_user, self.prices))

    @patch('apps.payment.views.cloudpayments.credentials_for_channel', return_value=('pub', 'sec'))
    def test_cloudpayments_site_accepts_special_price(self, _creds):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('create_payment_cloudpayments'),
            {'subscription': '100'},
            secure=True,
        )
        self.assertEqual(response.status_code, 302)
        transaction = Transaction.objects.get()
        self.assertEqual(transaction.amount, Decimal('100'))
        self.assertIn('31', transaction.description)
        self.assertEqual(transaction.payment_system, 'CloudPaymentsSite')

    @patch('apps.payment.views.cloudpayments.credentials_for_channel', return_value=('pub', 'sec'))
    def test_cloudpayments_site_rejects_special_during_cooldown(self, _creds):
        self.telegram_user.last_special_month_offer_at = timezone.now()
        self.telegram_user.save(update_fields=['last_special_month_offer_at'])
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('create_payment_cloudpayments'),
            {'subscription': '100'},
            secure=True,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Transaction.objects.count(), 0)

    @patch('apps.payment.views.robokassa.settings.ROBOKASSA_MERCHANT_LOGIN_SITE', 'test_merchant')
    @patch('apps.payment.views.robokassa.settings.ROBOKASSA_PASSWORD_1_SITE', 'test_password')
    def test_robokassa_site_accepts_special_price(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('create_payment_robokassa'),
            {'subscription': '100'},
            secure=True,
        )
        self.assertEqual(response.status_code, 302)
        transaction = Transaction.objects.get()
        self.assertEqual(transaction.amount, Decimal('100'))
        self.assertIn('31', transaction.description)
