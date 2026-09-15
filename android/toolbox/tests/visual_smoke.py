"""Capture native Qt layouts without touching attached devices."""

import argparse
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton

from android.toolbox.app import MainWindow
from android.toolbox.services import AppContext, Device, Devices, Outcome, Task
from android.toolbox.device_observer import Observation, parse_details, parse_foreground


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(Path(tempfile.gettempdir()) / "toolbox-visual"))
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setStyle("Fusion")
    scale = os.environ.get("QT_SCALE_FACTOR", "1")
    with tempfile.TemporaryDirectory() as folder, patch.object(Devices, "refresh"):
        context = AppContext(Path(folder) / "preferences")
        context.devices.items = [Device("R5CN90J7ASY", "device", "Galaxy S23"),
                                 Device("emulator-5554", "device", "Pixel 8"),
                                 Device("emulator-5556", "offline", "Pixel Tablet")]
        window = MainWindow(context)
        window.resize(1180, 780)
        window.show()
        page = window.pages["install"][1]
        for name in ("Cleaner_v1.0.xapk", "FileManager.apk"):
            path = Path(folder) / name
            path.touch()
            page.add_files([str(path)])
        first = str(page.paths[0])
        page.results[first] = {"status": "success", "detail": "安装完成"}
        page.render()
        task = Task("安装 2 个包", "install", None, "R5CN90J7ASY")
        task.status = "partial"
        task.outcome = Outcome("partial", [
            {"name": first, "status": "success", "detail": "安装完成"},
            {"name": "FileManager.apk", "status": "failed", "detail": "设备在传输过程中断开"},
        ])
        task.logs.extend(["17:30:00  开始安装 Cleaner_v1.0.xapk", "17:30:04  Success",
                          "17:30:04  开始安装 FileManager.apk", "17:30:06  设备在传输过程中断开"])
        context.tasks.tasks.append(task)
        context.tasks.changed.emit()
        for width, height, label in ((1180, 780, "desktop"), (800, 600, "small")):
            window.resize(width, height)
            for key in window.registry.entries:
                window.show_page(key)
                app.processEvents()
                scroll, widget = window.pages[key]
                if key in {"device_info", "foreground"}:
                    context.selected_serial = "R5CN90J7ASY"
                    window.update_devices(context.devices.items, "")
                    widget.auto.setChecked(False)
                    raw = {"属性": "[ro.product.manufacturer]: [samsung]\n[ro.product.model]: [Galaxy S23]",
                           "Activity": "mResumedActivity: ActivityRecord{x u0 com.example.cleaner/com.google.android.gms.ads.AdActivity}",
                           "Window": "mCurrentFocus=Window{x u0 com.example.cleaner/com.google.android.gms.ads.AdActivity}"}
                    rows = parse_details(raw) if key == "device_info" else parse_foreground(raw)
                    widget.receive(Observation(context.selected_serial, widget.kind, time.time(), tuple(rows), str(raw)))
                    app.processEvents()
                assert widget.width() <= scroll.viewport().width(), (key, "horizontal overflow")
                # The scroll area must make the last action reachable even on short displays.
                buttons = widget.findChildren(QPushButton)
                for control in buttons:
                    scroll.ensureWidgetVisible(control)
                    app.processEvents()
                    assert not control.visibleRegion().isEmpty(), (key, control.text(), "unreachable")
                scroll.verticalScrollBar().setValue(0)
                app.processEvents()
                window.grab().save(str(output / f"{scale}-{label}-{key}.png"))
            window.show_page("install")
            window.toggle_dock()
            app.processEvents()
            window.grab().save(str(output / f"{scale}-{label}-dock.png"))
            assert window.width() <= width and window.height() <= height, (
                "Dock forces window beyond requested size", width, height, window.width(), window.height(),
                window.minimumSizeHint().width(), window.minimumSizeHint().height())
            window.dock.hide()
            app.processEvents()
        window.close()
        context.devices.timer.stop()
        context.devices.refresh_timer.stop()
        context.tasks.timer.stop()
    print(f"PASS Qt scale {scale}: desktop, small, all pages, dock. Screenshots: {output}")


if __name__ == "__main__":
    main()
