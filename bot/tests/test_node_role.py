
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from apps.admindashboardx.panel_health import STATUS_DOWN
from bot.admin import ServerAdmin
from bot.main.node_firewall import build_role_init_script, ufw_rules_for_role
from bot.main.server_protocol import countries_for_protocol, pick_server_for_protocol
from bot.main.server_provision import servers_pending_marzban_or_celerity
from bot.main.vpn_key_issue import _server_for_hysteria2, _server_for_vless_outline
from bot.models import Country, Server
from bot.tests.test_vpn_key_issue_panel_health import _set_panel_status


class UfwRoleScriptTests(SimpleTestCase):
    def test_outline_opens_shadowsocks_and_marzban_ports(self):
        rules = ufw_rules_for_role("outline")
        script = build_role_init_script("outline")
        self.assertIn("1080/tcp", rules)
        self.assertIn("62050/tcp", rules)
        self.assertIn("62051/tcp", rules)
        self.assertNotIn("443/tcp", rules)
        self.assertIn("ufw allow 22/tcp", script)
        self.assertIn("ufw allow 1080/tcp", script)
        self.assertNotIn("ufw allow 443/tcp", script)
        self.assertIn("ufw default deny incoming", script)
        self.assertIn("UFW_ROLE_APPLIED", script)

    def test_vless_opens_reality_port_not_shadowsocks(self):
        script = build_role_init_script("vless", "echo MARZBAN_NODE_UP\n")
        self.assertIn("ufw allow 443/tcp", script)
        self.assertIn("ufw allow 62050/tcp", script)
        self.assertNotIn("ufw allow 1080/tcp", script)
        self.assertIn("echo MARZBAN_NODE_UP", script)
        self.assertEqual(script.count("#!/bin/bash"), 1)

    def test_hysteria_opens_tcp_and_udp_443(self):
        rules = ufw_rules_for_role("hysteria2")
        self.assertIn("443/tcp", rules)
        self.assertIn("443/udp", rules)
        self.assertNotIn("1080/tcp", rules)
        self.assertNotIn("62050/tcp", rules)


@override_settings(KEY_LIMIT=200)
class ProtocolRoleSelectionTests(TestCase):
    def setUp(self):
        self.country = Country.objects.create(name="DE", name_for_app="Германия", is_active=True)
        self.legacy = Server.objects.create(
            hosting="legacy",
            ip_address="10.1.0.1",
            country=self.country,
            is_active=True,
            is_activated_vless=True,
            is_c3celeryty_activated=True,
            node_role="",
            keys_generated=10,
        )
        self.outline = Server.objects.create(
            hosting="ss",
            ip_address="10.1.0.2",
            country=self.country,
            is_active=True,
            is_activated_vless=True,
            node_role=Server.NODE_ROLE_OUTLINE,
            keys_generated=50,
        )
        self.vless = Server.objects.create(
            hosting="vless",
            ip_address="10.1.0.3",
            country=self.country,
            is_active=True,
            is_activated_vless=True,
            node_role=Server.NODE_ROLE_VLESS,
            keys_generated=40,
        )
        self.hysteria = Server.objects.create(
            hosting="hy2",
            ip_address="10.1.0.4",
            country=self.country,
            is_active=True,
            is_c3celeryty_activated=True,
            node_role=Server.NODE_ROLE_HYSTERIA2,
            keys_generated=30,
        )

    def test_role_is_preferred_over_less_loaded_legacy(self):
        self.assertEqual(pick_server_for_protocol(self.country, "outline").pk, self.outline.pk)
        self.assertEqual(_server_for_vless_outline(self.country, "vless").pk, self.vless.pk)
        self.assertEqual(_server_for_hysteria2(self.country).pk, self.hysteria.pk)

    def test_missing_role_falls_back_to_legacy(self):
        self.outline.is_active = False
        self.outline.save(update_fields=["is_active"])
        self.assertEqual(pick_server_for_protocol(self.country, "outline").pk, self.legacy.pk)

    def test_panel_down_role_falls_back_to_legacy(self):
        _set_panel_status(self.vless, STATUS_DOWN)
        chosen = pick_server_for_protocol(self.country, "vless")
        self.assertEqual(chosen.pk, self.legacy.pk)

    def test_country_list_hides_protocol_without_server(self):
        other = Country.objects.create(name="US", name_for_app="США", is_active=True)
        Server.objects.create(
            hosting="us-ss",
            ip_address="10.2.0.1",
            country=other,
            is_active=True,
            is_activated_vless=True,
            node_role=Server.NODE_ROLE_OUTLINE,
            keys_generated=0,
        )
        outline_names = set(countries_for_protocol("outline").values_list("name", flat=True))
        vless_names = set(countries_for_protocol("vless").values_list("name", flat=True))
        self.assertIn("US", outline_names)
        self.assertNotIn("US", vless_names)
        self.assertIn("DE", vless_names)

    def test_batch_install_skips_role_servers(self):
        pending_ids = set(servers_pending_marzban_or_celerity().values_list("pk", flat=True))
        self.assertIn(self.legacy.pk, pending_ids)
        self.assertNotIn(self.outline.pk, pending_ids)
        self.assertNotIn(self.vless.pk, pending_ids)
        self.assertNotIn(self.hysteria.pk, pending_ids)


