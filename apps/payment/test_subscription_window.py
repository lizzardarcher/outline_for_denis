
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.admindashboardx.ukassa_recurring import (
    _apply_yookassa_recurring_success,
    _bot_skip_reason,
)
from apps.payment.robokassa_subscription import (
    RECURRING_CHARGE,
    RECURRING_REPAIR_AND_SKIP,
    evaluate_robokassa_recurring_charge,
    extend_telegram_user_subscription,
)
from apps.payment.subscription_window import renewal_due_q
from bot.models import IncomeInfo, Prices, TelegramBot, TelegramUser, Transaction, VpnKey


class RenewalWindowTest(TestCase):
    def _user(self, user_id, **kwargs):
        defaults = dict(username=f"u{user_id}", first_name="U", permission_revoked=False)
        defaults.update(kwargs)
        return TelegramUser.objects.create(user_id=user_id, **defaults)

    def test_due_includes_last_day_and_overdue_not_future_active(self):
        today = timezone.localdate()
        last_day = self._user(1, subscription_status=True, subscription_expiration=today)
        overdue = self._user(
            2,
            subscription_status=False,
            subscription_expiration=today - timedelta(days=1),
        )
        inactive_future = self._user(
            3,
            subscription_status=False,
            subscription_expiration=today + timedelta(days=5),
        )
        future = self._user(
            4,
            subscription_status=True,
            subscription_expiration=today + timedelta(days=1),
        )

        ids = set(TelegramUser.objects.filter(renewal_due_q()).values_list("pk", flat=True))
        self.assertIn(last_day.pk, ids)
        self.assertIn(overdue.pk, ids)
        self.assertIn(inactive_future.pk, ids)
        self.assertNotIn(future.pk, ids)


class RobokassaRenewalWindowTest(TestCase):
    def _user(self, **kwargs):
        defaults = dict(
            user_id=555,
            username="recurring",
            first_name="Recurring",
            subscription_status=True,
            permission_revoked=False,
            robokassa_recurring_parent_inv_id="100",
        )
        defaults.update(kwargs)
        return TelegramUser.objects.create(**defaults)

    def test_last_day_active_is_charge(self):
        user = self._user(subscription_expiration=timezone.localdate())
        action, reason = evaluate_robokassa_recurring_charge(user, "RoboKassaBot")
        self.assertEqual(action, RECURRING_CHARGE)
        self.assertEqual(reason, "")

    def test_tomorrow_is_skip(self):
        user = self._user(subscription_expiration=timezone.localdate() + timedelta(days=1))
        action, reason = evaluate_robokassa_recurring_charge(user, "RoboKassaBot")
        self.assertEqual(action, RECURRING_REPAIR_AND_SKIP)
        self.assertEqual(reason, "subscription_expiration в будущем")

    def test_yesterday_inactive_is_charge(self):
        user = self._user(
            subscription_status=False,
            subscription_expiration=timezone.localdate() - timedelta(days=1),
        )
        action, _reason = evaluate_robokassa_recurring_charge(user, "RoboKassaBot")
        self.assertEqual(action, RECURRING_CHARGE)


