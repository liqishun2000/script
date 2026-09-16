"""Opt-in Windows/ADB smoke check; opens the device's recent apps and Home."""
import argparse
import ctypes
import os
import re
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from ctypes import wintypes

from PySide6.QtCore import QMimeData, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from android.toolbox.services import AppContext, Device


def wait_until(predicate, timeout=25):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("Timed out")
        QTest.qWait(50)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", required=True)
    parser.add_argument("--settings-input", action="store_true")
    args = parser.parse_args()
    app = QApplication([])
    app.setStyle("Fusion")
    output = Path(tempfile.gettempdir()) / "toolbox-screen-visual"
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        context = AppContext(Path(folder))
        context.devices.refresh_timer.stop()
        context.devices.items = [Device(args.serial, "device")]
        window = context.screens.open(args.serial)

        def capture(name):
            screen = window.screen()
            pixmap = screen.grabWindow(0)
            ratio = pixmap.devicePixelRatio()
            origin = window.mapToGlobal(window.rect().topLeft()) - screen.geometry().topLeft()
            captured = pixmap.copy(int(origin.x() * ratio), int(origin.y() * ratio),
                                   int(window.width() * ratio), int(window.height() * ratio))
            captured.save(str(output / (os.environ.get("QT_SCALE_FACTOR", "1") + "-" + name)))
            image = captured.toImage()
            colors = {image.pixel(x, y) for x in range(image.width() // 3, image.width() * 2 // 3, 4)
                      for y in range(image.height() // 4, image.height() * 3 // 4, 4)}
            assert len(colors) > 20, (name, "blank video", len(colors))
            native = wintypes.RECT()
            native_api = ctypes.WinDLL("user32")
            native_api.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
            native_api.GetWindowRect(window.hwnd, ctypes.byref(native))
            viewport = window.container.mapToGlobal(QPoint(0, 0))
            expected = (viewport.x() * ratio, viewport.y() * ratio,
                        window.container.width() * ratio, window.container.height() * ratio)
            actual = (native.left, native.top, native.right - native.left, native.bottom - native.top)
            assert all(abs(a - b) <= 2 for a, b in zip(actual, expected)), (name, "video escapes viewport", actual, expected)
            return captured.toImage()

        try:
            wait_until(lambda: window.hwnd or not window.timer.isActive())
            assert window.hwnd, window.logs.toPlainText()
            window.move(20, 20)
            window.raise_()
            window.activateWindow()
            user32 = ctypes.WinDLL("user32")
            user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                          ctypes.c_int, ctypes.c_int, wintypes.UINT]
            user32.SetWindowPos(int(window.winId()), -1, 0, 0, 0, 0, 0x0043)
            QTest.qWait(1500)
            assert window.hwnd, window.logs.toPlainText()
            before = capture("desktop.png")
            assert context.screens.open(args.serial) is window
            window.key(187)
            wait_until(lambda: window.command is None)
            QTest.qWait(1500)
            after = capture("recents.png")
            assert before != after, "video did not change after opening recent apps"
            window.key(3)
            wait_until(lambda: window.command is None)
            window.resize(420, min(540, window.screen().availableGeometry().height() - 60))
            window.move(20, 20)
            QTest.qWait(2000)
            small = capture("small.png")
            # Native SDL receives real mouse input; Qt's synthetic widget events do not reach it.
            user32.SetForegroundWindow.argtypes = [wintypes.HWND]
            user32.SetForegroundWindow(int(window.winId()))
            origin = window.container.mapToGlobal(QPoint(0, 0))
            ratio = window.devicePixelRatioF()
            x = int((origin.x() + window.container.width() / 2) * ratio)
            y = int((origin.y() + 8) * ratio)
            user32.SetCursorPos(x, y)
            user32.mouse_event(0x0002, 0, 0, 0, 0)
            for step in range(1, 11):
                user32.SetCursorPos(x, y + int(window.container.height() * ratio * step / 20))
                QTest.qWait(20)
            user32.mouse_event(0x0004, 0, 0, 0, 0)
            QTest.qWait(700)
            assert small != capture("mouse-swipe.png"), "native mouse swipe did not change the frame"
            window.key(4)
            wait_until(lambda: window.command is None)
            if args.settings_input:
                verify_settings_input(window, user32, capture)
            for key, flags in ((0x12, 0), (0x27, 1), (0x27, 3), (0x12, 2)):
                user32.keybd_event(key, user32.MapVirtualKeyW(key, 0), flags, 0)
                QTest.qWait(60)
            QTest.qWait(1200)
            capture("rotated.png")
            window.toggle_fullscreen()
            QTest.qWait(1000)
            capture("fullscreen.png")
            window.toggle_fullscreen()
            QTest.qWait(500)
            window.screenshot()
            wait_until(lambda: window.command is None)
            assert list((context.preferences.output / "screenshots").glob("*.png"))
            window.restart()
            wait_until(lambda: window.hwnd or not window.timer.isActive())
            assert window.hwnd, window.logs.toPlainText()
            print(window.logs.toPlainText())
        finally:
            context.screens.close()
            context.sessions.close()
            context.devices.timer.stop()
            context.tasks.timer.stop()
            app.processEvents()
        assert not context.screens.windows
    print("PASS screen open, owned embedding, keys, screenshot, resize, restart, close:", output)


def verify_settings_input(window, user32, capture):
    """Optional foreground UI automation; finds Settings search by accessibility labels."""
    temporary = f"/data/local/tmp/toolbox-input-{os.getpid()}.xml"

    def adb(*args):
        return subprocess.check_output([window.tools["adb"], "-s", window.serial, *args],
                                       timeout=15, creationflags=subprocess.CREATE_NO_WINDOW).decode("utf-8")

    def nodes():
        adb("shell", "uiautomator", "dump", temporary)
        return list(ET.fromstring(adb("shell", "cat", temporary)).iter("node"))

    def click_node(node):
        points = [int(v) for v in re.findall(r"\d+", node.get("bounds"))]
        sizes = re.findall(r"(\d+)x(\d+)", adb("shell", "wm", "size"))
        width, height = map(int, sizes[-1])
        rect = wintypes.RECT()
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.GetWindowRect(window.hwnd, ctypes.byref(rect))
        cw, ch = rect.right - rect.left, rect.bottom - rect.top
        factor = min(cw / width, ch / height)
        x = rect.left + (cw - width * factor) / 2 + (points[0] + points[2]) / 2 * factor
        y = rect.top + (ch - height * factor) / 2 + (points[1] + points[3]) / 2 * factor
        user32.SetCursorPos(int(x), int(y))
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        QTest.qWait(80)
        user32.mouse_event(0x0004, 0, 0, 0, 0)
        QTest.qWait(1000)

    clipboard = QApplication.clipboard()
    saved = QMimeData()
    for fmt in clipboard.mimeData().formats():
        saved.setData(fmt, clipboard.mimeData().data(fmt))
    try:
        adb("shell", "am", "start", "-a", "android.settings.SETTINGS")
        QTest.qWait(1500)
        search = next(n for n in nodes() if n.get("content-desc", "").lower() in
                      {"搜索", "搜索设置", "search", "search settings"})
        click_node(search)
        capture("settings-after-click.png")
        clipboard.setText("工具箱测试abc")
        QTest.qWait(300)
        class GUIINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                        *[(name, wintypes.HWND) for name in ("active", "focus", "capture", "menu", "move", "caret")],
                        ("rect", wintypes.RECT)]
        info = GUIINFO()
        info.cbSize = ctypes.sizeof(info)
        user32.GetGUIThreadInfo(0, ctypes.byref(info))
        assert info.focus == window.hwnd, "keyboard focus did not reach the embedded SDL window"
        for key, flag in ((0x11, 0), (0x56, 0), (0x56, 2), (0x11, 2)):
            user32.keybd_event(key, user32.MapVirtualKeyW(key, 0), flag, 0)
            QTest.qWait(60)
        QTest.qWait(1000)
        capture("unicode-input.png")
        assert any(n.get("text") == "工具箱测试abc" for n in nodes()), "Unicode clipboard paste failed"
        print("PASS native mouse click, keyboard Ctrl+V and Unicode input")
    finally:
        clipboard.setMimeData(saved)
        adb("shell", "rm", temporary)
        window.key(3)
        wait_until(lambda: window.command is None)


if __name__ == "__main__":
    main()
