
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings


from bot.main.celerity_node_bootstrap import (
    bootstrap_celerity_for_server,
    build_celerity_node_payload,
    hysteria_restart_looks_failed,
    pin_sha256_from_setup_logs,
    resolve_celerity_node_sni,
)
from bot.main.marzban_node_bootstrap import build_marzban_node_install_script


_PEM = """-----BEGIN CERTIFICATE-----
MIIB
-----END CERTIFICATE-----
"""

class _Country:
    name_for_app = "NL"


class _Server:
    pk = 7
    ip_address = "203.0.113.10"
    hosting = "FVD NL1"
    user = "root"
    password = "secret"
    country = _Country()
    is_c3celeryty_activated = False


class MarzbanInstallScriptTests(SimpleTestCase):
    def test_script_writes_real_pem_and_official_compose(self):
        script = build_marzban_node_install_script(_PEM)
        self.assertIn("-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----", script)
        self.assertNotIn("\\nMIIB", script)
        self.assertIn('SSL_CLIENT_CERT_FILE: "/var/lib/marzban-node/cert.pem"', script)
        self.assertIn('SERVICE_PORT: "62050"', script)
        self.assertIn('XRAY_API_PORT: "62051"', script)
        self.assertIn('SERVICE_PROTOCOL: "rest"', script)
        self.assertIn("echo \"MARZBAN_NODE_UP\"", script)
        self.assertIn("HYSTERIA_PIN_SHA256=", script)
        self.assertIn("{{.State.Running}}", script)


class CeleritySniTests(SimpleTestCase):
    @override_settings(CELERITY_NODE_SNI="")
    def test_empty_sni_setting_defaults_to_bing(self):
        self.assertEqual(resolve_celerity_node_sni(), "bing.com")

    @override_settings(CELERITY_NODE_SNI="bing.com", CELERITY_SSH_PORT=22, CELERITY_NODE_PORT=443)
    def test_payload_includes_sni(self):
        body = build_celerity_node_payload(_Server(), "group-1", "hysteria")
        self.assertEqual(body["sni"], "bing.com")
        self.assertNotIn("domain", body)


class _Api:
    def __init__(self, setups=None):
        self.updated = None
        self.updates = []
        self.setup_called = False
        self.setups = list(setups or [])

    def find_node_id_by_ip(self, ip, node_type):
        return True, "node-1"

    def update_node(self, node_id, data):
        self.updated = (node_id, data)
        self.updates.append(data)
        return True, data

    def setup_node(self, node_id, data=None, request_timeout=300):
        self.setup_called = True
        if self.setups:
            return self.setups.pop(0)
        return True, {"ok": True}


class CelerityActivationTests(SimpleTestCase):
    @patch("bot.main.celerity_node_bootstrap._celerity_group_id", return_value="g1")
    @patch("bot.main.celerity_node_bootstrap.mark_server_c3_activated")
    @patch(
        "bot.main.celerity_node_bootstrap.try_sync_hysteria_tls_meta_after_setup",
        return_value=False,
    )
    def test_missing_pin_does_not_activate(self, _sync, mark, _group):
        api = _Api()
        ok, detail = bootstrap_celerity_for_server(_Server(), api=api)
        self.assertFalse(ok)
        self.assertIn("pinSHA256", detail)
        self.assertEqual(api.updates[0]["sni"], "bing.com")
        self.assertTrue(api.setup_called)
        mark.assert_not_called()

    @patch("bot.main.celerity_node_bootstrap._celerity_group_id", return_value="g1")
    @patch("bot.main.celerity_node_bootstrap.mark_server_c3_activated")
    @patch(
        "bot.main.celerity_node_bootstrap.try_sync_hysteria_tls_meta_after_setup",
        return_value=True,
    )
    def test_pin_sync_activates(self, sync, mark, _group):
        ok, _detail = bootstrap_celerity_for_server(_Server(), api=_Api())
        self.assertTrue(ok)
        sync.assert_called_once()
        self.assertEqual(sync.call_args.kwargs["sni_override"], "bing.com")
        mark.assert_called_once()


class PanelSshInstallTests(SimpleTestCase):
    def test_old_journal_permission_denied_is_not_a_failure_when_service_is_up(self):
        text = (
            "Active: active (running) since Wed 2026-09-30 08:04:00 UTC\n"
            "FATAL failed to load server config tls.key: open /etc/hysteria/key.pem: permission denied\n"
        )
        self.assertFalse(hysteria_restart_looks_failed(text))

    def test_permission_denied_without_running_service_is_a_failure(self):
        text = "FATAL tls.key: open /etc/hysteria/key.pem: permission denied"
        self.assertTrue(hysteria_restart_looks_failed(text))

    def test_pin_line_from_setup_logs(self):
        pin = "3E0CAA6110D55DC28123208EB5495C8D8C881DB3D8371C1E2F87AD0CEECDDB6E"
        found = pin_sha256_from_setup_logs(
            {"logs": ["docker pull", f"HYSTERIA_PIN_SHA256={pin.lower()}"]}
        )
        self.assertEqual(found, pin)

    @patch("bot.main.celerity_node_bootstrap._celerity_group_id", return_value="g1")
    @patch("bot.main.celerity_node_bootstrap.mark_server_c3_activated")
    @patch("bot.main.celerity_node_bootstrap.save_hysteria_tls_meta_to_server")
    @patch("bot.main.celerity_node_bootstrap.try_sync_hysteria_tls_meta_after_setup")
    def test_pin_comes_from_panel_setup_not_local_ssh(self, sync, save, mark, _group):
        pin = "AB" * 32
        api = _Api(setups=[
            (True, {"logs": ["MARZBAN_NODE_UP"]}),
            (True, {"logs": [f"HYSTERIA_PIN_SHA256={pin}"]}),
        ])
        ok, detail = bootstrap_celerity_for_server(
            _Server(),
            api=api,
            init_script="echo MARZBAN_NODE_UP",
        )
        self.assertTrue(ok)
        self.assertIn("MARZBAN_NODE_UP", detail)
        sync.assert_not_called()
        save.assert_called_once()
        self.assertEqual(save.call_args.kwargs["pin"], pin)
        self.assertEqual(save.call_args.kwargs["sni"], "bing.com")
        mark.assert_called_once()
        self.assertEqual(api.updates[0]["initScript"], "echo MARZBAN_NODE_UP")
