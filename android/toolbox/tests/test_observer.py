import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from android.toolbox.device_observer import Observation, collect, parse_details, parse_foreground
from android.toolbox.observer_page import ForegroundPage
from android.toolbox.services import AppContext, Device


APP = QApplication.instance() or QApplication([])


class ParserTests(unittest.TestCase):
    def test_activity_owner_is_not_sdk_class_namespace(self):
        rows = dict(parse_foreground({
            "Activity": "mResumedActivity: ActivityRecord{abc u0 com.example.app/com.google.ads.AdActivity t3}",
            "Window": "mCurrentFocus=Window{abc u0 InputMethod}\nmTopFocusedDisplayId=0",
        }))
        self.assertEqual(rows["前台包名"], "com.example.app")
        self.assertIn("InputMethod", rows["焦点 Window"])
        self.assertEqual(rows["焦点显示屏"], "0")

    def test_missing_fields_are_not_zero(self):
        rows = dict(parse_details({}))
        self.assertEqual(rows["总内存"], "未提供")
        self.assertEqual(rows["电池温度"], "未提供")
        self.assertEqual(dict(parse_foreground({}))["前台包名"], "未提供")

    def test_window_details_belong_to_focused_window(self):
        rows = dict(parse_foreground({"Window":
            "mCurrentFocus=Window{b u0 InputMethod}\n"
            "Window #0 Window{a u0 App}:\n mDisplayId=0 ty=BASE_APPLICATION mFrame=[0,0][100,200]\n"
            "Window #1 Window{b u0 InputMethod}:\n mDisplayId=2 ty=INPUT_METHOD mFrame=[0,100][100,200]\n"}))
        self.assertEqual(rows["焦点显示屏"], "2")
        self.assertEqual(rows["Window 类型"], "INPUT_METHOD")
        self.assertEqual(rows["Window 边界"], "[0,100][100,200]")

    def test_memory_and_battery_units(self):
        rows = dict(parse_details({"内存": "MemTotal: 8388608 kB",
                                   "电池": "  level: 50\n  scale: 100\n  temperature: 321"}))
        self.assertEqual(rows["总内存"], "8.00 GiB")
        self.assertEqual(rows["电量"], "50%")
        self.assertEqual(rows["电池温度"], "32.1 °C")

    def test_all_queries_capture_serial_and_window_fallback(self):
        import subprocess
        outputs = ["mResumedActivity: ActivityRecord{x u0 a.b/.Main}", "",
                   "mCurrentFocus=Window{x u0 a.b/.Main}", "123"]
        with patch("android.toolbox.device_observer.subprocess.run", side_effect=[
            subprocess.CompletedProcess([], 0, out, "") for out in outputs
        ]) as run:
            result = collect("adb", "phone-A", "foreground", threading.Event())
        self.assertEqual(dict(result.rows)["PID"], "123")
        for call in run.call_args_list:
            self.assertEqual(call.args[0][:4], ["adb", "-s", "phone-A", "shell"])


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.context = AppContext(Path(self.folder.name))
        self.context.devices.refresh_timer.stop()
        self.context.devices.items = [Device("A", "device"), Device("B", "device")]
        self.manager = self.context.sessions
        self.manager.timer.stop()

    def tearDown(self):
        self.manager.close()
        self.context.devices.timer.stop()
        self.context.tasks.timer.stop()
        self.folder.cleanup()

    def test_consumers_share_one_session(self):
        self.manager.subscribe("one", "A", "foreground")
        self.manager.subscribe("two", "A", "foreground")
        self.assertEqual(len(self.manager.sessions), 1)
        self.manager.unsubscribe("one")
        self.assertFalse(self.manager.sessions[("A", "foreground")].stop.is_set())
        self.manager.unsubscribe("two")
        self.assertTrue(self.manager.sessions[("A", "foreground")].stop.is_set())

    def test_late_result_after_disconnect_is_discarded(self):
        self.manager.subscribe("one", "A", "foreground")
        session = self.manager.sessions[("A", "foreground")]
        session.busy = True
        result = Observation("A", "foreground", time.time(), (), "old")
        self.manager.events.put((("A", "foreground"), session, session.generation, result))
        received = []
        self.manager.updated.connect(received.append)
        self.context.devices.items = []
        self.manager.poll()
        self.assertEqual(received, [])

    def test_device_switch_clears_and_rejects_old_result(self):
        self.context.selected_serial = "A"
        page = ForegroundPage(self.context)
        page.show()
        APP.processEvents()
        page.receive(Observation("A", "foreground", time.time(), (("Activity", "a/.Main"),), "a"))
        self.context.selected_serial = "B"
        page.receive(Observation("A", "foreground", time.time(), (), "stale"))
        self.assertIsNone(page.snapshot)
        self.assertEqual(page.raw.toPlainText(), "")
        self.assertEqual(len(page.history), 0)
        page.close()

    def test_selection_signal_only_emits_changes(self):
        received = []
        self.context.selection_changed.connect(received.append)
        self.context.selected_serial = "A"
        self.context.selected_serial = "A"
        self.assertEqual(received, ["A"])


if __name__ == "__main__":
    unittest.main()
