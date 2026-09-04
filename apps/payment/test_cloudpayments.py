
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.admindashboardx.cloudpayments_recurring import _skip_reason
from apps.payment.cloudpayments_common import (
    check_cloudpayments_pending_transactions,
    classify_cloudpayments_status,
    has_pending_cloudpayments_charge,
    reconcile_cloudpayments_pending_transaction,
)
from bot.models import (
    IncomeInfo,
    Prices,
    ReferralSettings,
    TelegramUser,
    Transaction,
)


def _json_response(payload):
    resp = MagicMock()
    resp.json.return_value = payload
    return resp


def _cp_model(
    status,
    *,
    transaction_id=897749645,
    amount="500",
    token="tok_abc",
    reason_code=0,
):
    return {
        "TransactionId": transaction_id,
        "Status": status,
        "Amount": float(amount),
        "Token": token,
        "ReasonCode": reason_code,
    }


@override_settings(
    CLOUDPAYMENTS_PUBLIC_ID_BOT="pk_bot",
    CLOUDPAYMENTS_API_SECRET_BOT="secret_bot",
    CLOUDPAYMENTS_PUBLIC_ID_SITE="pk_site",
    CLOUDPAYMENTS_API_SECRET_SITE="secret_site",
    CLOUDPAYMENTS_API_BASE="https://api.cloudpayments.ru",
)
class CloudPaymentsPendingCheckTest(TestCase):
    def setUp(self):
        self.telegram_user = TelegramUser.objects.create(
            user_id=123456789,
            username="cptest",
            first_name="CP",
            subscription_status=False,
            cloudpayments_token="tok_saved",
            cloudpayments_channel="bot",
        )
        IncomeInfo.objects.create(id=1, total_amount=Decimal("0.00"))
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
            status="pending",
            paid=False,
            amount=Decimal("500"),
            user=self.telegram_user,
            currency="RUB",
            income_info=IncomeInfo.objects.get(pk=1),
            side="Приход средств",
            description="Приобретение подписки (CloudPayments BOT, 31 дн.)",
            payment_system="CloudPaymentsBot",
        )

    def _run_pending_check(self):
        check_cloudpayments_pending_transactions(channel="bot", source_label="BOT/CP")

    def _find_ok(self, model):
        return _json_response({"Success": True, "Message": None, "Model": model})

    @patch("apps.payment.cloudpayments_common.requests.post")
    def test_pending_check_closes_completed(self, mock_post):
        mock_post.return_value = self._find_ok(_cp_model("Completed"))
        self._run_pending_check()
        self.transaction.refresh_from_db()
        self.telegram_user.refresh_from_db()
        self.assertEqual(self.transaction.status, "succeeded")
        self.assertTrue(self.transaction.paid)
        self.assertEqual(self.transaction.payment_id, "897749645")
        self.assertTrue(self.telegram_user.subscription_status)
        self.assertEqual(self.telegram_user.cloudpayments_token, "tok_abc")
        payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        self.assertEqual(payload, {"InvoiceId": str(self.transaction.id)})
        self.assertTrue(mock_post.call_args[0][0].endswith("/payments/find"))

    @patch("apps.payment.cloudpayments_common.requests.post")
    def test_pending_check_does_not_close_awaiting_auth(self, mock_post):
        mock_post.return_value = self._find_ok(_cp_model("AwaitingAuthentication"))
        self._run_pending_check()
        self.transaction.refresh_from_db()
        self.telegram_user.refresh_from_db()
        self.assertEqual(self.transaction.status, "pending")
        self.assertFalse(self.telegram_user.subscription_status)

    @patch("apps.payment.cloudpayments_common.requests.post")
    def test_pending_check_cancels_declined_and_clears_token(self, mock_post):
        mock_post.return_value = self._find_ok(
            _cp_model("Declined", reason_code=5054, token="")
        )
        self._run_pending_check()
        self.transaction.refresh_from_db()
        self.telegram_user.refresh_from_db()
        self.assertEqual(self.transaction.status, "canceled")
        self.assertFalse(self.transaction.paid)
        self.assertEqual(self.telegram_user.cloudpayments_token, "")

    @patch("apps.payment.cloudpayments_common.requests.post")
    def test_pending_check_not_found_keeps_pending(self, mock_post):
        mock_post.return_value = _json_response({"Success": False, "Message": "Not found"})
        self._run_pending_check()
        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.status, "pending")
        self.assertFalse(self.transaction.paid)


    @patch("apps.payment.cloudpayments_common.requests.post")
    def test_old_not_found_marks_canceled_keeps_token(self, mock_post):
        mock_post.return_value = _json_response({"Success": False, "Message": "Not found"})
        Transaction.objects.filter(pk=self.transaction.pk).update(
            timestamp=timezone.now() - timedelta(hours=25),
        )
        self._run_pending_check()
        self.transaction.refresh_from_db()
        self.telegram_user.refresh_from_db()
        self.assertEqual(self.transaction.status, "canceled")
        self.assertFalse(self.transaction.paid)
        self.assertEqual(self.telegram_user.cloudpayments_token, "tok_saved")
        self.assertFalse(self.telegram_user.subscription_status)

    @patch("apps.payment.cloudpayments_common.requests.post")
    def test_old_api_error_keeps_pending(self, mock_post):
        mock_post.side_effect = Exception("timeout")
        Transaction.objects.filter(pk=self.transaction.pk).update(
            timestamp=timezone.now() - timedelta(hours=25),
        )
        self._run_pending_check()
        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.status, "pending")

    @patch("apps.payment.cloudpayments_common.requests.post")
    def test_pending_check_falls_back_to_get_by_payment_id(self, mock_post):
        self.transaction.payment_id = "555001"
        self.transaction.save(update_fields=["payment_id"])

        def side_effect(url, **kwargs):
            if url.endswith("/payments/find"):
                return _json_response({"Success": False, "Message": "Not found"})
            self.assertTrue(url.endswith("/payments/get"))
            self.assertEqual(kwargs.get("json"), {"TransactionId": 555001})
            return self._find_ok(_cp_model("Completed", transaction_id=555001))

        mock_post.side_effect = side_effect
        self._run_pending_check()
        self.transaction.refresh_from_db()
        self.telegram_user.refresh_from_db()
        self.assertEqual(self.transaction.status, "succeeded")
        self.assertTrue(self.telegram_user.subscription_status)
        self.assertEqual(mock_post.call_count, 2)

    @patch("apps.payment.cloudpayments_common.requests.post")
    def test_pending_check_completed_is_idempotent(self, mock_post):
        mock_post.return_value = self._find_ok(_cp_model("Completed"))
        kwargs = dict(
            public_id="pk_bot",
            api_secret="secret_bot",
            channel="bot",
            source_label="BOT/CP",
        )
        reconcile_cloudpayments_pending_transaction(self.transaction, **kwargs)
        self.telegram_user.refresh_from_db()
        expiration = self.telegram_user.subscription_expiration
        reconcile_cloudpayments_pending_transaction(self.transaction, **kwargs)
        self.telegram_user.refresh_from_db()
        self.transaction.refresh_from_db()
        self.assertEqual(self.telegram_user.subscription_expiration, expiration)
        self.assertEqual(self.transaction.status, "succeeded")

    def test_classify_statuses(self):
        self.assertEqual(classify_cloudpayments_status("Completed"), "paid")
        self.assertEqual(classify_cloudpayments_status("Declined"), "canceled")
        self.assertEqual(classify_cloudpayments_status("Cancelled"), "canceled")
        self.assertEqual(classify_cloudpayments_status("Authorized"), "pending")
        self.assertEqual(classify_cloudpayments_status("AwaitingAuthentication"), "pending")
        self.assertEqual(classify_cloudpayments_status("Wat"), "unknown")


