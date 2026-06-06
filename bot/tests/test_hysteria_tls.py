from django.test import SimpleTestCase

from bot.main.celerity_key_issue import sanitize_hysteria2_uri_for_happ
from bot.main.hysteria_tls_meta import (
    parse_hysteria_cert_ssh_output,
    parse_pin_sha256_from_fingerprint_line,
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
        self.assertIn("pinSHA256=3E0CAA6110D55DC28123208EB5495C8D8C881DB3D8371C1E2F87AD0CEECDDB6E", out)
        self.assertNotIn("insecure", out)

    def test_sanitize_requires_pin_and_sni(self):
        with self.assertRaises(ValueError):
            sanitize_hysteria2_uri_for_happ("hysteria2://u:p@1.2.3.4:443", sni="", pin_sha256="AB")
