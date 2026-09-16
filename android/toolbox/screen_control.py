from __future__ import annotations

import os
import ctypes
from ctypes import wintypes
import re
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QProcess, QProcessEnvironment, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QImage, QKeySequence, QWindow
from PySide6.QtWidgets import (
    QComboBox, QDockWidget, QHBoxLayout, QLabel, QMainWindow, QPlainTextEdit,
    QStyle, QToolBar, QVBoxLayout, QWidget,
)

from .native_window import fit_window, focus_window, owned_window, request_close
from .widgets import icon_button


QUALITY = (("流畅 · 720 / 30 FPS", 720, 30, "4M"),
           ("均衡 · 1080 / 30 FPS", 1080, 30, "8M"),
           ("清晰 · 1920 / 60 FPS", 1920, 60, "12M"))
KEYS = (("返回", 4, QStyle.StandardPixmap.SP_ArrowBack),
        ("主页", 3, QStyle.StandardPixmap.SP_DirHomeIcon),
        ("最近任务", 187, QStyle.StandardPixmap.SP_TitleBarNormalButton),
        ("电源", 26, QStyle.StandardPixmap.SP_DialogCloseButton),
        ("音量增加", 24, QStyle.StandardPixmap.SP_MediaVolume),
        ("音量减少", 25, QStyle.StandardPixmap.SP_MediaVolumeMuted))


def scrcpy_arguments(serial, quality):
    _, size, fps, bitrate = QUALITY[quality]
    return ["--serial", serial, "--window-title", "AndroidToolbox-" + serial,
            "--video-codec=h264", "--render-driver=software", f"--max-size={size}", f"--max-fps={fps}",
            f"--video-bit-rate={bitrate}", "--no-audio", "--window-borderless",
            "--no-window-aspect-ratio-lock", "--window-x=-16000", "--window-width=480",
            "--window-height=640", "--no-terminal-title"]


class ScreenManager(QObject):
    changed = Signal()

    def __init__(self, context):
        super().__init__(context)
        self.context = context
        self.windows = {}

    def open(self, serial, quality=1):
        if os.name != "nt":
            raise RuntimeError("屏幕控制当前支持 Windows 10/11。")
        if serial in self.windows:
            window = self.windows[serial]
            if window.isMinimized():
                window.showNormal()
            window.raise_()
            window.activateWindow()
            return window
        if not any(d.serial == serial and d.state == "device" for d in self.context.devices.items):
            raise RuntimeError("设备已断开或尚未授权。")
        tools = self.context.tools.snapshot()
        self.context.tools.require(tools, "adb", "scrcpy")
        window = ScreenWindow(self, serial, tools, quality)
        self.windows[serial] = window
        window.show()
        window.start()
        self.changed.emit()
        return window

    def close(self):
        for window in list(self.windows.values()):
            window.close()


