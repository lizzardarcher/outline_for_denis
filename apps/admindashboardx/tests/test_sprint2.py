from decimal import Decimal


from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.admindashboardx.views import RevenueAnalyticsView, _admx_parse_optional_date
from bot.models import TelegramUser, Transaction

User = get_user_model()


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    SUPPORT_ACCOUNT="__no_support_match__",
)
class AdminDashboardSprint2Tests(TestCase):
    def test_parse_optional_date(self):
        self.assertIsNone(_admx_parse_optional_date(""))
        self.assertIsNone(_admx_parse_optional_date("not-a-date"))
        self.assertEqual(_admx_parse_optional_date("2024-06-10").isoformat(), "2024-06-10")

    def test_revenue_build_payload_alerts_have_actions(self):
        payload = RevenueAnalyticsView._build_payload(30, "", "all")
        self.assertIn("alerts", payload)
        self.assertGreaterEqual(len(payload["alerts"]), 1)
        for alert in payload["alerts"]:
            self.assertIn("level", alert)
            self.assertIn("actions", alert)
            for action in alert.get("actions") or []:
                self.assertIn("label", action)
                self.assertIn("url", action)

    def test_global_search_redirects_to_transaction_by_pk(self):
        User.objects.create_user("admintest", password="secret123!")
        self.client.login(username="admintest", password="secret123!")
        user = TelegramUser.objects.create(user_id=900000001, first_name="Test")
        tx = Transaction.objects.create(user=user, amount=Decimal("5.00"), status="succeeded", paid=True)
        response = self.client.get(reverse("admindashboardx:global_search"), {"q": str(tx.pk)})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.endswith(f"/transactions/{tx.pk}/"))

    def test_revenue_export_csv_returns_attachment(self):
        User.objects.create_user("admintest2", password="secret123!")
        self.client.login(username="admintest2", password="secret123!")
        response = self.client.get(reverse("admindashboardx:revenue_analytics_export_csv"), {"days": "30"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("csv", response["Content-Type"])