@override_settings(
    CLOUDPAYMENTS_PUBLIC_ID_BOT="pk_bot",
    CLOUDPAYMENTS_API_SECRET_BOT="secret_bot",
)
class CloudPaymentsRecurringPendingSkipTest(TestCase):
    def setUp(self):
        self.user = TelegramUser.objects.create(
            user_id=555,
            username="cprecurring",
            first_name="Recurring",
            subscription_status=False,
            permission_revoked=False,
            cloudpayments_token="tok_saved",
            cloudpayments_channel="bot",
        )
        IncomeInfo.objects.create(id=1, total_amount=Decimal("0.00"))

    def test_fresh_pending_blocks_recurring(self):
        self.assertIsNone(_skip_reason(self.user, "bot"))
        Transaction.objects.create(
            status="pending",
            paid=False,
            amount=Decimal("500"),
            user=self.user,
            currency="RUB",
            income_info=IncomeInfo.objects.get(pk=1),
            side="Приход средств",
            payment_system="CloudPaymentsBot",
        )
        self.assertEqual(_skip_reason(self.user, "bot"), "есть pending CloudPayments")
        self.assertTrue(has_pending_cloudpayments_charge(self.user, "CloudPaymentsBot"))

    def test_old_pending_does_not_block_recurring(self):
        pending = Transaction.objects.create(
            status="pending",
            paid=False,
            amount=Decimal("500"),
            user=self.user,
            currency="RUB",
            income_info=IncomeInfo.objects.get(pk=1),
            side="Приход средств",
            payment_system="CloudPaymentsBot",
        )
        Transaction.objects.filter(pk=pending.pk).update(
            timestamp=timezone.now() - timedelta(days=8),
        )
        self.assertIsNone(_skip_reason(self.user, "bot"))
        self.assertFalse(has_pending_cloudpayments_charge(self.user, "CloudPaymentsBot"))
