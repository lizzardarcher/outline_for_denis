from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch



from apps.admindashboardx.models import ServerHealthSample, ServerHealthState
from apps.admindashboardx.panel_health import CACHE_KEY, collect_and_store
from apps.admindashboardx.tests.test_panel_health import _celerity_api, _marzban_api, _server
from bot.models import Server




User = get_user_model()


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    SUPPORT_ACCOUNT="support-health",
    SECURE_SSL_REDIRECT=False,
)
class ServerPanelHealthAdminTests(TestCase):
    def setUp(self):
        cache.clear()
        patcher = patch("apps.admindashboardx.panel_health._ping_servers", return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)
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
        self.assertContains(response, "Последняя проверка")
        self.assertNotContains(response, "hosting, ip, country")


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
        self.assertContains(response, "❌")
        self.assertNotContains(response, "Marzban")
        self.assertNotContains(response, "Celerity")
        self.assertIsNotNone(cache.get(CACHE_KEY))



    def test_support_account_can_open_page(self):
        User.objects.create_user(
            "support-health",
            password="secret123!",
            is_staff=True,
            is_superuser=True,
        )
        self.client.login(username="support-health", password="secret123!")
        response = self.client.get(reverse("admin:bot_server_panel_health"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Проверить сейчас")

    def test_server_changelist_has_health_link(self):
        response = self.client.get(reverse("admin:bot_server_changelist"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("admin:bot_server_panel_health"))

    def test_health_page_links_to_server_log(self):
        server = Server.objects.create(hosting="Zomro DE1", ip_address="10.1.1.1", is_active=True)
        ServerHealthSample.objects.create(
            server=server,
            checked_at=timezone.now(),
            panel_status="ok",
            panel_detail="доступен",
            ping_status="ok",
            ping_detail="доступен",
            ping_ms=15,
        )
        collect_and_store(
            servers=[server],
            marzban_api=_marzban_api([{"id": 1, "address": "10.1.1.1", "status": "connected"}]),
            celerity_api=_celerity_api([{"_id": "n1", "ip": "10.1.1.1", "status": "online"}]),
            ping_hosts={"10.1.1.1": {"status": "ok", "detail": "доступен", "ping_ms": 15}},
        )
        response = self.client.get(reverse("admin:bot_server_panel_health"))
        log_url = reverse("admin:bot_server_panel_health_log", args=[server.pk])
        self.assertContains(response, log_url)
        self.assertContains(response, "Сеть")

        log_response = self.client.get(log_url)
        self.assertEqual(log_response.status_code, 200)
        self.assertContains(log_response, "Zomro DE1")
        self.assertContains(log_response, "✅")
        self.assertContains(log_response, "15")
        self.assertContains(log_response, "Cheburcheck")

    def test_health_log_shows_question_mark_for_silent_scanners(self):
        server = Server.objects.create(hosting="Zomro DE2", ip_address="10.1.1.2", is_active=True)
        now = timezone.now()
        ServerHealthState.objects.create(
            server=server,
            channel=ServerHealthState.CHANNEL_CHEBUR,
            status="question",
            detail="нет ответа сканеров",
            streak_started_at=now,
            last_checked_at=now,
        )
        ServerHealthSample.objects.create(
            server=server,
            checked_at=now,
            panel_status="",
            ping_status="",
            chebur_status="question",
            chebur_detail="нет ответа сканеров",
        )
        collect_and_store(
            servers=[server],
            marzban_api=_marzban_api([{"id": 1, "address": "10.1.1.2", "status": "connected"}]),
            celerity_api=_celerity_api([{"_id": "n1", "ip": "10.1.1.2", "status": "online"}]),
            ping_hosts={"10.1.1.2": {"status": "ok", "detail": "доступен", "ping_ms": 9}},
        )
        response = self.client.get(reverse("admin:bot_server_panel_health"))
        self.assertContains(response, "❓")
        log_response = self.client.get(reverse("admin:bot_server_panel_health_log", args=[server.pk]))
        self.assertContains(log_response, "❓")
        self.assertContains(log_response, "Cheburcheck")

    def test_health_page_shows_no_access_when_api_is_down(self):
        server = Server.objects.create(hosting="Zomro DE3", ip_address="10.1.1.3", is_active=True)
        now = timezone.now()
        ServerHealthState.objects.create(
            server=server,
            channel=ServerHealthState.CHANNEL_CHEBUR,
            status="no_access",
            detail="нет доступа",
            streak_started_at=now,
            last_checked_at=now,
        )
        collect_and_store(
            servers=[server],
            marzban_api=_marzban_api([{"id": 1, "address": "10.1.1.3", "status": "connected"}]),
            celerity_api=_celerity_api([{"_id": "n1", "ip": "10.1.1.3", "status": "online"}]),
            ping_hosts={"10.1.1.3": {"status": "ok", "detail": "доступен", "ping_ms": 9}},
        )
        response = self.client.get(reverse("admin:bot_server_panel_health"))
        self.assertContains(response, "⚠️ нет доступа")
        self.assertContains(response, "Нет доступа к API Cheburcheck")
