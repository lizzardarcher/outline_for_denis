
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone


from apps.admindashboardx.panel_health import (
    CACHE_KEY,
    collect_and_store,
    collect_server_panel_health,
)


User = get_user_model()


def _server(**kwargs):
    defaults = {
        "pk": 1,
        "hosting": "host-a",
        "ip_address": "1.1.1.1",
        "is_active": True,
        "is_activated_vless": True,
        "is_c3celeryty_activated": True,
        "country": SimpleNamespace(name="NL", name_for_app="Нидерланды"),
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _marzban_api(nodes):
    api = MagicMock()
    api.api_token = "token"
    api.list_nodes.return_value = (True, nodes)
    return api


def _celerity_api(nodes):
    api = MagicMock()
    api.list_nodes.return_value = (True, nodes)
    return api


class PanelHealthCollectorTests(SimpleTestCase):
    def test_combined_ok_when_both_panels_healthy(self):
        payload = collect_server_panel_health(
            servers=[_server()],
            marzban_api=_marzban_api([{"id": 1, "address": "1.1.1.1", "status": "connected"}]),
            celerity_api=_celerity_api([{"_id": "n1", "ip": "1.1.1.1", "status": "online"}]),
        )
        row = payload["rows"][0]
        self.assertTrue(payload["panels_ok"])
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["detail"], "доступен")
        self.assertNotIn("marzban", row)
        self.assertNotIn("celerity", row)
        self.assertEqual(payload["summary"]["ok"], 1)

    def test_combined_down_if_one_panel_is_down(self):
        payload = collect_server_panel_health(
            servers=[_server()],
            marzban_api=_marzban_api([{"id": 1, "address": "1.1.1.1", "status": "connected"}]),
            celerity_api=_celerity_api([{"_id": "n1", "ip": "1.1.1.1", "status": "offline"}]),
        )
        row = payload["rows"][0]
        self.assertEqual(row["status"], "down")
        self.assertEqual(row["detail"], "недоступен")
        self.assertEqual(payload["summary"]["down"], 1)

    def test_combined_down_if_expected_node_missing(self):
        payload = collect_server_panel_health(
            servers=[_server()],
            marzban_api=_marzban_api([{"id": 1, "address": "1.1.1.1", "status": "connected"}]),
            celerity_api=_celerity_api([]),
        )
        self.assertEqual(payload["rows"][0]["status"], "down")

    def test_unknown_when_panel_request_fails(self):
        marzban = MagicMock()
        marzban.api_token = "token"
        marzban.list_nodes.return_value = (False, "timeout")
        payload = collect_server_panel_health(
            servers=[_server()],
            marzban_api=marzban,
            celerity_api=_celerity_api([{"_id": "n1", "ip": "1.1.1.1", "status": "online"}]),
        )
        self.assertFalse(payload["panels_ok"])
        self.assertEqual(payload["rows"][0]["status"], "unknown")
        self.assertEqual(payload["rows"][0]["detail"], "нет ответа панели")

    def test_idle_when_not_in_panels(self):
        payload = collect_server_panel_health(
            servers=[_server(is_activated_vless=False, is_c3celeryty_activated=False)],
            marzban_api=_marzban_api([]),
            celerity_api=_celerity_api([]),
        )
        self.assertEqual(payload["rows"][0]["status"], "idle")
        self.assertEqual(payload["rows"][0]["detail"], "не в панелях")

    def test_unwraps_nested_node_lists(self):
        payload = collect_server_panel_health(
            servers=[_server()],
            marzban_api=_marzban_api({"nodes": [{"id": 1, "address": "1.1.1.1", "status": "connected"}]}),
            celerity_api=_celerity_api({"data": [{"_id": "n1", "ip": "1.1.1.1", "status": "online"}]}),
        )
        self.assertEqual(payload["rows"][0]["status"], "ok")


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    SUPPORT_ACCOUNT="__no_support_match__",
    SECURE_SSL_REDIRECT=False,
)
class ServerPanelHealthViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("admintest-health", password="secret123!")
        self.client.login(username="admintest-health", password="secret123!")

    def test_get_empty_page(self):
        response = self.client.get(reverse("admindashboardx:server_panel_health"))
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
        with patch("apps.admindashboardx.views.collect_and_store", return_value=snapshot) as mocked:
            response = self.client.post(reverse("admindashboardx:server_panel_health"))
        self.assertEqual(response.status_code, 302)
        mocked.assert_called_once()
        self.assertIn("ops=checked", response.url)

    def test_get_shows_cached_combined_status(self):
        collect_and_store(
            servers=[_server()],
            marzban_api=_marzban_api([{"id": 1, "address": "1.1.1.1", "status": "connected"}]),
            celerity_api=_celerity_api([{"_id": "n1", "ip": "1.1.1.1", "status": "offline"}]),
        )
        response = self.client.get(reverse("admindashboardx:server_panel_health"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "недоступен")
        self.assertNotContains(response, "Marzban")
        self.assertNotContains(response, "Celerity")
        self.assertIsNotNone(cache.get(CACHE_KEY))
