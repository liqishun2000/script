from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPushButton, QSizePolicy, QStyle, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)


STATUS = {"queued": "排队中", "running": "执行中", "stopping": "正在停止后续步骤",
          "success": "完成", "failed": "失败", "partial": "部分完成 / 需复核",
          "cancelled": "已取消", "interrupted": "已中断", "device": "已连接",
          "offline": "离线", "unauthorized": "待授权"}


def button(text, callback, icon=None, primary=False):
    widget = QPushButton(text)
    if icon is not None:
        widget.setIcon(widget.style().standardIcon(icon))
    widget.setProperty("primary", primary)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.clicked.connect(callback)
    return widget


def icon_button(tooltip, callback, icon):
    widget = button("", callback, icon)
    widget.setToolTip(tooltip)
    widget.setAccessibleName(tooltip)
    widget.setProperty("iconButton", True)
    widget.setFixedSize(34, 34)
    return widget


class ResultTable(QTableWidget):
    def __init__(self, columns):
        super().__init__(0, columns)
        self.empty = QLabel("暂无记录", self.viewport())
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setStyleSheet("color: #87919d; font-size: 14px; background: transparent;")
        self.empty.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def setRowCount(self, count):
        super().setRowCount(count)
        self.empty.setVisible(count == 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.empty.setGeometry(self.viewport().rect())


def table(headers):
    widget = ResultTable(len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    widget.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    widget.verticalHeader().hide()
    widget.verticalHeader().setDefaultSectionSize(38)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setAlternatingRowColors(True)
    widget.setShowGrid(False)
    widget.setWordWrap(False)
    widget.setMinimumHeight(130)
    return widget


def set_rows(widget, rows):
    widget.setRowCount(len(rows))
    for row, values in enumerate(rows):
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setToolTip(str(value))
            if str(value) in {"完成", "可用", "已连接", "支持"}:
                item.setForeground(QColor("#247a61"))
            elif str(value) in {"失败", "缺失 / 无效", "离线"}:
                item.setForeground(QColor("#b04238"))
            elif str(value) in {"执行中", "排队中"}:
                item.setForeground(QColor("#246fa8"))
            elif str(value) in {"部分完成 / 需复核", "待授权"}:
                item.setForeground(QColor("#956619"))
            widget.setItem(row, column, item)


def open_path(path):
    if path and Path(path).exists():
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).resolve())))


class FileField(QWidget):
    changed = Signal(str)

    def __init__(self, value="", directory=False, file_filter="所有文件 (*)"):
        super().__init__()
        self.directory = directory
        self.file_filter = file_filter
        self.setAcceptDrops(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit(value)
        self.edit.setAcceptDrops(False)
        self.edit.setMinimumWidth(80)
        self.edit.textChanged.connect(self.changed)
        self.edit.textChanged.connect(self.edit.setToolTip)
        self.edit.setToolTip(value)
        self.browse_button = icon_button("选择目录" if directory else "选择文件", self.browse,
                                         QStyle.StandardPixmap.SP_DirOpenIcon)
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.browse_button)

    def text(self):
        return self.edit.text().strip()

    def browse(self):
        if self.directory:
            path = QFileDialog.getExistingDirectory(self, "选择目录", self.text())
        else:
            path, _ = QFileDialog.getOpenFileName(self, "选择文件", self.text(), self.file_filter)
        if path:
            self.edit.setText(path)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.edit.setText(paths[0])
            event.acceptProposedAction()


class Page(QWidget):
    def __init__(self, context):
        super().__init__()
        self.context = context
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(14)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        self.notice.setObjectName("notice")
        self.notice.hide()
        self.layout.addWidget(self.notice)

    def guard(self, operation):
        self.notice.hide()
        try:
            return operation()
        except Exception as exc:
            self.notify(str(exc), True)

    def notify(self, message, error=False):
        self.notice.setText(message[:500])
        self.notice.setToolTip(message)
        self.notice.setProperty("error", error)
        self.notice.style().unpolish(self.notice)
        self.notice.style().polish(self.notice)
        self.notice.show()


def form():
    widget = QWidget()
    layout = QFormLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)
    layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    return widget, layout
