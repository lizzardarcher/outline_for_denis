
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from bot.main.celerity_node_bootstrap import (
    bootstrap_celerity_for_server,
    build_celerity_node_payload,
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
    def __init__(self):
        self.updated = None
        self.setup_called = False

    def find_node_id_by_ip(self, ip, node_type):
        return True, "node-1"

    def update_node(self, node_id, data):
        self.updated = (node_id, data)
        return True, {"sni": data["sni"]}

    def setup_node(self, node_id, request_timeout=300):
        self.setup_called = True
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
        self.assertEqual(api.updated[1]["sni"], "bing.com")
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
