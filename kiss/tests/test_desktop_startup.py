"""The native app must become ready before optional CLI login probes."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kiss_cli import gui


class DesktopStartupTests(unittest.TestCase):
    def test_server_starts_without_waiting_for_provider_health(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = mock.MagicMock(models_dir=root / "models")
            catalog.__len__.return_value = 127
            with mock.patch.object(gui, "Handler"), \
                 mock.patch.object(gui.Catalog, "discover", return_value=catalog), \
                 mock.patch.object(gui, "GeoForgeHTTPServer") as server, \
                 mock.patch.object(gui.providers, "available",
                                   side_effect=AssertionError("blocking login probe")), \
                 mock.patch("kiss_cli.firstrun.data_dir", return_value=root):
                server.return_value.serve_forever.side_effect = KeyboardInterrupt
                self.assertEqual(gui.serve(None, open_browser=False,
                                           workroot=root / "installs"), 0)
                server.return_value.serve_forever.assert_called_once()

    def test_loopback_bind_does_not_wait_for_reverse_dns(self):
        with mock.patch("socket.getfqdn", side_effect=AssertionError("reverse DNS")):
            with gui.GeoForgeHTTPServer(("127.0.0.1", 0), gui.Handler) as server:
                self.assertEqual(server.server_name, "127.0.0.1")
                self.assertGreater(server.server_port, 0)