class ServerHealthImportTests(TestCase):
    def test_role_server_is_not_a_legacy_marzban_candidate(self):
        country = Country.objects.create(name="NL", name_for_app="Нидерланды", is_active=True)
        Server.objects.create(
            hosting="only-vless",
            ip_address="10.3.0.1",
            country=country,
            is_active=True,
            is_activated_vless=True,
            node_role=Server.NODE_ROLE_VLESS,
            keys_generated=0,
        )
        from bot.main.vpn_key_issue import _server_for_marzban

        self.assertIsNone(_server_for_marzban(country))
        self.assertEqual(_server_for_vless_outline(country, "vless").ip_address, "10.3.0.1")


class DjangoAdminServerAddTests(TestCase):
    def setUp(self):
        self.admin = ServerAdmin(Server, AdminSite())
        self.request = RequestFactory().get("/admin/bot/server/add/")

    def test_add_form_requires_protocol(self):
        form_class = self.admin.get_form(self.request, obj=None)
        form = form_class(data={
            "hosting": "new",
            "ip_address": "10.9.0.1",
            "user": "root",
            "password": "secret",
            "is_active": True,
            "node_role": "",
        })
        self.assertIn("node_role", form.fields)
        self.assertTrue(form.fields["node_role"].required)
        choice_values = [value for value, _label in form.fields["node_role"].choices]
        self.assertIn(Server.NODE_ROLE_OUTLINE, choice_values)
        self.assertIn(Server.NODE_ROLE_VLESS, choice_values)
        self.assertIn(Server.NODE_ROLE_HYSTERIA2, choice_values)
        self.assertFalse(form.is_valid())
        self.assertIn("node_role", form.errors)

        form = form_class(data={
            "hosting": "new",
            "ip_address": "10.9.0.1",
            "user": "root",
            "password": "secret",
            "is_active": True,
            "node_role": Server.NODE_ROLE_VLESS,
        })
        self.assertTrue(form.is_valid(), form.errors)
        server = form.save()
        self.assertEqual(server.node_role, Server.NODE_ROLE_VLESS)
        self.assertNotIn("node_role", self.admin.get_readonly_fields(self.request, obj=None))

    def test_installed_server_role_is_readonly(self):
        country = Country.objects.create(name="KZ", name_for_app="Казахстан", is_active=True)
        server = Server.objects.create(
            hosting="installed",
            ip_address="10.9.0.2",
            country=country,
            is_active=True,
            is_activated_vless=True,
            node_role=Server.NODE_ROLE_OUTLINE,
        )
        readonly = self.admin.get_readonly_fields(self.request, obj=server)
        self.assertIn("node_role", readonly)
        form_class = self.admin.get_form(self.request, obj=server)
        self.assertNotIn("node_role", form_class.base_fields)


    def test_same_ip_cannot_be_added_for_another_protocol(self):
        Server.objects.create(
            hosting="already",
            ip_address="10.9.0.1",
            is_active=True,
            node_role=Server.NODE_ROLE_OUTLINE,
            is_activated_vless=True,
        )
        form_class = self.admin.get_form(self.request, obj=None)
        form = form_class(data={
            "hosting": "again",
            "ip_address": " 10.9.0.1 ",
            "user": "root",
            "password": "secret",
            "is_active": True,
            "node_role": Server.NODE_ROLE_VLESS,
        })
        self.assertFalse(form.is_valid())
        self.assertIn("Сервер с таким IP уже есть.", form.errors["ip_address"])