class ScreenWindow(QMainWindow):
    def __init__(self, manager, serial, tools, quality):
        super().__init__()
        from .app import STYLE
        self.setStyleSheet(STYLE)
        self.manager = manager
        self.context = manager.context
        self.serial = serial
        self.tools = dict(tools)
        self.process = None
        self.command = None
        self.hwnd = 0
        self.foreign = None
        self.container = None
        self.stopping = False
        self.closed = False
        self.retry_on_connect = False
        self.video_ready = False
        self.log_tail = ""
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("屏幕控制 · " + serial)
        self.setWindowIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        available = self.screen().availableGeometry()
        self.resize(min(620, available.width() - 40), min(820, available.height() - 40))
        self.setMinimumSize(380, 360)
        toolbar = QToolBar()
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        self.quality = QComboBox()
        self.quality.addItems([q[0] for q in QUALITY])
        self.quality.setCurrentIndex(quality)
        self.quality.setToolTip("最大边长 / 帧率上限；更改后重新连接")
        toolbar.addWidget(self.quality)
        toolbar.addSeparator()
        self.reconnect = icon_button("重新连接", self.restart, QStyle.StandardPixmap.SP_BrowserReload)
        toolbar.addWidget(self.reconnect)
        toolbar.addWidget(icon_button("全屏 / 退出全屏", self.toggle_fullscreen, QStyle.StandardPixmap.SP_TitleBarMaxButton))
        toolbar.addWidget(icon_button("显示 / 隐藏日志", self.toggle_logs, QStyle.StandardPixmap.SP_FileDialogListView))
        self.quality.currentIndexChanged.connect(self.restart)

        central = QWidget()
        row = QHBoxLayout(central)
        row.setContentsMargins(8, 8, 8, 8)
        controls = QVBoxLayout()
        self.keys = []
        for title, key, icon in KEYS:
            control = icon_button(title, lambda checked=False, key=key: self.key(key), icon)
            control.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            controls.addWidget(control)
            self.keys.append(control)
        controls.addSpacing(12)
        self.screenshot_button = icon_button("保存截图", self.screenshot, QStyle.StandardPixmap.SP_DialogSaveButton)
        controls.addWidget(self.screenshot_button)
        controls.addStretch()
        row.addLayout(controls)
        self.video = QWidget()
        self.video.setStyleSheet("background: #222222;")
        self.video_layout = QVBoxLayout(self.video)
        self.video_layout.setContentsMargins(0, 0, 0, 0)
        self.placeholder = QLabel("正在连接设备")
        self.placeholder.setWordWrap(True)
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setStyleSheet("color: #d6dbe2; padding: 20px;")
        self.video_layout.addWidget(self.placeholder)
        row.addWidget(self.video, 1)
        self.setCentralWidget(central)
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMaximumBlockCount(1000)
        self.logs.setObjectName("log")
        self.dock = QDockWidget("投屏日志", self)
        self.dock.setWidget(self.logs)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.dock)
        self.dock.hide()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.attach)
        self.fit_timer = QTimer(self)
        self.fit_timer.timeout.connect(self.fit_video)
        self.context.devices.changed.connect(self.devices_changed)
        action = QAction(self)
        action.setShortcut(QKeySequence("Esc"))
        action.triggered.connect(lambda: self.showNormal() if self.isFullScreen() else None)
        self.addAction(action)
        self.set_ready(False)

    def set_ready(self, ready):
        for control in [*self.keys, self.screenshot_button]:
            control.setEnabled(ready)

    def start(self):
        if self.closed or (self.process and self.process.state() != QProcess.ProcessState.NotRunning):
            return
        self.retry_on_connect = False
        self.video_ready = False
        self.log_tail = ""
        self.placeholder.setText("正在连接设备")
        self.placeholder.show()
        self.statusBar().showMessage("连接中 · " + self.serial)
        process = QProcess(self)
        self.process = process
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("ADB", self.tools["adb"])
        process.setProcessEnvironment(environment)
        process.setWorkingDirectory(str(Path(self.tools["scrcpy"]).parent))
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(lambda: self.read_logs(process))
        process.finished.connect(lambda code, status: self.finished(process, code))
        process.errorOccurred.connect(lambda error: self.process_error(process, error))
        process.start(self.tools["scrcpy"], scrcpy_arguments(self.serial, self.quality.currentIndex()))
        self.deadline = time.monotonic() + 20
        self.timer.start(100)

    def read_logs(self, process):
        text = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace").rstrip()
        if text:
            self.logs.appendPlainText(text)
            self.log_tail = (self.log_tail + text)[-512:]
            if process is self.process and "Texture:" in self.log_tail:
                self.video_ready = True

    def process_error(self, process, error):
        if process is self.process and error == QProcess.ProcessError.FailedToStart:
            self.timer.stop()
            self.placeholder.setText("无法启动投屏；请检查 scrcpy 路径")
            self.logs.appendPlainText(process.errorString())
            self.statusBar().showMessage("启动失败")
            self.set_ready(False)

    def attach(self):
        if not self.process or self.closed:
            return
        handle = owned_window(self.process.processId()) if self.video_ready else 0
        if handle:
            self.timer.stop()
            self.hwnd = handle
            self.foreign = QWindow.fromWinId(handle)
            if self.foreign is None:
                self.stop()
                self.placeholder.setText("无法嵌入投屏窗口")
                return
            self.container = QWidget.createWindowContainer(self.foreign, self.video)
            self.container.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.video_layout.addWidget(self.container)
            self.placeholder.hide()
            self.container.show()
            self.container.setFocus()
            focus_window(self.hwnd)
            self.fit_timer.start(100)
            self.set_ready(True)
            self.statusBar().showMessage("已连接 · " + self.serial)
        elif time.monotonic() >= self.deadline:
            self.stop()
            self.placeholder.setText("连接超时；可重新连接或查看日志")
            self.statusBar().showMessage("连接超时")

    def release_video(self):
        self.fit_timer.stop()
        if self.container:
            self.container.hide()
            self.video_layout.removeWidget(self.container)
            self.container.deleteLater()
        self.container = None
        self.foreign = None
        self.hwnd = 0
        self.placeholder.show()
        self.set_ready(False)

    def fit_video(self):
        if self.hwnd and self.container:
            # scrcpy may resize itself when the display rotates; keep it inside the Qt viewport.
            ratio = self.container.devicePixelRatioF()
            origin = self.container.mapTo(self, QPoint(0, 0))
            fit_window(self.hwnd, int(self.winId()), round(origin.x() * ratio), round(origin.y() * ratio),
                       round(self.container.width() * ratio), round(self.container.height() * ratio))

    def finished(self, process, code):
        self.read_logs(process)
        if process is not self.process:
            return
        self.timer.stop()
        self.cancel_command()
        self.release_video()
        if not self.stopping:
            self.placeholder.setText("投屏已结束；可重新连接或查看日志")
            self.statusBar().showMessage(f"投屏已结束 · 退出码 {code}")

    def stop(self):
        self.stopping = True
        self.timer.stop()
        self.cancel_command()
        process = self.process
        if process and process.state() != QProcess.ProcessState.NotRunning:
            request_close(self.hwnd or owned_window(process.processId()))
            if not process.waitForFinished(1200):
                process.kill()
                process.waitForFinished(1200)
        self.release_video()
        if process:
            process.deleteLater()
        self.process = None
        self.stopping = False

    def restart(self):
        self.stop()
        if any(d.serial == self.serial and d.state == "device" for d in self.context.devices.items):
            self.start()
        else:
            self.retry_on_connect = True
            self.placeholder.setText("设备已断开；等待重新连接")

    def devices_changed(self, devices, error):
        if self.closed:
            return
        online = any(d.serial == self.serial and d.state == "device" for d in devices)
        if not online:
            self.stop()
            self.retry_on_connect = True
            self.placeholder.setText("设备已断开或尚未授权")
            self.statusBar().showMessage("等待设备 · " + self.serial)
        elif self.retry_on_connect:
            self.start()

    def run_command(self, args, callback=None):
        if not self.hwnd or self.closed:
            return
        if self.command:
            self.statusBar().showMessage("正在执行上一条设备操作")
            return
        process = QProcess(self)
        self.command = process
        self.set_ready(False)
        timeout = QTimer(process)
        timeout.setSingleShot(True)

        def done(code=1, status=None):
            if self.command is not process:
                return
            timeout.stop()
            output = bytes(process.readAllStandardOutput())
            error = bytes(process.readAllStandardError()).decode("utf-8", errors="replace").strip()
            self.command = None
            if not self.closed:
                self.set_ready(bool(self.hwnd))
                if code:
                    self.statusBar().showMessage("操作失败：" + (error or process.errorString()))
                elif callback:
                    callback(output)
                else:
                    self.statusBar().showMessage("已连接 · " + self.serial)
            process.deleteLater()

        process.finished.connect(done)
        process.errorOccurred.connect(lambda error: done() if error == QProcess.ProcessError.FailedToStart else None)
        timeout.timeout.connect(process.kill)
        process.start(self.tools["adb"], ["-s", self.serial, *args])
        timeout.start(8000)

    def cancel_command(self):
        process = self.command
        self.command = None
        if process:
            process.kill()
            process.waitForFinished(1000)
            process.deleteLater()

    def key(self, code):
        if code in {entry[1] for entry in KEYS}:
            self.run_command(["shell", "input", "keyevent", str(code)])

    def screenshot(self):
        def save(output):
            image = QImage.fromData(output, "PNG")
            if image.isNull():
                self.statusBar().showMessage("截图失败：未收到有效图像")
                return
            folder = self.context.preferences.output / "screenshots"
            try:
                folder.mkdir(parents=True, exist_ok=True)
                serial = re.sub(r"[^A-Za-z0-9_.-]", "_", self.serial)
                path = folder / f"{serial}-{datetime.now():%Y%m%d-%H%M%S-%f}.png"
                if not image.save(str(path), "PNG"):
                    raise OSError("无法写入截图")
                self.statusBar().showMessage("截图已保存：" + str(path))
                self.logs.appendPlainText("截图已保存：" + str(path))
            except OSError as exc:
                self.statusBar().showMessage(str(exc))
        self.run_command(["exec-out", "screencap", "-p"], save)

    def toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def nativeEvent(self, event_type, message):
        if os.name == "nt":
            msg = wintypes.MSG.from_address(int(message))
            # Windows activates the Qt ancestor of a foreign child on click. Restore SDL focus
            # after that activation, so native keyboard/clipboard events reach the owned child.
            if msg.message == 0x0210 and msg.wParam & 0xffff == 0x0201:
                QTimer.singleShot(0, lambda: focus_window(self.hwnd))
        return super().nativeEvent(event_type, message)

    def toggle_logs(self):
        self.dock.setVisible(not self.dock.isVisible())

    def closeEvent(self, event):
        self.closed = True
        self.context.devices.changed.disconnect(self.devices_changed)
        self.stop()
        self.manager.windows.pop(self.serial, None)
        self.manager.changed.emit()
        event.accept()
