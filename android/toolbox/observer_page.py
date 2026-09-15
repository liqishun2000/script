from collections import deque
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QHBoxLayout, QHeaderView, QLabel, QPlainTextEdit, QStyle, QTabWidget,
)

from .widgets import Page, icon_button, set_rows, table


class ObserverPage(Page):
    kind = "details"

    def __init__(self, context):
        super().__init__(context)
        self.serial = ""
        self.snapshot = None
        self.history = deque(maxlen=100)
        self.last_identity = None
        bar = QHBoxLayout()
        self.state = QLabel("未选择设备")
        self.state.setWordWrap(True)
        self.state.setTextFormat(Qt.TextFormat.PlainText)
        bar.addWidget(self.state, 1)
        self.auto = QCheckBox("自动刷新")
        self.auto.setChecked(True)
        self.auto.toggled.connect(self.subscribe)
        bar.addWidget(self.auto)
        bar.addWidget(icon_button("立即刷新", self.refresh, QStyle.StandardPixmap.SP_BrowserReload))
        self.copy = icon_button("复制当前信息", self.copy_snapshot, QStyle.StandardPixmap.SP_FileDialogContentsView)
        self.copy.setEnabled(False)
        bar.addWidget(self.copy)
        self.layout.addLayout(bar)
        self.tabs = QTabWidget()
        self.values = table(["项目", "值"])
        self.values.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.values.setColumnWidth(0, 140)
        self.values.setWordWrap(True)
        self.tabs.addTab(self.values, "概览")
        self.raw = QPlainTextEdit()
        self.raw.setReadOnly(True)
        self.raw.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.tabs.addTab(self.raw, "原始输出")
        self.changes = table(["时间", "包名 / Activity", "焦点 Window"])
        if self.kind == "foreground":
            self.tabs.addTab(self.changes, "切换记录")
        self.tabs.setMinimumHeight(300)
        self.layout.addWidget(self.tabs, 1)
        context.selection_changed.connect(self.select)
        context.devices.changed.connect(self.devices_changed)
        context.sessions.updated.connect(self.receive)
        context.sessions.failed.connect(self.failed)

    def showEvent(self, event):
        super().showEvent(event)
        self.select(self.context.selected_serial)

    def hideEvent(self, event):
        self.context.sessions.unsubscribe(self)
        super().hideEvent(event)

    def select(self, serial):
        if serial != self.serial:
            self.serial = serial
            self.clear()
            self.history.clear()
            self.last_identity = None
            set_rows(self.changes, [])
        self.subscribe()

    def clear(self):
        self.snapshot = None
        self.copy.setEnabled(False)
        self.raw.clear()
        set_rows(self.values, [])
        self.state.setText("等待刷新" if self.serial else "未选择设备")

    def subscribe(self):
        self.context.sessions.unsubscribe(self)
        if self.isVisible() and self.serial and self.auto.isChecked():
            self.context.sessions.subscribe(self, self.serial, self.kind)

    def refresh(self):
        if self.serial:
            self.context.sessions.subscribe(self, self.serial, self.kind)
            self.context.sessions.refresh(self.serial, self.kind)
            self.state.setText("正在读取 · " + self.serial)

    def devices_changed(self, devices, error):
        if self.serial and not any(d.serial == self.serial and d.state == "device" for d in devices):
            self.failed(self.serial, self.kind, error or "设备已断开或尚未授权")

    def failed(self, serial, kind, message):
        if serial != self.serial or kind != self.kind or not self.isVisible():
            return
        self.clear()
        self.state.setText(message or "读取已取消")
        if not self.auto.isChecked():
            self.context.sessions.unsubscribe(self)

    def receive(self, snapshot):
        if snapshot.serial != self.serial or snapshot.kind != self.kind or not self.isVisible():
            return
        self.snapshot = snapshot
        self.copy.setEnabled(True)
        stamp = datetime.fromtimestamp(snapshot.timestamp).strftime("%H:%M:%S")
        self.state.setText(f"{self.serial} · 更新于 {stamp}")
        set_rows(self.values, [("设备序列号", self.serial), *snapshot.rows])
        self.values.resizeRowsToContents()
        self.raw.setPlainText(snapshot.raw)
        if self.kind == "foreground":
            values = dict(snapshot.rows)
            identity = (values.get("Activity"), values.get("焦点 Window"))
            if identity != self.last_identity:
                self.history.appendleft((stamp, *identity))
                self.last_identity = identity
                set_rows(self.changes, self.history)
        if not self.auto.isChecked():
            self.context.sessions.unsubscribe(self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.values.resizeRowsToContents()

    def copy_snapshot(self):
        if self.snapshot:
            QApplication.clipboard().setText("设备序列号: " + self.serial + "\n" + "\n".join(
                f"{key}: {value}" for key, value in self.snapshot.rows))


class DeviceInfoPage(ObserverPage):
    kind = "details"


class ForegroundPage(ObserverPage):
    kind = "foreground"
