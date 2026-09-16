import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from android.toolbox.metrics import collect_metrics
from android.toolbox.services import AppContext, Device

APP = QApplication.instance() or QApplication([])

class MetricTests(unittest.TestCase):
    def test_device_delta_is_normalized(self):
        outputs = ["cpu 100 0 100 800 0 0 0 0 0\n", "MemTotal: 1000 kB\nMemAvailable: 500 kB\n",
                   "level: 50\ntemperature: 300\n", "thermal status\n", "cpu 150 0 150 850 0 0 0 0 0\n", "MemTotal: 1000 kB\nMemAvailable: 500 kB\n", "level: 50\ntemperature: 300\n", "thermal status\n"]
        with patch("android.toolbox.metrics.subprocess.run", side_effect=[subprocess.CompletedProcess([], 0, x, "") for x in outputs]):
            _, state = collect_metrics("adb", "A", "device_metrics")
        with patch("android.toolbox.metrics.subprocess.run", side_effect=[subprocess.CompletedProcess([], 0, x, "") for x in outputs[4:]]):
            sample, _ = collect_metrics("adb", "A", "device_metrics", state)
        self.assertEqual(dict(sample.values)["CPU 总使用率"], "66.7%")
        self.assertEqual(dict(sample.values)["温度服务"], "可用")

    def test_app_metrics_keep_unavailable_as_na(self):
        outputs = ["123", "TOTAL PSS: 200\n", ""]
        with patch("android.toolbox.metrics.subprocess.run", side_effect=[subprocess.CompletedProcess([], 0, x, "") for x in outputs]):
            sample, _ = collect_metrics("adb", "A", "app_metrics", "pkg")
        self.assertEqual(dict(sample.values)["PID"], "123")
        self.assertEqual(dict(sample.values)["TOTAL PSS"], "200 kB")
        self.assertEqual(dict(sample.values)["CPU"], "N/A")

    def test_context_owns_shared_metric_manager(self):
        with tempfile.TemporaryDirectory() as folder:
            context = AppContext(Path(folder))
            context.devices.items = [Device("A", "device")]
            self.assertIsNotNone(context.metrics)
            context.metrics.close(); context.metric_windows.close(); context.sessions.close()
            context.devices.timer.stop(); context.devices.refresh_timer.stop(); context.tasks.timer.stop()

if __name__ == "__main__": unittest.main()
