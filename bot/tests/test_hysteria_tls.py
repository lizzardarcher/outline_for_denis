
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase


from bot.main.celerity_key_issue import (
    ensure_hysteria2_insecure,
    hysteria2_uri_has_salamander,
    issue_hysteria2_tls_for_user,
    persist_hysteria2_insecure,
    sanitize_hysteria2_uri_for_happ,
)
from bot.models import Server, TelegramUser, VpnKey
from bot.main.hysteria_tls_meta import (
    parse_hysteria_cert_ssh_output,
    parse_pin_sha256_from_fingerprint_line,
    parse_pin_sha256_from_sha256sum_line,
    parse_sni_from_subject_line,
)

class HysteriaTlsMetaParseTests(SimpleTestCase):
    def test_parse_pin_from_fingerprint(self):
        line = "sha256 Fingerprint=3E:0C:AA:61:10:D5:5D:C2:81:23:20:8E:B5:49:5C:8D:8C:88:1D:B3:D8:37:1C:1E:2F:87:AD:0C:EE:CD:DB:6E"
        self.assertEqual(
            parse_pin_sha256_from_fingerprint_line(line),
            "3E0CAA6110D55DC28123208EB5495C8D8C881DB3D8371C1E2F87AD0CEECDDB6E",
        )


    def test_parse_sni_from_subject(self):
        self.assertEqual(parse_sni_from_subject_line("subject=CN = bing.com"), "bing.com")
        self.assertEqual(
            parse_sni_from_subject_line("subject=C=US, CN=example.com, O=Test"),
            "example.com",
        )

    def test_parse_sha256sum_line(self):
        self.assertEqual(
            parse_pin_sha256_from_sha256sum_line(
                "3e0caa6110d55dc28123208eb5495c8d8c881db3d8371c1e2f87ad0ceecddb6e  -"
            ),
            "3E0CAA6110D55DC28123208EB5495C8D8C881DB3D8371C1E2F87AD0CEECDDB6E",
        )

    def test_parse_ssh_output_prefers_sha256sum(self):
        stdout = (
            "3E0CAA6110D55DC28123208EB5495C8D8C881DB3D8371C1E2F87AD0CEECDDB6E  -\n"
            "sha256 Fingerprint=AA:AA:AA:61:10:D5:5D:C2:81:23:20:8E:B5:49:5C:8D:8C:88:1D:B3:D8:37:1C:1E:2F:87:AD:0C:EE:CD:DB:6E\n"
            "subject=CN = bing.com\n"
        )
        pin, sni = parse_hysteria_cert_ssh_output(stdout)
        self.assertEqual(sni, "bing.com")
        self.assertTrue(pin.startswith("3E0CAA61"))

    def test_parse_ssh_output(self):
        stdout = (
            "sha256 Fingerprint=3E:0C:AA:61:10:D5:5D:C2:81:23:20:8E:B5:49:5C:8D:8C:88:1D:B3:D8:37:1C:1E:2F:87:AD:0C:EE:CD:DB:6E\n"
            "subject=CN = bing.com\n"
        )
        pin, sni = parse_hysteria_cert_ssh_output(stdout)
        self.assertEqual(sni, "bing.com")
        self.assertTrue(pin.startswith("3E0CAA61"))


class SanitizeHysteriaUriTests(SimpleTestCase):
    def test_sanitize_hopping_uri(self):
        raw = (
            "hysteria2://u:p@217.65.79.212:443"
            "?mport=443,8443,2096&insecure=1&alpn=h3&sni=www.microsoft.com#NL8"
        )
        out = sanitize_hysteria2_uri_for_happ(
            raw,
            sni="bing.com",
            pin_sha256="3E0CAA6110D55DC28123208EB5495C8D8C881DB3D8371C1E2F87AD0CEECDDB6E",
        )
        self.assertIn("mport=443", out)
        self.assertIn("sni=bing.com", out)
        self.assertIn(
            "insecure=1&pinSHA256=3E0CAA6110D55DC28123208EB5495C8D8C881DB3D8371C1E2F87AD0CEECDDB6E",
            out,
        )
        self.assertEqual(out.count("insecure=1"), 1)
        self.assertTrue(out.endswith("#NL8"))

    def test_sanitize_keeps_salamander(self):
        raw = "hysteria2://u:p@10.9.3.1:443?obfs=salamander&obfs-password=keep-me&insecure=1"
        out = sanitize_hysteria2_uri_for_happ(raw, sni="bing.com", pin_sha256="AB")
        self.assertTrue(hysteria2_uri_has_salamander(out))
        self.assertIn("insecure=1&pinSHA256=AB", out)
        self.assertEqual(out.count("insecure=1"), 1)


