"""Startup regressions: reopen the existing HUD without spawning another server."""
import unittest
from unittest.mock import patch, MagicMock
from core.launcher import is_jarvis_running, open_hud


class LauncherTests(unittest.TestCase):
    def test_identifies_jarvis_before_reusing_a_port(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"status":"online","engine":"Hermes AIAgent"}'
        with patch('core.launcher.build_opener') as opener:
            opener.return_value.open.return_value = response
            self.assertTrue(is_jarvis_running(8000))
            response.__enter__.return_value.read.return_value = b'{"status":"online","engine":"another service"}'
            self.assertFalse(is_jarvis_running(8000))

    def test_opens_app_window_with_literal_arguments(self):
        with patch('core.launcher.Path.is_file',return_value=True), patch('core.launcher.subprocess.Popen') as launch:
            self.assertTrue(open_hud(8000))
            args = launch.call_args.args[0]
            self.assertIn('--app=http://127.0.0.1:8000',args)
            self.assertNotIn('shell',launch.call_args.kwargs)

    def test_relaunch_reuses_existing_server(self):
        import run_jarvis
        sock = MagicMock()
        sock.__enter__.return_value.connect_ex.return_value = 0
        with patch('sys.argv',['run_jarvis.py']), patch.object(run_jarvis.socket,'socket',return_value=sock), \
             patch.object(run_jarvis,'is_jarvis_running',return_value=True), patch.object(run_jarvis,'open_hud') as open_window, \
             patch.object(run_jarvis.uvicorn,'Server') as server:
            run_jarvis.main()
            open_window.assert_called_once()
            server.assert_not_called()
