from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QFileDialog, QStyle

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
        self.setAcceptDrops(True)
        toolbar = QHBoxLayout()
        toolbar.addWidget(button("添加安装包", self.browse, QStyle.StandardPixmap.SP_FileIcon))
        toolbar.addWidget(icon_button("移除选中文件", self.remove, QStyle.StandardPixmap.SP_TrashIcon))
        toolbar.addWidget(icon_button("清空文件列表", self.clear, QStyle.StandardPixmap.SP_DialogResetButton))
        toolbar.addStretch()
        self.count = QLabel("0 个文件")
        toolbar.addWidget(self.count)
        self.layout.addLayout(toolbar)
        self.files = table(["安装包", "大小", "状态"])
        self.files.empty.setText("暂无安装包")
        self.files.horizontalHeader().resizeSection(0, 420)
        self.layout.addWidget(self.files, 1)
        options = QHBoxLayout()
        self.keep = QCheckBox("覆盖安装并保留数据")
        self.downgrade = QCheckBox("允许降级")
        options.addWidget(self.keep)
        options.addWidget(self.downgrade)
        options.addStretch()
        self.layout.addLayout(options)
        actions = QHBoxLayout()
        self.start = button("开始安装", lambda: self.guard(self.submit),
                            QStyle.StandardPixmap.SP_MediaPlay, True)
        self.retry = button("重试失败项", lambda: self.guard(lambda: self.submit(True)),
                            QStyle.StandardPixmap.SP_BrowserReload)
        self.start.setEnabled(False)
        self.retry.setEnabled(False)
        actions.addWidget(self.start)
        actions.addWidget(self.retry)
        actions.addStretch()
        self.layout.addLayout(actions)
        context.tasks.finished.connect(self.completed)
        context.tasks.changed.connect(self.update_progress)
        context.tools.changed.connect(self.render)

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
        selected = {self.files.item(index.row(), 0).toolTip()
                    for index in self.files.selectionModel().selectedRows()}
        rows = []
        for path in self.paths:
            size = f"{path.stat().st_size / 1024 / 1024:.1f} MB" if path.is_file() else "文件不存在"
            status = self.results.get(str(path), {}).get("status", "")
            rows.append((path.name, size, STATUS.get(status, "待安装")))
        set_rows(self.files, rows)
        for row, path in enumerate(self.paths):
            self.files.item(row, 0).setToolTip(str(path))
            self.files.item(row, 2).setToolTip(self.results.get(str(path), {}).get("detail", ""))
            if str(path) in selected:
                self.files.selectRow(row)
        self.count.setText(f"{len(self.paths)} 个文件")
        ready = Tools.available(self.context.tools.snapshot(), "adb") and not self.pending
        self.start.setEnabled(bool(self.paths) and ready)
        self.retry.setEnabled(any(self.results.get(str(path), {}).get("status") == "failed"
                                  for path in self.paths) and ready)

    def remove(self):
        selected = {index.row() for index in self.files.selectionModel().selectedRows()}
        self.paths = [path for i, path in enumerate(self.paths) if i not in selected]
        self.render()

    def clear(self):
        self.paths.clear()
        self.results.clear()
        self.render()

    def submit(self, retry=False):
        paths = tuple(path for path in self.paths if not retry or
                      self.results.get(str(path), {}).get("status") == "failed")
        if not paths:
            raise ValueError("请添加安装包。")
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
        self.notify("安装任务已提交：" + target)

    def update_progress(self):
        previous = {key: dict(value) for key, value in self.results.items()}
        for task in self.context.tasks.tasks:
            if task.id not in self.pending:
                continue
            for item in task.outcome.items if task.outcome else []:
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
        self.pending_paths.pop(task.id, None)
        for item in task.outcome.items if task.outcome else []:
            self.results[item["name"]] = item
        for result in self.results.values():
            if result["status"] in {"queued", "running"}:
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