class ExtendKeepsKeysTest(TestCase):
    def setUp(self):
        Prices.objects.create(
            id=1, price_1=500, price_2=1400, price_3=2500, price_4=4500, price_5=25
        )
        self.today = timezone.localdate()
        self.user = TelegramUser.objects.create(
            user_id=77,
            username="active",
            first_name="Active",
            subscription_status=True,
            subscription_expiration=self.today,
        )
        self.key = VpnKey.objects.create(user=self.user, key_id="key-keep")

    def test_active_extend_shifts_from_current_date_and_keeps_key(self):
        extend_telegram_user_subscription(self.user, 31)
        self.user.save()
        self.user.refresh_from_db()
        self.assertEqual(self.user.subscription_expiration, self.today + timedelta(days=31))
        self.assertTrue(self.user.subscription_status)
        self.assertTrue(VpnKey.objects.filter(key_id="key-keep").exists())

    def test_yookassa_success_uses_extend_while_active(self):
        _apply_yookassa_recurring_success(self.user, Decimal("500"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.subscription_expiration, self.today + timedelta(days=31))
        self.assertTrue(VpnKey.objects.filter(key_id="key-keep").exists())


class YooKassaChargeGuardTest(TestCase):
    def setUp(self):
        IncomeInfo.objects.create(id=1, total_amount=Decimal("0.00"))
        self.user = TelegramUser.objects.create(
            user_id=88,
            username="yk",
            first_name="Yk",
            subscription_status=True,
            subscription_expiration=timezone.localdate(),
            payment_method_id="12300045678901",
            permission_revoked=False,
        )

    def test_recent_success_blocks_charge(self):
        Transaction.objects.create(
            user=self.user,
            amount=Decimal("500"),
            currency="RUB",
            side="Приход средств",
            status="succeeded",
            paid=True,
            payment_system="YooKassaBot",
            description="Рекуррентный платеж",
            income_info=IncomeInfo.objects.get(pk=1),
        )
        self.assertEqual(_bot_skip_reason(self.user, {}), "недавний успешный платёж")

    def test_pending_blocks_charge(self):
        Transaction.objects.create(
            user=self.user,
            amount=Decimal("500"),
            currency="RUB",
            side="Приход средств",
            status="pending",
            paid=False,
            payment_system="YooKassaBot",
            description="Рекуррентный платеж",
            income_info=IncomeInfo.objects.get(pk=1),
        )
        self.assertEqual(_bot_skip_reason(self.user, {}), "есть pending")

    def test_old_success_does_not_block(self):
        tx = Transaction.objects.create(
            user=self.user,
            amount=Decimal("500"),
            currency="RUB",
            side="Приход средств",
            status="succeeded",
            paid=True,
            payment_system="YooKassaBot",
            description="Рекуррентный платеж",
            income_info=IncomeInfo.objects.get(pk=1),
        )
        Transaction.objects.filter(pk=tx.pk).update(timestamp=timezone.now() - timedelta(days=10))
        self.assertIsNone(_bot_skip_reason(self.user, {}))


class SubscriptionWipeGraceTest(TestCase):
    def setUp(self):
        TelegramBot.objects.create(username="testbot", token="token")
        IncomeInfo.objects.create(id=1, total_amount=Decimal("0.00"))
        self.yesterday = timezone.localdate() - timedelta(days=1)
        self.user = TelegramUser.objects.create(
            user_id=99,
            username="expiring",
            first_name="Exp",
            subscription_status=True,
            subscription_expiration=self.yesterday,
        )
        VpnKey.objects.create(user=self.user, key_id="key-wipe")

    @patch("bot.tasks.try_delete_celerity_user")
    @patch("bot.tasks.try_delete_pasarguard_user")
    @patch("bot.tasks.MarzbanAPI")
    @patch("bot.tasks.TeleBot")
    def test_fresh_pending_keeps_status_and_key(self, _bot, marzban, _pg, _cel):
        Transaction.objects.create(
            user=self.user,
            amount=Decimal("500"),
            currency="RUB",
            side="Приход средств",
            status="pending",
            paid=False,
            payment_system="YooKassaBot",
            description="Рекуррентный платеж",
            income_info=IncomeInfo.objects.get(pk=1),
        )
        from bot.tasks import update_user_subscription_status

        update_user_subscription_status()
        self.user.refresh_from_db()
        self.assertTrue(self.user.subscription_status)
        self.assertTrue(VpnKey.objects.filter(key_id="key-wipe").exists())
        marzban.assert_not_called()

    @patch("bot.tasks.try_delete_celerity_user")
    @patch("bot.tasks.try_delete_pasarguard_user")
    @patch("bot.tasks.MarzbanAPI")
    @patch("bot.tasks.TeleBot")
    def test_overdue_without_pending_clears_status_and_key(self, _bot, _marzban, _pg, _cel):
        from bot.tasks import update_user_subscription_status

        update_user_subscription_status()
        self.user.refresh_from_db()
        self.assertFalse(self.user.subscription_status)
        self.assertFalse(VpnKey.objects.filter(key_id="key-wipe").exists())
