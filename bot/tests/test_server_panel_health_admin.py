from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch

from apps.admindashboardx.panel_health import CACHE_KEY, collect_and_store
from apps.admindashboardx.tests.test_panel_health import _celerity_api, _marzban_api, _server




User = get_user_model()


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    SUPPORT_ACCOUNT="support-health",
    SECURE_SSL_REDIRECT=False,
)
class ServerPanelHealthAdminTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin_user = User.objects.create_user(
            "admin-health",
            password="secret123!",
            is_staff=True,
            is_superuser=True,
        )
        self.client.login(username="admin-health", password="secret123!")

    def test_get_empty_page(self):
        response = self.client.get(reverse("admin:bot_server_panel_health"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Проверить сейчас")
        self.assertContains(response, "Проверка ещё не запускалась")

    def test_post_stores_snapshot_and_redirects(self):
        snapshot = {
            "checked_at": timezone.now().isoformat(),
            "panels_ok": True,
            "summary": {"servers": 0, "ok": 0, "down": 0, "unknown": 0, "idle": 0},
            "rows": [],
        }
        with patch("bot.admin.collect_and_store", return_value=snapshot) as mocked:
            response = self.client.post(reverse("admin:bot_server_panel_health"))
        self.assertEqual(response.status_code, 302)
        mocked.assert_called_once()
        self.assertEqual(response.url, reverse("admin:bot_server_panel_health"))

    def test_get_shows_cached_combined_status(self):
        collect_and_store(
            servers=[_server()],
            marzban_api=_marzban_api([{"id": 1, "address": "1.1.1.1", "status": "connected"}]),
            celerity_api=_celerity_api([{"_id": "n1", "ip": "1.1.1.1", "status": "offline"}]),
        )
        response = self.client.get(reverse("admin:bot_server_panel_health"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "недоступен")
        self.assertNotContains(response, "Marzban")
        self.assertNotContains(response, "Celerity")
        self.assertIsNotNone(cache.get(CACHE_KEY))

    def test_support_account_forbidden(self):
        User.objects.create_user(
            "support-health",
            password="secret123!",
            is_staff=True,
            is_superuser=True,
        )
        self.client.login(username="support-health", password="secret123!")
        response = self.client.get(reverse("admin:bot_server_panel_health"))
        self.assertEqual(response.status_code, 403)

    def test_server_changelist_has_health_link(self):
        response = self.client.get(reverse("admin:bot_server_changelist"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("admin:bot_server_panel_health"))
