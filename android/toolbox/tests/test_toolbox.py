from __future__ import annotations

import json
import queue
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from android import xapk_installer
from android.closeEmulator.close_emulators import close_emulator, emulator_serials
from android.removeGpCheck import gpcheck_core as gp
from android.toolbox import operations
from android.toolbox.app import MainWindow
from android.toolbox.registry import Registry, ToolSpec, builtins
from android.toolbox.services import (
    AppContext, Cancelled, Device, Devices, Execution, Outcome, Preferences, Task, Tasks, Tools, parse_devices,
)


APP = QApplication.instance() or QApplication([])
APP.setStyle("Fusion")


def wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("Timed out waiting for task")
        QTest.qWait(20)


class CoreTests(unittest.TestCase):
    def test_device_parser_and_emulator_filter(self):
        output = "List of devices attached\nphone123 device model:Galaxy_S23\nemulator-5554 offline\nemulator-5556 device model:Pixel_8\nusb unauthorized\n* daemon started successfully *\n"
        devices = parse_devices(output)
        self.assertEqual(len(devices), 4)
        self.assertEqual(devices[0].model, "Galaxy S23")
        self.assertFalse(devices[0].emulator)
        self.assertEqual(emulator_serials(output), ["emulator-5554", "emulator-5556"])

    def test_emulator_close_rejects_physical_device(self):
        runner = Mock()
        with self.assertRaises(ValueError):
            close_emulator("phone123", "adb", runner)
        runner.assert_not_called()

    def test_emulator_close_confirms_disappearance(self):
        runner = Mock(side_effect=[(0, "OK"), (0, "List of devices attached\nphone123 device\n")])
        close_emulator("emulator-5554", "adb.exe", runner)
        self.assertEqual(runner.call_args_list[0].args[0], ["adb.exe", "-s", "emulator-5554", "emu", "kill"])
        self.assertEqual(len(runner.call_args_list), 2)

    def test_emulator_ack_without_exit_is_not_success(self):
        runner = Mock(return_value=(0, "OK"))
        with self.assertRaises(TimeoutError):
            close_emulator("emulator-5554", "adb", runner, timeout=0)

    def test_apk_installer_uses_injected_target_and_flags(self):
        with tempfile.TemporaryDirectory(prefix="toolbox space ") as folder:
            package = Path(folder) / "测试 APK.apk"
            package.touch()
            runner = Mock(side_effect=[(0, "List of devices attached\nphone device\nother device\n"), (0, "Success")])
            original = xapk_installer.ADB_PATH
            xapk_installer.install_xapk(package, serial="phone", keep_data=True, downgrade=True,
                                       adb_path="custom-adb", runner=runner, log=lambda _: None)
            self.assertEqual(runner.call_args_list[-1].args[0],
                             ["custom-adb", "-s", "phone", "install", "-r", "-d", str(package.resolve())])
            self.assertEqual(xapk_installer.ADB_PATH, original)

    def test_gpcheck_queries_remain_bound_to_selected_device(self):
        calls = []
        def runner(args, **kwargs):
            args = [str(a) for a in args]
            calls.append(args)
            if args[-1] == "devices":
                return 0, "List of devices attached\nphone device\nemulator-5554 device\n"
            if args[-2:] == ["wm", "density"]:
                return 0, "Physical density: 420"
            return 0, "arm64-v8a"
        with tempfile.TemporaryDirectory() as folder:
            executable = Path(folder) / "adb.exe"
            executable.touch()
            chain = gp.Toolchain(executable, executable, executable, executable, Path(folder),
                                 serial="emulator-5554", runner=runner)
            info = gp.read_device_info(chain)
            self.assertEqual(info.serial, "emulator-5554")
            self.assertTrue(all(args[1:3] == ["-s", "emulator-5554"] for args in calls[1:]))
            chain.serial = "missing"
            with self.assertRaises(gp.GpCheckError):
                gp.read_device_info(chain)

    def test_install_batch_records_failure_and_continues(self):
        context = Mock()
        with patch.object(Tools, "require"), patch.object(xapk_installer, "install_xapk", side_effect=[RuntimeError("bad"), None]):
            result = operations.install_packages(context, ["a.apk", "b.apk"], "phone", {"adb": "adb"})
        self.assertEqual(result.status, "partial")
        self.assertEqual([item["status"] for item in result.items], ["failed", "success"])


class TaskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.preferences = Preferences(Path(self.temp.name))
        self.tasks = Tasks(self.preferences)

    def tearDown(self):
        for task in self.tasks.tasks:
            self.tasks.cancel(task)
        wait_until(lambda: self.tasks.active is None)
        self.tasks.timer.stop()
        self.temp.cleanup()

    def test_fifo_execution_and_queued_cancellation(self):
        gate = threading.Event()
        calls = []
        def first(ctx):
            gate.wait(2)
            calls.append("first")
        first_task = self.tasks.submit("first", "test", first)
        cancelled = self.tasks.submit("cancel", "test", lambda ctx: calls.append("wrong"))
        last = self.tasks.submit("last", "test", lambda ctx: calls.append("last"))
        self.tasks.cancel(cancelled)
        gate.set()
        wait_until(lambda: last.status == "success")
        self.assertEqual(calls, ["first", "last"])
        self.assertEqual(first_task.status, "success")
        self.assertEqual(cancelled.status, "cancelled")

    def test_running_cancel_stops_at_checkpoint(self):
        gate = threading.Event()
        reached = []
        def work(ctx):
            gate.wait(2)
            ctx.checkpoint()
            reached.append(True)
        task = self.tasks.submit("stop", "test", work)
        self.tasks.cancel(task)
        gate.set()
        wait_until(lambda: task.status == "cancelled")
        self.assertFalse(reached)

    def test_command_output_and_timeout(self):
        task = self.tasks.submit("run", "test", lambda ctx: Outcome(value=ctx.run(
            [sys.executable, "-c", "print('hello')"], timeout=3)))
        wait_until(lambda: task.status == "success")
        self.assertIn("hello", task.outcome.value[1])
        timed = self.tasks.submit("timeout", "test", lambda ctx: ctx.run(
            [sys.executable, "-c", "import time; time.sleep(20)"], timeout=0.2))
        wait_until(lambda: timed.status == "failed")
        self.assertIn("超时", timed.message)

    def test_failed_task_does_not_block_next_task(self):
        bad = self.tasks.submit("bad", "test", lambda ctx: 1 / 0)
        good = self.tasks.submit("good", "test", lambda ctx: Outcome())
        wait_until(lambda: good.status == "success")
        self.assertEqual(bad.status, "failed")

    def test_interrupted_history_is_not_replayed(self):
        self.tasks.history_path.write_text(json.dumps([
            {"id": "old", "title": "old", "module": "test", "status": "running"}]), encoding="utf-8")
        loaded = Tasks(self.preferences)
        self.assertEqual(loaded.tasks[0].status, "interrupted")
        self.assertIsNone(loaded.tasks[0].operation)
        loaded.timer.stop()

    def test_command_logging_redacts_password(self):
        task = Task("test", "test", None)
        execution = Execution(task, queue.Queue(), self.preferences.logs / "redaction.log")
        with patch("android.toolbox.services.subprocess.Popen", side_effect=FileNotFoundError):
            with self.assertRaises(FileNotFoundError):
                execution.run(["missing", "--ks-pass", "pass:secret-value"])
        self.assertNotIn("secret-value", execution.log_path.read_text(encoding="utf-8"))


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.refresh = patch.object(Devices, "refresh")
        self.refresh.start()
        self.context = AppContext(Path(self.temp.name))
        self.window = MainWindow(self.context)
        self.window.show()
        APP.processEvents()

    def tearDown(self):
        wait_until(lambda: self.context.tasks.active is None)
        self.window.close()
        self.context.devices.timer.stop()
        self.context.devices.refresh_timer.stop()
        self.context.tasks.timer.stop()
        self.refresh.stop()
        self.temp.cleanup()

    def test_all_pages_load_and_keep_input_after_navigation(self):
        for key in self.window.registry.entries:
            self.window.show_page(key)
            self.assertNotIsInstance(self.window.pages[key][1], QLabel)
        page = self.window.pages["gpcheck"][1]
        page.source.edit.setText("example.xapk")
        self.window.show_page("install")
        self.window.show_page("gpcheck")
        self.assertEqual(page.source.text(), "example.xapk")

    def test_device_disconnect_never_switches_target(self):
        self.context.selected_serial = "original"
        self.context.devices.items = [Device("other", "device")]
        self.window.update_devices(self.context.devices.items, "")
        self.assertEqual(self.context.selected_serial, "original")
        with self.assertRaises(RuntimeError):
            self.context.target()

    def test_install_snapshot_and_partial_results(self):
        page = self.window.pages["install"][1]
        package = Path(self.temp.name) / "测试.apk"
        package.touch()
        page.add_files([str(package)])
        self.context.devices.items = [Device("one", "device"), Device("two", "device")]
        self.context.selected_serial = "one"
        gate = threading.Event()
        self.context.tasks.submit("wait", "test", lambda ctx: (gate.wait(2), Outcome())[1])
        captured = []
        def operation(ctx, files, serial, tools, keep, downgrade):
            captured.append((serial, keep))
            return Outcome("failed", [{"name": str(package), "status": "failed", "detail": "sample failure"}])
        with patch.object(Tools, "require"), patch.object(operations, "install_packages", operation):
            page.submit()
            self.context.selected_serial = "two"
            page.keep.setChecked(True)
            gate.set()
            wait_until(lambda: not page.pending)
        self.assertEqual(captured, [("one", False)])
        self.assertTrue(page.retry.isEnabled())
        self.assertIn("sample failure", page.files.item(0, 2).toolTip())

    def test_new_registered_module_uses_existing_window(self):
        registry = builtins()
        original = registry.entries["install"]
        registry.register(ToolSpec("sample", "Sample", "Extra", original.icon, original.factory))
        window = MainWindow(self.context, registry)
        window.show_page("sample")
        self.assertEqual(type(window.pages["sample"][1]).__name__, "InstallPage")
        with self.assertRaises(ValueError):
            registry.register(original)
        window.close()

    def test_small_window_has_scroll_access_to_gpcheck_controls(self):
        self.window.show_page("gpcheck")
        self.window.resize(800, 600)
        APP.processEvents()
        scroll, page = self.window.pages["gpcheck"]
        scroll.ensureWidgetVisible(page.open_button)
        APP.processEvents()
        self.assertLessEqual(page.width(), scroll.viewport().width())
        self.assertTrue(page.open_button.isVisible())
        self.assertEqual(self.window.sidebar.width(), 64)


if __name__ == "__main__":
    unittest.main()
