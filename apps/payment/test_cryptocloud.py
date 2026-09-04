
import base64
import hashlib
import hmac
import json
import time
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.admindashboardx.cloudpayments_recurring import _skip_reason as cp_skip_reason
from apps.admindashboardx.cryptocloud_recurring import _skip_reason as cc_skip_reason
from apps.payment.cryptocloud_common import (
    apply_successful_pay,
    find_transaction_from_postback,
    is_cryptocloud_allowed_for_user,
    verify_cryptocloud_jwt,
)
from bot.models import (
    IncomeInfo,
    Prices,
    ReferralSettings,
    TelegramUser,
    Transaction,
    UserProfile,
)

User = get_user_model()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def make_jwt(secret: str, extra_payload=None, exp_offset=300) -> str:
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = {"exp": int(time.time()) + exp_offset}
    if extra_payload:
        payload.update(extra_payload)
    payload_b64 = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(
        secret.encode("utf-8"),
        f"{header}.{payload_b64}".encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{header}.{payload_b64}.{_b64url(sig)}"


@override_settings(
    CRYPTOCLOUD_TEST_MODE=True,
    CRYPTOCLOUD_TEST_USERNAMES="megafoll",
    CRYPTOCLOUD_SECRET_KEY_SITE="test-cc-secret",
    CRYPTOCLOUD_API_KEY_SITE="test-key",
    CRYPTOCLOUD_SHOP_ID_SITE="test-shop",
    SECURE_SSL_REDIRECT=False,
)
class CryptoCloudCommonTests(TestCase):
    def setUp(self):
        self.tester = TelegramUser.objects.create(
            user_id=111,
            username="megafoll",
            first_name="Mega",
        )
        self.other = TelegramUser.objects.create(
            user_id=222,
            username="someone",
            first_name="Other",
        )
        IncomeInfo.objects.create(id=1, total_amount=Decimal("0.00"))
        Prices.objects.create(id=1, price_1=250, price_2=700, price_3=1300, price_4=2400, price_5=25)
        ReferralSettings.objects.create(
            id=1,
            level_1_percentage=10,
            level_2_percentage=5,
            level_3_percentage=3,
            level_4_percentage=2,
            level_5_percentage=1,
        )

    def test_jwt_valid_and_invalid(self):
        token = make_jwt("test-cc-secret")
        self.assertTrue(verify_cryptocloud_jwt(token, "test-cc-secret"))
        self.assertFalse(verify_cryptocloud_jwt(token, "wrong-secret"))
        self.assertFalse(verify_cryptocloud_jwt("not.a.jwt", "test-cc-secret"))
        expired = make_jwt("test-cc-secret", exp_offset=-10)
        self.assertFalse(verify_cryptocloud_jwt(expired, "test-cc-secret"))

    def test_test_gate_megafoll(self):
        self.assertTrue(is_cryptocloud_allowed_for_user(self.tester))
        self.assertTrue(is_cryptocloud_allowed_for_user(
            TelegramUser(user_id=1, username="@MegaFoll", first_name="X")
        ))
        self.assertFalse(is_cryptocloud_allowed_for_user(self.other))
        self.assertFalse(is_cryptocloud_allowed_for_user(None))

    @override_settings(CRYPTOCLOUD_TEST_MODE=False)
    def test_test_gate_off_allows_everyone(self):
        self.assertTrue(is_cryptocloud_allowed_for_user(self.other))

    def test_apply_pay_by_order_id_and_idempotent(self):
        tx = Transaction.objects.create(
            status="pending",
            paid=False,
            amount=Decimal("250"),
            user=self.tester,
            currency="RUB",
            income_info=IncomeInfo.objects.get(pk=1),
            side="Приход средств",
            description="Приобретение подписки (CryptoCloud SITE, 31 дн.)",
            payment_system="CryptoCloudSite",
        )
        found = find_transaction_from_postback({"order_id": str(tx.id)})
        self.assertEqual(found.id, tx.id)

        apply_successful_pay(
            transaction=tx,
            telegram_user=self.tester,
            payment_id="INV-TEST1",
            channel="site",
            log_prefix="[TEST]",
        )
        tx.refresh_from_db()
        self.tester.refresh_from_db()
        self.assertEqual(tx.status, "succeeded")
        self.assertTrue(tx.paid)
        self.assertEqual(tx.payment_id, "INV-TEST1")
        self.assertTrue(self.tester.subscription_status)
        self.assertEqual(self.tester.cryptocloud_channel, "site")

        apply_successful_pay(
            transaction=tx,
            telegram_user=self.tester,
            payment_id="INV-TEST1",
            channel="site",
            log_prefix="[TEST]",
        )
        self.assertEqual(Transaction.objects.filter(status="succeeded", user=self.tester).count(), 1)

    def test_recurring_skip_other_ps(self):
        self.tester.cryptocloud_channel = "bot"
        self.tester.permission_revoked = False
        self.tester.save()
        self.assertIsNone(cc_skip_reason(self.tester, "bot"))

        self.tester.payment_method_id = "pm_yookassa_000"
        self.tester.save()
        self.assertEqual(cc_skip_reason(self.tester, "bot"), "активен payment_method_id ЮKassa")

        other = TelegramUser.objects.create(
            user_id=333,
            username="megafoll2",
            first_name="CP",
            cloudpayments_token="tok_xxx",
            cryptocloud_channel="site",
        )
        self.assertEqual(cp_skip_reason(other, "site"), "активна подписка CryptoCloud")

    def test_skip_wrong_channel_and_test_user(self):
        self.tester.cryptocloud_channel = "site"
        self.tester.save()
        self.assertIn("канал", cc_skip_reason(self.tester, "bot") or "")
        self.other.cryptocloud_channel = "bot"
        self.other.save()
        self.assertIn("test-mode", cc_skip_reason(self.other, "bot") or "")


@override_settings(
    CRYPTOCLOUD_TEST_MODE=True,
    CRYPTOCLOUD_TEST_USERNAMES="megafoll",
    CRYPTOCLOUD_SECRET_KEY_SITE="test-cc-secret",
    CRYPTOCLOUD_API_KEY_SITE="test-key",
    CRYPTOCLOUD_SHOP_ID_SITE="test-shop",
    SECURE_SSL_REDIRECT=False,
)
class CryptoCloudViewsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="siteuser", password="pass123")
        self.tg = TelegramUser.objects.create(
            user_id=444,
            username="not_tester",
            first_name="No",
        )
        UserProfile.objects.create(user=self.user, telegram_user=self.tg)
        IncomeInfo.objects.create(id=1, total_amount=Decimal("0.00"))
        Prices.objects.create(id=1, price_1=250, price_2=700, price_3=1300, price_4=2400, price_5=25)

    def test_create_blocked_for_non_tester(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("create_payment_cryptocloud"), {"subscription": "250"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_webhook_rejects_bad_jwt(self):
        response = self.client.post(
            reverse("cryptocloud_site_webhook"),
            data=json.dumps({"status": "success", "order_id": "1", "token": "bad"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    @patch("apps.payment.views.cryptocloud.create_invoice")
    def test_create_allowed_for_megafoll(self, mock_create):
        self.tg.username = "megafoll"
        self.tg.save()
        mock_create.return_value = {"uuid": "INV-ABC", "link": "https://pay.example/ABC"}
        self.client.force_login(self.user)
        response = self.client.post(reverse("create_payment_cryptocloud"), {"subscription": "250"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("pay.example", response.url)
        tx = Transaction.objects.get()
        self.assertEqual(tx.payment_system, "CryptoCloudSite")
        self.assertEqual(tx.payment_id, "INV-ABC")
        self.assertEqual(tx.status, "pending")
