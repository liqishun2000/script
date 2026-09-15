from __future__ import annotations

import sys

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QFont
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDockWidget, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QProgressBar, QScrollArea,
    QStackedWidget, QStyle, QVBoxLayout, QWidget,
)

from .registry import builtins
from .services import AppContext
from .task_page import TaskPage
from .widgets import STATUS, icon_button


STYLE = """
QWidget { font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 13px; color: #292d33; }
QMainWindow, QWidget#workspace { background: #f5f6f8; }
QFrame#sidebar { background: #ffffff; border-right: 1px solid #e2e5ea; }
QLabel#brand { font-size: 17px; font-weight: 600; padding: 14px 0; }
QLabel#pageTitle { font-size: 21px; font-weight: 600; }
QLabel#category { color: #737b86; font-size: 12px; }
QLabel#notice { background: #eaf3fb; color: #235c84; padding: 10px; border-radius: 4px; }
QLabel#notice[error=true] { background: #fff0ee; color: #a7352d; }
QLabel#dependency { color: #a35d12; }
QLineEdit, QComboBox { background: white; border: 1px solid #d6dbe2; border-radius: 4px;
                     padding: 7px 9px; min-height: 18px; selection-background-color: #d8eafa; }
QLineEdit:focus, QComboBox:focus { border: 1px solid #287bbb; }
QPushButton { background: white; border: 1px solid #d6dbe2; border-radius: 4px; padding: 7px 12px; min-height: 18px; }
QPushButton:hover { background: #edf3fa; border-color: #93b7d5; }
QPushButton:pressed { background: #dceaf7; }
QPushButton[iconButton=true] { padding: 0; }
QPushButton[primary=true] { background: #246fa8; color: white; border-color: #246fa8; }
QPushButton[primary=true]:hover { background: #195d90; }
QPushButton:disabled { color: #9ca3ad; background: #f0f2f4; border-color: #e0e3e7; }
QListWidget#navigation { background: transparent; border: none; outline: none; }
QListWidget#navigation::item { padding: 10px 8px; border-radius: 4px; margin: 2px 0; }
QListWidget#navigation::item:selected { background: #e7f0fa; color: #15598c; }
QListWidget#navigation::item:hover { background: #f0f3f7; }
QTableWidget { background: white; alternate-background-color: #f9fafc; border: 1px solid #e0e4e9;
               selection-background-color: #e2eef9; selection-color: #202c38; border-radius: 4px; }
QHeaderView::section { background: #eef1f5; color: #606975; border: none; border-bottom: 1px solid #e0e4e9; padding: 9px; }
QPlainTextEdit { background: white; border: 1px solid #e0e4e9; border-radius: 4px; padding: 6px; }
QPlainTextEdit#log { background: #23272c; color: #e1e5e9; font-family: Consolas, 'Microsoft YaHei UI'; font-size: 12px; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: #f5f6f8; }
QSplitter::handle { background: #e0e4e9; }
QStatusBar { background: white; border-top: 1px solid #e0e4e9; }
QProgressBar { border: none; background: #e5e9ed; max-height: 5px; }
QProgressBar::chunk { background: #319679; }
QCheckBox { spacing: 7px; padding: 4px 0; }
QTabWidget::pane { border: none; }
QTabBar::tab { background: transparent; padding: 10px 14px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #15598c; border-bottom-color: #246fa8; }
QTabBar::tab:hover { background: #e7f0fa; }
QToolTip { background: #292d33; color: white; border: none; padding: 6px; }
"""


