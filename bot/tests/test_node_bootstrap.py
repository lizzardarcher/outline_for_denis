
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings


from bot.main.celerity_node_bootstrap import (
    bootstrap_celerity_for_server,
    build_celerity_node_payload,

    ensure_hysteria_salamander,

    generated_config_has_salamander,
    hysteria_restart_looks_failed,
    pin_sha256_from_setup_logs,
    resolve_celerity_node_sni,
    setup_response_pending,
    wait_for_marzban_node,
)
from bot.main.celerity_panel_form import (
    obfs_form_fields,
    reset_panel_session_cache,
    save_node_obfs_via_panel,
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
        self.assertIn("compose_up_ok", script)
        self.assertIn("docker install failed", script)


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


class _SalamanderApi(_Api):
    def __init__(self, reads):
        super().__init__()
        self.reads = list(reads)
        self.config_calls = 0

    def get_node(self, node_id):
        if not self.reads:
            return False, "empty"
        return True, self.reads.pop(0)

    def update_node_config(self, node_id, request_timeout=180):
        self.config_calls += 1
        return True, {"ok": True}

    def get_node_config(self, node_id, request_timeout=60):
        body = getattr(self, "config_body", "obfs:\n  type: salamander\n")
        if body is None:
            return False, "config unavailable"
        return True, body


class HysteriaSalamanderTests(SimpleTestCase):
    def test_existing_password_is_kept(self):
        api = _SalamanderApi([
            {"obfs": {"type": "salamander", "password": "keep-me"}},
            {"obfs": {"type": "salamander", "password": "keep-me"}},
        ])
        notes = []
        ok, detail = ensure_hysteria_salamander(api, "node-1", lambda level, msg: notes.append(msg))
        self.assertTrue(ok)
        self.assertEqual(api.updates, [])
        self.assertEqual(api.config_calls, 1)
        self.assertNotIn("keep-me", detail)
        self.assertNotIn("keep-me", " ".join(notes))

    def test_new_password_is_not_logged(self):
        api = _SalamanderApi([
            {},
            {"obfs": {"type": "salamander", "password": "from-panel"}},
            {"obfs": {"type": "salamander", "password": "from-panel"}},
        ])
        notes = []
        ok, detail = ensure_hysteria_salamander(api, "node-1", lambda level, msg: notes.append(msg))
        self.assertTrue(ok)
        self.assertEqual(api.updates[0]["obfs"]["type"], "salamander")
        password = api.updates[0]["obfs"]["password"]
        self.assertTrue(password)
        self.assertNotIn(password, detail)
        self.assertNotIn(password, " ".join(notes))
        self.assertEqual(api.config_calls, 1)

    @patch(
        "bot.main.celerity_node_bootstrap.save_node_obfs_via_panel",
        return_value=(False, "API Celerity не сохраняет obfs"),
    )
    @patch("bot.main.celerity_node_bootstrap._celerity_group_id", return_value="g1")
    @patch("bot.main.celerity_node_bootstrap.mark_server_c3_activated")
    @patch(
        "bot.main.celerity_node_bootstrap.try_sync_hysteria_tls_meta_after_setup",
        return_value=True,
    )
    def test_role_install_waits_for_confirmed_obfs(self, _sync, mark, _group, form):
        api = _SalamanderApi([{}])
        ok, detail = bootstrap_celerity_for_server(_Server(), api=api, salamander=True)
        self.assertFalse(ok)
        self.assertIn("не сохраняет obfs", detail)
        form.assert_called_once()
        mark.assert_not_called()

        api = _SalamanderApi([
            {},
            {"obfs": {"type": "salamander", "password": "secret-obfs"}},
            {"obfs": {"type": "salamander", "password": "secret-obfs"}},
        ])
        ok, detail = bootstrap_celerity_for_server(_Server(), api=api, salamander=True)
        self.assertTrue(ok)
        self.assertNotIn("secret-obfs", detail)
        mark.assert_called_once()
        self.assertEqual(form.call_count, 1)

    @patch("bot.main.celerity_node_bootstrap._celerity_group_id", return_value="g1")
    @patch("bot.main.celerity_node_bootstrap.mark_server_c3_activated")
    @patch(
        "bot.main.celerity_node_bootstrap.try_sync_hysteria_tls_meta_after_setup",
        return_value=True,
    )
    @patch(
        "bot.main.celerity_node_bootstrap.save_node_obfs_via_panel",
        return_value=(True, "форма панели приняла obfs"),
    )
    def test_panel_form_saves_obfs_when_api_drops_it(self, form, _sync, mark, _group):
        saved = {"obfs": {"type": "salamander", "password": "secret-obfs"}}
        api = _SalamanderApi([{}, {}, saved, saved])
        notes = []
        ok, detail = bootstrap_celerity_for_server(
            _Server(),
            api=api,
            salamander=True,
            log_fn=lambda level, msg: notes.append(msg),
        )
        self.assertTrue(ok)
        form.assert_called_once()
        posted_password = form.call_args.args[2]
        self.assertTrue(posted_password)
        self.assertNotIn(posted_password, detail)
        self.assertNotIn(posted_password, " ".join(notes))
        self.assertNotIn("secret-obfs", " ".join(notes))
        mark.assert_called_once()
        story = "\n".join(notes)
        self.assertLess(story.index("Шаг 2."), story.index("Шаг 3."))
        self.assertLess(story.index("Шаг 3."), story.index("Шаг 5."))

    @patch("bot.main.celerity_node_bootstrap._celerity_group_id", return_value="g1")
    @patch("bot.main.celerity_node_bootstrap.mark_server_c3_activated")
    @patch(
        "bot.main.celerity_node_bootstrap.try_sync_hysteria_tls_meta_after_setup",
        return_value=True,
    )
    def test_install_stops_when_built_config_has_no_salamander(self, _sync, mark, _group):
        api = _SalamanderApi([
            {"obfs": {"type": "salamander", "password": "keep-me"}},
        ])
        api.config_body = "listen: :443\n"
        ok, detail = bootstrap_celerity_for_server(_Server(), api=api, salamander=True)
        self.assertFalse(ok)
        self.assertIn("Salamander", detail)
        self.assertNotIn("keep-me", detail)
        mark.assert_not_called()
        self.assertEqual(api.updates[0].get("obfs"), None)

    def test_generated_config_requires_salamander_line(self):
        self.assertTrue(generated_config_has_salamander("obfs:\n  type: salamander\n"))
        self.assertTrue(generated_config_has_salamander("type: salamander  # obfs"))
        self.assertTrue(generated_config_has_salamander({"config": "obfs:\n  type: salamander\n"}))
        self.assertFalse(generated_config_has_salamander("# type: salamander\nlisten: :443\n"))


class MarzbanWaitTests(SimpleTestCase):
    def test_timeout_and_busy_count_as_pending(self):
        self.assertTrue(setup_response_pending("setup_node: Read timed out"))
        self.assertTrue(setup_response_pending("Node is busy: Node setup is running"))
        self.assertFalse(setup_response_pending("MARZBAN_NODE_NOT_RUNNING"))

    @patch("bot.main.celerity_node_bootstrap.time.sleep")
    @patch("bot.main.celerity_node_bootstrap.run_setup_init_script")
    def test_wait_retries_while_setup_is_busy(self, run_setup, sleep):
        run_setup.side_effect = [
            (False, "setup_node: Node is busy: Node setup is running", "n1"),
            (True, "MARZBAN_NODE_UP", "n1"),
        ]
        ok, detail, node_id = wait_for_marzban_node(
            _Server(),
            api=object(),
            attempts=3,
            pause_seconds=1,
        )
        self.assertTrue(ok)
        self.assertIn("MARZBAN_NODE_UP", detail)
        self.assertEqual(node_id, "n1")
        sleep.assert_called_once()


class PanelFormTests(SimpleTestCase):
    def test_form_keeps_groups_and_does_not_send_ssh_password(self):
        fields = dict(obfs_form_fields(
            {
                "name": "DE-1",
                "ip": "203.0.113.10",
                "sni": "bing.com",
                "groups": ["group-1"],
                "ssh": {"password": "ssh-secret"},
                "initScript": "ufw allow 22/tcp",
            },
            "obfs-secret",
        ))
        self.assertEqual(fields["obfs.type"], "salamander")
        self.assertEqual(fields["obfs.password"], "obfs-secret")
        self.assertEqual(fields["sni"], "bing.com")
        self.assertIn(("groups", "group-1"), obfs_form_fields(
            {"name": "DE-1", "groups": ["group-1"]},
            "obfs-secret",
        ))
        self.assertNotIn("ssh.password", fields)
        self.assertNotIn("ssh-secret", fields.values())

    @override_settings(
        C3CELERYTY_API_ENDPOINT="https://panel.example/api",
        CELERITY_PANEL_USERNAME="admin",
        CELERITY_PANEL_PASSWORD="panel-secret",
    )
    def test_login_and_form_post_do_not_return_the_obfs_password(self):
        reset_panel_session_cache()
        session = _FormSession()
        with patch("bot.main.celerity_panel_form.requests.Session", return_value=session):
            ok, detail = save_node_obfs_via_panel(
                "node-1",
                {"name": "DE-1", "ip": "203.0.113.10", "groups": ["group-1"]},
                "obfs-secret",
            )
        self.assertTrue(ok)
        self.assertNotIn("obfs-secret", detail)
        self.assertNotIn("panel-secret", detail)
        form_post = session.posts[1]
        self.assertIn("/panel/nodes/node-1", form_post[0])
        posted = dict(form_post[2])
        self.assertEqual(posted["obfs.password"], "obfs-secret")
        self.assertEqual(posted["groups"], "group-1")
        reset_panel_session_cache()

    @override_settings(
        C3CELERYTY_API_ENDPOINT="https://panel.example/api",
        CELERITY_PANEL_USERNAME="admin",
        CELERITY_PANEL_PASSWORD="panel-secret",
    )
    def test_form_redirect_with_error_is_not_success(self):
        reset_panel_session_cache()
        session = _FormSession(error="Имя обязательно")
        with patch("bot.main.celerity_panel_form.requests.Session", return_value=session):
            ok, detail = save_node_obfs_via_panel(
                "node-1",
                {"name": "DE-1", "ip": "203.0.113.10", "groups": ["group-1"]},
                "obfs-secret",
            )
        self.assertFalse(ok)
        self.assertIn("Имя обязательно", detail)
        self.assertNotIn("obfs-secret", detail)
        reset_panel_session_cache()


class _FormSession:
    def __init__(self, error=""):
        self.posts = []
        self.error = error

    def post(self, url, json=None, data=None, timeout=None, allow_redirects=True):
        self.posts.append((url, json, data))
        response = _FormResponse()
        response.status_code = 200
        response.url = url
        if self.error and data is not None:
            response.url = url + "?error=" + self.error.replace(" ", "%20")
        response.payload = {"success": True}
        return response


class _FormResponse:
    status_code = 200
    url = ""
    payload = None

    def json(self):
        return self.payload or {}
