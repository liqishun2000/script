import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication

from android.toolbox.screen_control import ScreenWindow, scrcpy_arguments
from android.toolbox.services import AppContext, Device, Tools


APP = QApplication.instance() or QApplication([])


class ScreenTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.context = AppContext(Path(self.folder.name))
        self.context.devices.refresh_timer.stop()
        self.context.devices.items = [Device("phone-A", "device"), Device("phone-B", "device")]
        self.require = patch.object(Tools, "require")
        self.require.start()
        self.start = patch.object(ScreenWindow, "start")
        self.start.start()

    def tearDown(self):
        self.context.screens.close()
        self.context.sessions.close()
        self.context.devices.timer.stop()
        self.context.tasks.timer.stop()
        APP.processEvents()
        self.require.stop()
        self.start.stop()
        self.folder.cleanup()

    def test_reopen_reuses_window_and_selection_does_not_retarget(self):
        window = self.context.screens.open("phone-A")
        self.context.selected_serial = "phone-B"
        self.assertIs(window, self.context.screens.open("phone-A"))
        self.assertEqual(window.serial, "phone-A")
        self.assertEqual(len(self.context.screens.windows), 1)

    def test_disconnect_pauses_and_same_serial_reconnects(self):
        window = self.context.screens.open("phone-A")
        window.devices_changed([Device("phone-B", "device")], "")
        self.assertTrue(window.retry_on_connect)
        self.assertTrue(all(not button.isEnabled() for button in window.keys))
        with patch.object(window, "start") as start:
            window.devices_changed([Device("phone-A", "device")], "")
            start.assert_called_once()

    def test_close_removes_only_its_window(self):
        first = self.context.screens.open("phone-A")
        second = self.context.screens.open("phone-B")
        first.close()
        self.assertEqual(list(self.context.screens.windows), ["phone-B"])
        self.assertFalse(second.closed)

    def test_keyboard_command_captures_original_device(self):
        window = self.context.screens.open("phone-A")
        window.hwnd = 123
        self.context.selected_serial = "phone-B"
        with patch.object(QProcess, "start") as start:
            window.key(3)
            self.assertEqual(start.call_args.args[1], ["-s", "phone-A", "shell", "input", "keyevent", "3"])

    def test_disconnected_window_rejects_keys(self):
        window = self.context.screens.open("phone-A")
        with patch.object(QProcess, "start") as start:
            window.key(3)
            start.assert_not_called()

    def test_arguments_preserve_serial_and_finite_quality(self):
        args = scrcpy_arguments("192.168.1.2:5555", 1)
        self.assertEqual(args[:2], ["--serial", "192.168.1.2:5555"])
        self.assertIn("--no-audio", args)
        self.assertIn("--max-size=1080", args)
        self.assertIn("--render-driver=software", args)
        self.assertNotIn("--kill-adb-on-close", args)


if __name__ == "__main__":
    unittest.main()