class HysteriaRoleLinkTests(TestCase):
    def _server(self, role):
        return Server.objects.create(
            hosting="hy",
            ip_address="10.9.3.1",
            is_active=True,
            is_c3celeryty_activated=True,
            node_role=role,
            hysteria_tls_sni="bing.com",
            hysteria_pin_sha256="AB",
        )

    def _issue(self, subscription):
        api = type("Api", (), {})()
        api.delete_user = lambda uid: (True, None)
        api.create_user = lambda body: (True, {})
        api.get_user = lambda uid: (True, {"subscriptionToken": "tok"})
        api.get_subscription_content = lambda token, params=None: (True, subscription)
        with patch("bot.main.celerity_key_issue.CelerityAPI", return_value=api), \
                patch("bot.main.celerity_key_issue.MarzbanAPI"), \
                patch("bot.main.celerity_key_issue.try_delete_pasarguard_user"), \
                patch("bot.main.celerity_key_issue._celerity_group_id", return_value="g1"):
            return issue_hysteria2_tls_for_user(
                telegram_user_id=7,
                display_username="user",
                server_ip="10.9.3.1",
            )

    def test_role_server_rejects_tls_link_without_salamander(self):
        self._server(Server.NODE_ROLE_HYSTERIA2)
        ok, detail = self._issue("hysteria2://u:p@10.9.3.1:443?insecure=1\n")
        self.assertFalse(ok)
        self.assertIn("salamander", detail)

    def test_legacy_server_still_accepts_tls_link(self):
        self._server("")
        ok, uri = self._issue("hysteria2://u:p@10.9.3.1:443?insecure=1\n")
        self.assertTrue(ok, uri)
        self.assertIn("insecure=1&pinSHA256=AB", uri)
        self.assertEqual(uri.count("insecure=1"), 1)
        self.assertNotIn("obfs=salamander", uri)

    def test_role_server_accepts_salamander_link(self):
        self._server(Server.NODE_ROLE_HYSTERIA2)
        ok, uri = self._issue(
            "hysteria2://u:p@10.9.3.1:443?obfs=salamander&obfs-password=keep-me\n"
        )
        self.assertTrue(ok, uri)
        self.assertIn("obfs=salamander", uri)
        self.assertIn("obfs-password=keep-me", uri)
        self.assertIn("insecure=1&pinSHA256=AB", uri)
        self.assertEqual(uri.count("insecure=1"), 1)

    def test_sanitize_requires_pin_and_sni(self):
        with self.assertRaises(ValueError):
            sanitize_hysteria2_uri_for_happ("hysteria2://u:p@1.2.3.4:443", sni="", pin_sha256="AB")


class EnsureHysteriaInsecureTests(SimpleTestCase):
    def test_inserts_before_pin_and_keeps_fragment(self):
        raw = (
            "hysteria2://USER:PASS@170.168.33.111:443"
            "?sni=bing.com&alpn=h3&obfs=salamander&obfs-password=XXX"
            "&pinSHA256=939277F789BD5591EEE7DE7A45CF3B4E801560050D3F0B8C0330C52445F01FCC"
            "#RWDKZ2%20TLS"
        )
        out = ensure_hysteria2_insecure(raw)
        self.assertIn(
            "obfs-password=XXX&insecure=1&pinSHA256=939277F789BD5591EEE7DE7A45CF3B4E801560050D3F0B8C0330C52445F01FCC",
            out,
        )
        self.assertTrue(out.endswith("#RWDKZ2%20TLS"))
        self.assertEqual(out.count("insecure=1"), 1)

    def test_appends_when_pin_missing(self):
        raw = "hysteria2://u:p@1.2.3.4:443?sni=bing.com&alpn=h3#NAME%20TLS"
        out = ensure_hysteria2_insecure(raw)
        self.assertEqual(
            out,
            "hysteria2://u:p@1.2.3.4:443?sni=bing.com&alpn=h3&insecure=1#NAME%20TLS",
        )

    def test_adds_query_when_link_has_only_fragment(self):
        raw = "hysteria2://u:p@1.2.3.4:443#NAME%20TLS"
        self.assertEqual(
            ensure_hysteria2_insecure(raw),
            "hysteria2://u:p@1.2.3.4:443?insecure=1#NAME%20TLS",
        )

    def test_does_not_duplicate_existing_insecure(self):
        raw = "hysteria2://u:p@1.2.3.4:443?sni=bing.com&insecure=1&pinSHA256=AB#NAME%20TLS"
        self.assertEqual(ensure_hysteria2_insecure(raw), raw)

    def test_leaves_non_hysteria_uri(self):
        raw = "vless://uuid@1.2.3.4:443?security=tls#name"
        self.assertEqual(ensure_hysteria2_insecure(raw), raw)


class PersistHysteriaInsecureTests(TestCase):
    def test_rewrites_stored_key_once(self):
        user = TelegramUser.objects.create(user_id=77, first_name="A")
        key = VpnKey.objects.create(
            user=user,
            key_id="77",
            protocol="hysteria2",
            access_url="hysteria2://u:p@1.2.3.4:443?sni=bing.com&pinSHA256=AB#NAME%20TLS",
        )
        persist_hysteria2_insecure(key)
        key.refresh_from_db()
        self.assertEqual(
            key.access_url,
            "hysteria2://u:p@1.2.3.4:443?sni=bing.com&insecure=1&pinSHA256=AB#NAME%20TLS",
        )
        persist_hysteria2_insecure(key)
        key.refresh_from_db()
        self.assertEqual(key.access_url.count("insecure=1"), 1)

    def test_stored_key_without_pin_gets_insecure_at_end(self):
        user = TelegramUser.objects.create(user_id=78, first_name="B")
        key = VpnKey.objects.create(
            user=user,
            key_id="78",
            protocol="hysteria2",
            access_url="hysteria2://u:p@1.2.3.4:443?sni=bing.com&alpn=h3#NAME%20TLS",
        )
        persist_hysteria2_insecure(key)
        key.refresh_from_db()
        self.assertEqual(
            key.access_url,
            "hysteria2://u:p@1.2.3.4:443?sni=bing.com&alpn=h3&insecure=1#NAME%20TLS",
        )