class MainWindow(QMainWindow):
    def __init__(self, context=None, registry=None):
        super().__init__()
        self.context = context or AppContext()
        self.registry = registry or builtins()
        self.pages = {}
        self.current_id = ""
        self.manual_compact = False
        self.task_overlay_previous = None
        self.closing_after_tasks = False
        self.setWindowTitle("Android 工具箱")
        self.setWindowIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        self.setStyleSheet(STYLE)
        central = QWidget()
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(206)
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(14, 12, 14, 14)
        self.brand = QLabel("Android 工具箱")
        self.brand.setObjectName("brand")
        side.addWidget(self.brand)
        self.collapse_button = icon_button("收起 / 展开导航", self.toggle_navigation,
                                           QStyle.StandardPixmap.SP_ArrowLeft)
        side.addWidget(self.collapse_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索工具")
        self.search.textChanged.connect(self.filter_navigation)
        side.addWidget(self.search)
        self.navigation = QListWidget()
        self.navigation.setObjectName("navigation")
        self.navigation.setIconSize(QSize(20, 20))
        self.navigation.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        side.addWidget(self.navigation, 1)
        self.utilities = QListWidget()
        self.utilities.setObjectName("navigation")
        self.utilities.setIconSize(QSize(20, 20))
        self.utilities.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.utilities.setFixedHeight(116)
        side.addWidget(self.utilities)
        self.nav_items = {}
        self.group_items = {}
        for spec in self.registry.entries.values():
            target = self.utilities if spec.category == "工作区" else self.navigation
            if target is self.navigation and spec.category not in self.group_items:
                heading = QListWidgetItem(spec.category)
                heading.setFlags(Qt.ItemFlag.NoItemFlags)
                heading.setForeground(QColor("#87919d"))
                heading.setSizeHint(QSize(150, 34))
                target.addItem(heading)
                self.group_items[spec.category] = heading
            item = QListWidgetItem(self.style().standardIcon(spec.icon), spec.title)
            item.setData(Qt.ItemDataRole.UserRole, spec.id)
            item.setToolTip(spec.category + " · " + spec.title)
            item.setSizeHint(QSize(150, 46))
            target.addItem(item)
            self.nav_items[spec.id] = item
        self.navigation.currentItemChanged.connect(self.navigate)
        self.utilities.currentItemChanged.connect(self.navigate)
        outer.addWidget(self.sidebar)
        content = QWidget()
        content.setObjectName("workspace")
        body = QVBoxLayout(content)
        body.setContentsMargins(22, 20, 22, 16)
        body.setSpacing(12)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        self.category = QLabel()
        self.category.setObjectName("category")
        self.title = QLabel()
        self.title.setObjectName("pageTitle")
        titles.addWidget(self.category)
        titles.addWidget(self.title)
        header.addLayout(titles)
        header.addStretch()
        body.addLayout(header)
        device_row = QHBoxLayout()
        device_row.addWidget(QLabel("目标设备"))
        self.device_picker = QComboBox()
        self.device_picker.setMinimumWidth(100)
        self.device_picker.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.device_picker.currentIndexChanged.connect(self.select_device)
        device_row.addWidget(self.device_picker, 1)
        device_row.addWidget(icon_button("刷新设备", self.context.devices.refresh, QStyle.StandardPixmap.SP_BrowserReload))
        body.addLayout(device_row)
        self.dependency = QLabel()
        self.dependency.setObjectName("dependency")
        self.dependency.setWordWrap(True)
        body.addWidget(self.dependency)
        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)
        outer.addWidget(content, 1)
        self.setCentralWidget(central)

        self.dock = QDockWidget("任务与日志", self)
        self.dock.setObjectName("taskDock")
        self.dock.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea)
        self.dock.setWidget(TaskPage(self.context, compact=True))
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.dock)
        self.dock.hide()
        self.progress = QProgressBar()
        self.progress.setFixedWidth(100)
        self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().addPermanentWidget(icon_button("展开 / 收起任务日志", self.toggle_dock,
                                                        QStyle.StandardPixmap.SP_FileDialogListView))
        self.context.devices.changed.connect(self.update_devices)
        self.context.tools.changed.connect(self.update_dependency)
        self.context.tasks.changed.connect(self.update_status)
        self.context.tasks.finished.connect(lambda _: self.context.devices.refresh())
        shortcut = QAction(self)
        shortcut.setShortcut("Ctrl+K")
        shortcut.triggered.connect(self.focus_search)
        self.addAction(shortcut)

        available = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1180, available.width() - 40), min(780, available.height() - 40))
        preferences = self.context.preferences
        geometry = preferences.get("window/geometry", None)
        if geometry:
            self.restoreGeometry(geometry)
        self.resize(min(self.width(), available.width()), min(self.height(), available.height()))
        self.move(max(available.left(), min(self.x(), available.right() - self.width())),
                  max(available.top(), min(self.y(), available.bottom() - self.height())))
        state = preferences.get("window/state", None)
        if state:
            self.restoreState(state)
        self.show_page(next(iter(self.registry.entries)))
        self.update_devices(self.context.devices.items, self.context.devices.error)
        self.update_status()
        self.context.devices.refresh()

    def focus_search(self):
        self.search.show()
        self.sidebar.setFixedWidth(206)
        self.search.setFocus()

    def filter_navigation(self, text):
        for key, item in self.nav_items.items():
            spec = self.registry.entries[key]
            item.setHidden(text.lower() not in (spec.title + spec.category + spec.id).lower())
        for category, item in self.group_items.items():
            item.setHidden(self.sidebar.width() < 100 or all(
                self.nav_items[key].isHidden() for key, spec in self.registry.entries.items()
                if spec.category == category))

    def navigate(self, item, previous=None):
        if not item:
            return
        self.show_page(item.data(Qt.ItemDataRole.UserRole))

    def show_page(self, key):
        spec = self.registry.entries[key]
        item = self.nav_items[key]
        for navigation in (self.navigation, self.utilities):
            navigation.blockSignals(True)
            navigation.setCurrentItem(item if item.listWidget() is navigation else None)
            navigation.blockSignals(False)
        if key not in self.pages:
            try:
                page = spec.create(self.context)
            except Exception as exc:
                page = QLabel("页面加载失败：" + str(exc))
                page.setWordWrap(True)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(page)
            self.stack.addWidget(scroll)
            self.pages[key] = (scroll, page)
        self.current_id = key
        self.stack.setCurrentWidget(self.pages[key][0])
        self.title.setText(spec.title)
        self.category.setText(spec.category)
        self.update_dependency()

    def update_dependency(self):
        if not self.current_id:
            return
        from .services import Tools
        try:
            Tools.require(self.context.tools.snapshot(), *self.registry.entries[self.current_id].dependencies)
            self.dependency.hide()
        except RuntimeError as exc:
            self.dependency.setText(str(exc))
            self.dependency.show()

    def update_devices(self, devices, error):
        selected = self.context.selected_serial
        self.device_picker.blockSignals(True)
        self.device_picker.clear()
        self.device_picker.addItem("选择设备" if devices else "未连接设备", "")
        for device in devices:
            text = f"{device.model or device.serial} · {device.serial} · {STATUS.get(device.state, device.state)}"
            self.device_picker.addItem(text, device.serial)
            index = self.device_picker.count() - 1
            self.device_picker.setItemData(index, text, Qt.ItemDataRole.ToolTipRole)
            if device.state != "device":
                self.device_picker.model().item(index).setEnabled(False)
        if selected and not any(d.serial == selected and d.state == "device" for d in devices):
            self.device_picker.addItem(selected + " · 已断开", selected)
            self.device_picker.model().item(self.device_picker.count() - 1).setEnabled(False)
        index = self.device_picker.findData(selected)
        if not selected and len([d for d in devices if d.state == "device"]) == 1:
            index = next(i + 1 for i, d in enumerate(devices) if d.state == "device")
        self.device_picker.setCurrentIndex(max(index, 0))
        self.device_picker.blockSignals(False)
        self.select_device()
        self.device_picker.setToolTip(error or self.device_picker.currentText())
        self.update_dependency()

    def select_device(self):
        self.context.selected_serial = self.device_picker.currentData() or ""

    def toggle_dock(self):
        # Short windows use the central task view to keep controls reachable.
        if self.height() < 650 and not self.dock.isVisible():
            if self.current_id == "tasks" and self.task_overlay_previous:
                self.show_page(self.task_overlay_previous)
                self.task_overlay_previous = None
            else:
                self.task_overlay_previous = self.current_id
                self.show_page("tasks")
            return
        original_size = self.size()
        self.dock.setVisible(not self.dock.isVisible())
        if self.dock.isVisible():
            self.resizeDocks([self.dock], [270], Qt.Orientation.Vertical)
            if not self.isMaximized():
                QTimer.singleShot(0, lambda: self.resize(original_size))

    def update_status(self):
        active = self.context.tasks.active
        count = sum(t.status == "queued" for t in self.context.tasks.tasks)
        self.statusBar().showMessage(f"{active.title} · {STATUS[active.status]} · 排队 {count}" if active else "就绪")
        self.progress.setVisible(active is not None)
        self.progress.setRange(0, 0 if active else 1)
        if self.closing_after_tasks and not active and not count:
            QTimer.singleShot(0, self.close)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, "sidebar"):
            return
        if not hasattr(self, "nav_items"):
            return
        self.apply_navigation_size()

    def toggle_navigation(self):
        self.manual_compact = self.sidebar.width() >= 100
        if not self.manual_compact:
            self.sidebar.setFixedWidth(206)
            self.brand.show()
            self.search.show()
            for key, item in self.nav_items.items():
                item.setText(self.registry.entries[key].title)
            for item in self.group_items.values():
                item.setHidden(False)
        else:
            self.apply_navigation_size()

    def apply_navigation_size(self):
        compact = self.width() < 950 or self.manual_compact
        self.sidebar.setFixedWidth(64 if compact else 206)
        self.brand.setVisible(not compact)
        self.search.setVisible(not compact)
        for key, item in self.nav_items.items():
            item.setText("" if compact else self.registry.entries[key].title)
        for item in self.group_items.values():
            item.setHidden(compact)
        self.collapse_button.setIcon(self.style().standardIcon(
            QStyle.StandardPixmap.SP_ArrowRight if compact else QStyle.StandardPixmap.SP_ArrowLeft))
        self.filter_navigation(self.search.text())

    def closeEvent(self, event):
        tasks = self.context.tasks
        pending = tasks.active or any(t.status == "queued" for t in tasks.tasks)
        if pending and not self.closing_after_tasks:
            dialog = QMessageBox(self)
            dialog.setWindowTitle("任务尚未结束")
            dialog.setText("关闭窗口时如何处理当前任务？")
            wait = dialog.addButton("完成任务后退出", QMessageBox.ButtonRole.AcceptRole)
            stop = dialog.addButton("停止后续步骤并退出", QMessageBox.ButtonRole.DestructiveRole)
            dialog.addButton("返回", QMessageBox.ButtonRole.RejectRole)
            dialog.exec()
            if dialog.clickedButton() in (wait, stop):
                self.closing_after_tasks = True
                tasks.accepting = False
                if dialog.clickedButton() == stop:
                    for task in list(tasks.tasks):
                        tasks.cancel(task)
            event.ignore()
            self.update_status()
            return
        if pending:
            event.ignore()
            return
        self.context.preferences.set("window/geometry", self.saveGeometry())
        self.context.preferences.set("window/state", self.saveState())
        tasks.save()
        self.context.sessions.close()
        self.context.devices.refresh_timer.stop()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("AndroidToolbox")
    app.setOrganizationName("AndroidToolbox")
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    return app.exec()
