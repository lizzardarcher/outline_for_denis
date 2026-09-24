

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.admindashboardx.models import ServerHealthSample, ServerHealthState
from apps.admindashboardx.panel_health import (
    CACHE_KEY,
    collect_and_store,
    collect_server_panel_health,
    format_streak,
    purge_old_health_samples,
)
from bot.models import Server


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
    def setUp(self):
        patcher = patch("apps.admindashboardx.panel_health._ping_servers", return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)

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
        patcher = patch("apps.admindashboardx.panel_health._ping_servers", return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)
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
        self.assertContains(response, "Сеть")
        self.assertIsNotNone(cache.get(CACHE_KEY))


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class ServerHealthHistoryTests(TestCase):
    def _apis(self, panel_status="connected", celerity_status="online"):
        return (
            _marzban_api([{"id": 1, "address": "10.0.0.8", "status": panel_status}]),
            _celerity_api([{"_id": "n1", "ip": "10.0.0.8", "status": celerity_status}]),
        )

    def _store(self, server, ping_status="ok", panel_ok=True):
        if panel_ok:
            marzban, celerity = self._apis()
        else:
            marzban = MagicMock()
            marzban.api_token = "token"
            marzban.list_nodes.return_value = (False, "timeout")
            celerity = self._apis()[1]
        ping = {"10.0.0.8": {"status": ping_status, "detail": "доступен" if ping_status == "ok" else "недоступен", "ping_ms": 12 if ping_status == "ok" else None}}
        return collect_and_store(servers=[server], marzban_api=marzban, celerity_api=celerity, ping_hosts=ping)

    def test_streak_holds_and_resets(self):
        server = Server.objects.create(
            hosting="Zomro DE1",
            ip_address="10.0.0.8",
            is_activated_vless=True,
            is_c3celeryty_activated=True,
        )
        self._store(server)
        ping_state = ServerHealthState.objects.get(server=server, channel=ServerHealthState.CHANNEL_PING)
        panel_state = ServerHealthState.objects.get(server=server, channel=ServerHealthState.CHANNEL_PANEL)
        ping_started = ping_state.streak_started_at
        panel_started = panel_state.streak_started_at

        self._store(server)
        ping_state.refresh_from_db()
        panel_state.refresh_from_db()
        self.assertEqual(ping_state.streak_started_at, ping_started)
        self.assertEqual(panel_state.streak_started_at, panel_started)
        self.assertEqual(ServerHealthSample.objects.filter(server=server).count(), 2)

        self._store(server, ping_status="down")
        ping_state.refresh_from_db()
        self.assertEqual(ping_state.status, "down")
        self.assertGreater(ping_state.streak_started_at, ping_started)

        self._store(server, panel_ok=False)
        panel_state.refresh_from_db()
        self.assertEqual(panel_state.status, "ok")
        self.assertEqual(panel_state.streak_started_at, panel_started)
        latest = server.health_samples.order_by("-id").first()
        self.assertEqual(latest.panel_status, "unknown")

    def test_purge_keeps_only_seven_days(self):
        server = Server.objects.create(hosting="old", ip_address="10.0.0.9")
        stale = ServerHealthSample.objects.create(
            server=server,
            checked_at=timezone.now() - timedelta(days=8),
            panel_status="ok",
            ping_status="ok",
        )
        fresh = ServerHealthSample.objects.create(
            server=server,
            checked_at=timezone.now() - timedelta(days=6),
            panel_status="down",
            ping_status="down",
        )
        deleted = purge_old_health_samples()
        self.assertGreaterEqual(deleted, 1)
        self.assertFalse(ServerHealthSample.objects.filter(pk=stale.pk).exists())
        self.assertTrue(ServerHealthSample.objects.filter(pk=fresh.pk).exists())

    def test_format_streak_days(self):
        started = timezone.now() - timedelta(days=3, hours=2)
        self.assertEqual(format_streak(started), "3 дн")

    @patch("apps.admindashboardx.panel_health.subprocess.run")
    def test_ping_host_parses_rtt(self, run):
        from apps.admindashboardx.panel_health import _ping_host

        run.return_value = SimpleNamespace(returncode=0, stdout="64 bytes from 10.0.0.1: icmp_seq=1 ttl=50 time=18.4 ms")
        result = _ping_host("10.0.0.8")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["ping_ms"], 18)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0][:3], ["ping", "-c", "1"])
