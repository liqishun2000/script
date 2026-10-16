from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QBoxLayout, QCheckBox, QFileDialog, QHBoxLayout, QLabel,
    QLayout, QSizePolicy, QStyle, QWidget,
)

from . import operations
from .services import Tools
from .widgets import Page, STATUS, button, icon_button, table, set_rows


class InstallPage(Page):
    def __init__(self, context):
        super().__init__(context)
        self.paths = []
        self.results = {}
        self.pending = set()
        self.pending_paths = {}
        self.adb_available = False
        self.setAcceptDrops(True)
        toolbar = QHBoxLayout()
        toolbar.addWidget(button("添加安装包", self.browse, QStyle.StandardPixmap.SP_FileIcon))
        toolbar.addWidget(icon_button("移除选中文件", self.remove, QStyle.StandardPixmap.SP_TrashIcon))
        toolbar.addWidget(icon_button("清空文件列表", self.clear, QStyle.StandardPixmap.SP_DialogResetButton))
        toolbar.addStretch()
        self.count = QLabel()
        self.count.setWordWrap(True)
        self.count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        toolbar.addWidget(self.count)
        self.layout.addLayout(toolbar)
        self.files = table(["安装包", "大小", "状态"])
        self.files.empty.setText("暂无安装包")
        self.files.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.files.setToolTip("单击选中一个安装包；Ctrl 多选，Shift 连选。")
        self.files.horizontalHeader().resizeSection(0, 420)
        self.layout.addWidget(self.files, 1)
        options = QHBoxLayout()
        self.keep = QCheckBox("覆盖安装并保留数据")
        self.downgrade = QCheckBox("允许降级")
        options.addWidget(self.keep)
        options.addWidget(self.downgrade)
        options.addStretch()
        self.layout.addLayout(options)
        self.action_bar = QWidget()
        self.action_bar.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.actions = QBoxLayout(QBoxLayout.Direction.LeftToRight, self.action_bar)
        self.actions.setContentsMargins(0, 0, 0, 0)
        self.actions.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.start = button("安装选中项（0）", lambda: self.guard(self.submit),
                            QStyle.StandardPixmap.SP_MediaPlay, True)
        self.install_all = button("安装全部（0）", lambda: self.guard(lambda: self.submit("all")),
                                  QStyle.StandardPixmap.SP_MediaPlay)
        self.retry = button("重试失败项", lambda: self.guard(lambda: self.submit("failed")),
                            QStyle.StandardPixmap.SP_BrowserReload)
        self.start.setToolTip("只安装选中的安装包。")
        self.install_all.setToolTip("安装列表中的全部安装包，不受当前选择范围影响。")
        self.retry.setToolTip("重试列表中全部失败项，不受当前选择范围影响。")
        self.actions.addWidget(self.start)
        self.actions.addWidget(self.install_all)
        self.actions.addWidget(self.retry)
        self.actions.addStretch()
        self.layout.addWidget(self.action_bar)
        self.files.itemSelectionChanged.connect(self.update_actions)
        context.tasks.finished.connect(self.completed)
        context.tasks.changed.connect(self.update_progress)
        context.tools.changed.connect(self.refresh_tools)
        self.refresh_tools()

    def selected_paths(self):
        return tuple(Path(item.data(Qt.ItemDataRole.UserRole))
                     for index in sorted(self.files.selectionModel().selectedRows(), key=lambda index: index.row())
                     if (item := self.files.item(index.row(), 0)) is not None)

    def refresh_tools(self):
        self.adb_available = Tools.available(self.context.tools.snapshot(), "adb")
        self.update_actions()

    def update_actions(self):
        selected, total = len(self.selected_paths()), len(self.paths)
        self.count.setText(f"共 {total} 个文件 · 已选 {selected} 个")
        self.start.setText(f"安装选中项（{selected}）")
        self.install_all.setText(f"安装全部（{total}）")
        ready = self.adb_available and not self.pending
        self.start.setEnabled(bool(selected) and ready)
        self.install_all.setEnabled(bool(total) and ready)
        self.retry.setEnabled(any(self.results.get(str(path), {}).get("status") == "failed"
                                  for path in self.paths) and ready)
        self.fit_actions()

    def fit_actions(self):
        buttons = (self.start, self.install_all, self.retry)
        width = sum(control.minimumSizeHint().width() for control in buttons) + self.actions.spacing() * 2
        self.actions.setDirection(QBoxLayout.Direction.TopToBottom if width > self.width()
                                  else QBoxLayout.Direction.LeftToRight)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "retry"):
            self.fit_actions()

    def browse(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择安装包", str(self.context.preferences.get("recent/install")),
            "Android 安装包 (*.apk *.xapk *.apks *.apkm)")
        self.add_files(paths)

    def add_files(self, paths):
        invalid = []
        for value in paths:
            path = Path(value).resolve()
            if not path.is_file() or path.suffix.lower() not in {".apk", ".xapk", ".apks", ".apkm"}:
                invalid.append(path.name)
            elif path not in self.paths:
                self.paths.append(path)
                self.context.preferences.set("recent/install", str(path.parent))
        self.render()
        if invalid:
            self.notify("未添加：" + "、".join(invalid), True)

    def render(self):
        selected = set(self.selected_paths())
        current = self.files.item(self.files.currentRow(), 0)
        current_path = current.data(Qt.ItemDataRole.UserRole) if current else None
        vertical, horizontal = self.files.verticalScrollBar().value(), self.files.horizontalScrollBar().value()
        rows = []
        for path in self.paths:
            size = f"{path.stat().st_size / 1024 / 1024:.1f} MB" if path.is_file() else "文件不存在"
            status = self.results.get(str(path), {}).get("status", "")
            rows.append((path.name, size, STATUS.get(status, "待安装")))
        with QSignalBlocker(self.files):
            self.files.clearSelection()
            set_rows(self.files, rows)
            selection = self.files.selectionModel()
            current_row = -1
            for row, path in enumerate(self.paths):
                self.files.item(row, 0).setData(Qt.ItemDataRole.UserRole, str(path))
                self.files.item(row, 0).setToolTip(str(path))
                self.files.item(row, 2).setToolTip(self.results.get(str(path), {}).get("detail", ""))
                if str(path) == current_path:
                    current_row = row
                if path in selected:
                    selection.select(self.files.model().index(row, 0),
                                     QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
            selection.setCurrentIndex(self.files.model().index(current_row, 0),
                                      QItemSelectionModel.SelectionFlag.NoUpdate)
        self.files.verticalScrollBar().setValue(vertical)
        self.files.horizontalScrollBar().setValue(horizontal)
        self.update_actions()

    def remove(self):
        selected = set(self.selected_paths())
        self.paths = [path for path in self.paths if path not in selected]
        self.render()

    def clear(self):
        self.paths.clear()
        self.results.clear()
        self.render()

    def submit(self, scope="selected"):
        if self.pending:
            raise ValueError("当前安装任务尚未结束。")
        if scope == "selected":
            paths = self.selected_paths()
            empty_message = "请先选中要安装的安装包。"
        elif scope == "all":
            paths = tuple(self.paths)
            empty_message = "请添加安装包。"
        elif scope == "failed":
            paths = tuple(path for path in self.paths if self.results.get(str(path), {}).get("status") == "failed")
            empty_message = "没有可重试的失败项。"
        else:
            raise ValueError("未知安装范围。")
        if not paths:
            raise ValueError(empty_message)
        target = self.context.target()
        tools = self.context.tools.snapshot()
        Tools.require(tools, "adb")
        keep, downgrade = self.keep.isChecked(), self.downgrade.isChecked()
        task = self.context.tasks.submit(
            f"安装 {len(paths)} 个包", "install",
            lambda ctx: operations.install_packages(ctx, paths, target, tools, keep, downgrade), target)
        self.pending.add(task.id)
        self.pending_paths[task.id] = paths
        for path in paths:
            self.results[str(path)] = {"status": "queued", "detail": ""}
        self.render()
        self.notify(f"已提交 {len(paths)} 个安装包 · {target}")

    def update_progress(self):
        previous = {key: dict(value) for key, value in self.results.items()}
        for task in self.context.tasks.tasks:
            if task.id not in self.pending:
                continue
            task_paths = {str(path) for path in self.pending_paths[task.id]}
            for item in task.outcome.items if task.outcome else []:
                if item["name"] in task_paths:
                    self.results[item["name"]] = item
            if task.status in {"running", "stopping"}:
                waiting = [str(path) for path in self.pending_paths[task.id]
                           if self.results.get(str(path), {}).get("status") in {"queued", "running"}]
                if waiting:
                    self.results[waiting[0]] = {"status": "running", "detail": STATUS[task.status]}
        if self.results != previous:
            self.render()

    def completed(self, task):
        if task.id not in self.pending:
            return
        self.pending.remove(task.id)
        paths = self.pending_paths.pop(task.id)
        task_paths = {str(path) for path in paths}
        for item in task.outcome.items if task.outcome else []:
            if item["name"] in task_paths:
                self.results[item["name"]] = item
        for path in paths:
            result = self.results.get(str(path), {})
            if result.get("status") in {"queued", "running"}:
                result.update(status=task.status, detail=task.message)
        self.render()
        self.notify(STATUS[task.status] + ("：" + task.message if task.message else ""),
                    task.status in {"failed", "partial"})

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.add_files([url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()])
        event.acceptProposedAction()
