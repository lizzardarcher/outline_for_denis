"""Unit tests for pasarguard_key_issue helpers."""

from django.test import SimpleTestCase

from bot.main.pasarguard_key_issue import pick_pasarguard_link
from bot.models import Server


class PickPasarGuardLinkTests(SimpleTestCase):
    def test_pick_vless(self):
        server = Server(ip_address="1.2.3.4")
        links = [
            "ss://abc@1.2.3.4:1040",
            "vless://uuid@1.2.3.4:443?security=reality",
        ]
        self.assertIn("vless://", pick_pasarguard_link(links, server, "vless"))

    def test_pick_outline(self):
        server = Server(ip_address="1.2.3.4")
        links = [
            "vless://uuid@1.2.3.4:443",
            "ss://abc@1.2.3.4:1040",
        ]
        url = pick_pasarguard_link(links, server, "outline")
        self.assertTrue(url.startswith("ss://"))
        self.assertNotIn("vless://", url)
