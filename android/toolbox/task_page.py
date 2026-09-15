from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QSplitter, QStyle, QWidget, QVBoxLayout,
)

from .widgets import Page, STATUS, button, icon_button, open_path, table, set_rows


class TaskPage(Page):
    def __init__(self, context, compact=False):
        super().__init__(context)
        self.compact = compact
        self.selected_id = None
        self.signature = None
        toolbar = QHBoxLayout()
        self.filter = QComboBox()
        self.filter.addItem("全部任务", "all")
        self.filter.addItem("进行中", "active")
        self.filter.addItem("未完成 / 需复核", "errors")
        self.filter.currentIndexChanged.connect(self.refresh)
        toolbar.addWidget(self.filter)
        self.task_picker = QComboBox()
        self.task_picker.setMinimumWidth(100)
        self.task_picker.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.task_picker.currentIndexChanged.connect(self.pick_task)
        self.task_picker.setVisible(compact)
        toolbar.addWidget(self.task_picker, 1)
        self.filter.setVisible(not compact)
        toolbar.addStretch()
        toolbar.addWidget(icon_button("清理已结束的任务及日志", context.tasks.clear_completed,
                                       QStyle.StandardPixmap.SP_TrashIcon))
        self.layout.addLayout(toolbar)
        self.split = QSplitter(Qt.Orientation.Vertical)
        self.list = table(["时间", "任务", "目标设备", "状态"])
        self.list.itemSelectionChanged.connect(self.selection_changed)
        self.split.addWidget(self.list)
        self.list.setVisible(not compact)
        details = QWidget()
        layout = QVBoxLayout(details)
        layout.setContentsMargins(0, 0, 0, 0)
        tools = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("筛选日志")
        self.search.textChanged.connect(self.render_detail)
        tools.addWidget(self.search, 1)
        self.stop = icon_button("停止后续步骤 / 取消排队", self.cancel, QStyle.StandardPixmap.SP_MediaStop)
        tools.addWidget(self.stop)
        tools.addWidget(icon_button("复制日志", self.copy, QStyle.StandardPixmap.SP_FileDialogDetailedView))
        tools.addWidget(icon_button("导出完整日志", lambda: self.guard(self.export), QStyle.StandardPixmap.SP_DialogSaveButton))
        self.output_button = icon_button("打开输出目录", self.open_output, QStyle.StandardPixmap.SP_DirOpenIcon)
        tools.addWidget(self.output_button)
        layout.addLayout(tools)
        self.result = QPlainTextEdit("暂无任务")
        self.result.setReadOnly(True)
        self.result.setMaximumHeight(80)
        if compact:
            self.result.setMinimumHeight(35)
            self.result.setMaximumHeight(45)
        layout.addWidget(self.result)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setObjectName("log")
        self.log.setMinimumHeight(90)
        self.log.document().setMaximumBlockCount(2000)
        layout.addWidget(self.log, 1)
        self.split.addWidget(details)
        self.split.setSizes([220, 340])
        saved = context.preferences.get("tasks/split", None)
        if saved:
            try:
                self.split.setSizes([int(value) for value in saved])
            except (TypeError, ValueError):
                pass
        self.split.splitterMoved.connect(lambda *_: context.preferences.set("tasks/split", self.split.sizes()))
        self.layout.addWidget(self.split, 1)
        context.tasks.changed.connect(self.refresh)
        self.refresh()

    def task(self):
        return next((t for t in self.context.tasks.tasks if t.id == self.selected_id), None)

    def refresh(self):
        mode = self.filter.currentData()
        tasks = list(reversed(self.context.tasks.tasks))
        if mode == "active":
            tasks = [t for t in tasks if t.status in {"queued", "running", "stopping"}]
        elif mode == "errors":
            tasks = [t for t in tasks if t.status in {"failed", "partial", "interrupted", "cancelled"}]
        signature = [(t.id, t.status) for t in tasks]
        if signature != self.signature:
            self.signature = signature
            self.visible_tasks = tasks
            self.list.blockSignals(True)
            set_rows(self.list, [(t.created.replace("T", " "), t.title, t.target or "本机",
                                 STATUS[t.status]) for t in tasks])
            index = next((i for i, t in enumerate(tasks) if t.id == self.selected_id), 0)
            if tasks:
                self.selected_id = tasks[index].id
                self.list.selectRow(index)
            else:
                self.selected_id = None
            self.list.blockSignals(False)
            self.task_picker.blockSignals(True)
            self.task_picker.clear()
            for task in tasks:
                self.task_picker.addItem(task.title + " · " + STATUS[task.status], task.id)
            self.task_picker.setCurrentIndex(self.task_picker.findData(self.selected_id))
            self.task_picker.blockSignals(False)
        self.render_detail()

    def pick_task(self):
        self.selected_id = self.task_picker.currentData()
        self.render_detail()

    def selection_changed(self):
        rows = self.list.selectionModel().selectedRows()
        if rows:
            self.selected_id = self.visible_tasks[rows[0].row()].id
            self.render_detail()

    def lines(self, task):
        if task.logs:
            return list(task.logs)
        path = self.context.preferences.logs / f"{task.id}.log"
        if path.is_file():
            from collections import deque
            with path.open(encoding="utf-8", errors="replace") as handle:
                task.logs.extend(line.rstrip() for line in deque(handle, maxlen=2000))
        return list(task.logs)

    def render_detail(self):
        task = self.task()
        self.stop.setEnabled(bool(task and task.status in {"queued", "running"}))
        self.output_button.setEnabled(bool(task and task.outcome and task.outcome.output))
        if not task:
            self.result.setPlainText("暂无任务")
            self.log.clear()
            return
        details = [STATUS[task.status], task.message]
        if task.outcome:
            details.extend(f"{Path(i['name']).name} · {STATUS.get(i['status'], i['status'])}: {i['detail']}"
                           for i in task.outcome.items)
        summary = "\n".join(v for v in details if v)
        if summary != self.result.toPlainText():
            self.result.setPlainText(summary)
        self.result.setToolTip(summary)
        query = self.search.text().lower()
        text = "\n".join(line for line in self.lines(task) if query in line.lower())
        if text != self.log.toPlainText():
            scroll = self.log.verticalScrollBar()
            at_end, position = scroll.value() >= scroll.maximum() - 2, scroll.value()
            self.log.setPlainText(text)
            scroll.setValue(scroll.maximum() if at_end else position)

    def cancel(self):
        task = self.task()
        if task:
            self.context.tasks.cancel(task)

    def copy(self):
        QApplication.clipboard().setText(self.log.toPlainText())

    def export(self):
        task = self.task()
        if not task:
            return
        destination, _ = QFileDialog.getSaveFileName(self, "导出日志", f"task-{task.id[:8]}.log", "日志 (*.log)")
        if destination:
            import shutil
            source = self.context.preferences.logs / f"{task.id}.log"
            if source.is_file():
                if source.resolve() != Path(destination).resolve():
                    shutil.copyfile(source, destination)
            else:
                Path(destination).write_text(task.message, encoding="utf-8")

    def open_output(self):
        task = self.task()
        if task and task.outcome:
            open_path(task.outcome.output)
