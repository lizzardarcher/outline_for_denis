
"""Выдача ключей не выбирает серверы с panel=down в ServerHealthState."""

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.admindashboardx.models import ServerHealthState
from apps.admindashboardx.panel_health import STATUS_DOWN, STATUS_OK, exclude_panel_down_servers
from bot.main.vpn_key_issue import (
    _server_for_hysteria2,
    _server_for_marzban,
    _server_for_pasarguard,
)
from bot.models import Country, Server


def _set_panel_status(server: Server, status: str) -> ServerHealthState:
    now = timezone.now()
    state, _ = ServerHealthState.objects.update_or_create(
        server=server,
        channel=ServerHealthState.CHANNEL_PANEL,
        defaults={
            "status": status,
            "detail": status,
            "streak_started_at": now,
            "last_checked_at": now,
            "last_ok_at": now if status == STATUS_OK else None,
        },
    )
    return state


@override_settings(KEY_LIMIT=200)
class PanelDownExcludesFromKeyIssueTests(TestCase):
    def setUp(self):
        self.country = Country.objects.create(name="DE", name_for_app="🇩🇪 Германия")
        self.ok = Server.objects.create(
            hosting="ok",
            ip_address="10.0.0.1",
            country=self.country,
            is_active=True,
            is_activated_vless=True,
            is_pasarguard_activated=True,
            is_c3celeryty_activated=True,
            keys_generated=0,
        )
        self.down = Server.objects.create(
            hosting="down",
            ip_address="10.0.0.2",
            country=self.country,
            is_active=True,
            is_activated_vless=True,
            is_pasarguard_activated=True,
            is_c3celeryty_activated=True,
            keys_generated=0,
        )
        _set_panel_status(self.ok, STATUS_OK)
        _set_panel_status(self.down, STATUS_DOWN)

    def test_exclude_helper_skips_panel_down_only(self):
        ids = set(
            exclude_panel_down_servers(Server.objects.filter(is_active=True)).values_list(
                "pk", flat=True
            )
        )
        self.assertIn(self.ok.pk, ids)
        self.assertNotIn(self.down.pk, ids)

    def test_ping_down_does_not_block(self):
        now = timezone.now()
        ServerHealthState.objects.update_or_create(
            server=self.ok,
            channel=ServerHealthState.CHANNEL_PING,
            defaults={
                "status": STATUS_DOWN,
                "detail": "ping down",
                "streak_started_at": now,
                "last_checked_at": now,
            },
        )
        self.assertEqual(_server_for_marzban(self.country).pk, self.ok.pk)

    def test_marzban_skips_panel_down(self):
        chosen = _server_for_marzban(self.country)
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.pk, self.ok.pk)

    def test_pasarguard_skips_panel_down(self):
        chosen = _server_for_pasarguard(self.country)
        self.assertEqual(chosen.pk, self.ok.pk)

    def test_hysteria2_skips_panel_down(self):
        chosen = _server_for_hysteria2(self.country)
        self.assertEqual(chosen.pk, self.ok.pk)

    def test_never_checked_server_still_eligible(self):
        unchecked = Server.objects.create(
            hosting="new",
            ip_address="10.0.0.3",
            country=self.country,
            is_active=True,
            is_activated_vless=True,
            keys_generated=0,
        )
        self.ok.is_active = False
        self.ok.save(update_fields=["is_active"])
        self.down.is_active = False
        self.down.save(update_fields=["is_active"])
        self.assertEqual(_server_for_marzban(self.country).pk, unchecked.pk)

    def test_all_panel_down_returns_none(self):
        _set_panel_status(self.ok, STATUS_DOWN)
        self.assertIsNone(_server_for_marzban(self.country))
