from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from bot.main.server_panel_cleanup import (
    delete_server_from_celerity,
    delete_server_from_marzban,
)
from bot.models import Server

class ServerPanelCleanupTests(SimpleTestCase):
    def _server(self, ip="1.2.3.4", pk=42):
        return Server(pk=pk, hosting="test-host", ip_address=ip)

    @patch("bot.main.server_panel_cleanup._log")
    def test_delete_marzban_by_ip(self, log_mock):
        server = self._server()
        api = MagicMock()
        api.find_node_ids_by_ip.return_value = (True, [7, 8])
        api.delete_node.side_effect = [(True, None), (True, None)]

        deleted, failed = delete_server_from_marzban(server, api=api)

        self.assertEqual(deleted, 2)
        self.assertEqual(failed, 0)
        api.find_node_ids_by_ip.assert_called_once_with("1.2.3.4")
        self.assertEqual(api.delete_node.call_count, 2)

    @patch("bot.main.server_panel_cleanup._log")
    def test_delete_celerity_by_ip(self, log_mock):
        server = self._server()
        api = MagicMock()
        api.find_node_ids_by_ip.return_value = (True, ["abc123"])
        api.delete_node.return_value = (True, None)

        deleted, failed = delete_server_from_celerity(server, api=api)

        self.assertEqual(deleted, 1)
        self.assertEqual(failed, 0)
        api.delete_node.assert_called_once_with("abc123")

    @patch("bot.main.server_panel_cleanup._log")
    def test_skip_when_ip_empty(self, log_mock):
        server = self._server(ip="")
        api = MagicMock()

        deleted, failed = delete_server_from_marzban(server, api=api)

        self.assertEqual(deleted, 0)
        self.assertEqual(failed, 0)
        api.find_node_ids_by_ip.assert_not_called()

    @patch("bot.main.server_panel_cleanup._log")
    def test_marzban_not_found_is_ok(self, log_mock):
        server = self._server()
        api = MagicMock()
        api.find_node_ids_by_ip.return_value = (False, "Нода Marzban с ip='1.2.3.4' не найдена")

        deleted, failed = delete_server_from_marzban(server, api=api)

        self.assertEqual(deleted, 0)
        self.assertEqual(failed, 0)
        api.delete_node.assert_not_called()
