from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QStyle

from . import operations
from .services import Tools
from .widgets import Page, FileField, STATUS, button, form, table, set_rows, open_path


class GpCheckPage(Page):
    def __init__(self, context):
        super().__init__(context)
        self.analysis = None
        self.build_result = None
        self.jobs = {}
        source_form, layout = form()
        self.source = FileField(file_filter="XAPK (*.xapk)")
        self.source.changed.connect(self.invalidate)
        layout.addRow("XAPK 文件", self.source)
        self.layout.addWidget(source_form)
        self.actions = QGridLayout()
        self.analyze_button = button("分析安装包", lambda: self.guard(lambda: self.submit("analyze")),
                                     QStyle.StandardPixmap.SP_FileDialogContentsView, True)
        self.original_button = button("原包安装与验证", lambda: self.guard(lambda: self.submit("original")),
                                      QStyle.StandardPixmap.SP_MediaPlay)
        self.build_button = button("构建补丁", lambda: self.guard(lambda: self.submit("build")),
                                   QStyle.StandardPixmap.SP_FileDialogDetailedView)
        self.install_button = button("补丁安装与验证", lambda: self.guard(lambda: self.submit("patched")),
                                     QStyle.StandardPixmap.SP_MediaPlay)
        self.action_buttons = [self.analyze_button, self.original_button, self.build_button, self.install_button]
        self.layout.addLayout(self.actions)
        self.summary = table(["检测项", "结果"])
        self.summary.empty.setText("暂无分析结果")
        self.summary.setMinimumHeight(170)
        self.layout.addWidget(self.summary, 1)
        self.evidence = QPlainTextEdit()
        self.evidence.setReadOnly(True)
        self.evidence.setMaximumHeight(120)
        self.layout.addWidget(self.evidence)
        options = QHBoxLayout()
        self.permissions = QCheckBox("安装后配置清理权限")
        options.addWidget(self.permissions)
        options.addStretch()
        self.layout.addLayout(options)
        signature, layout = form()
        self.password = QLineEdit("android")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setMaximumWidth(280)
        layout.addRow("签名密码", self.password)
        self.layout.addWidget(signature)
        self.open_button = button("打开输出目录", self.open_output, QStyle.StandardPixmap.SP_DirOpenIcon)
        self.layout.addWidget(self.open_button)
        context.tasks.finished.connect(self.completed)
        context.tools.changed.connect(self.update_actions)
        self.update_actions()
        self.source.edit.setText(str(context.preferences.get("recent/gpcheck")))
        self.reflow()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reflow()

    def reflow(self):
        columns = 4 if self.width() >= 900 else 2 if self.width() >= 430 else 1
        for index, widget in enumerate(self.action_buttons):
            self.actions.addWidget(widget, index // columns, index % columns)
        for index in range(4):
            self.actions.setColumnStretch(index, 1 if index < columns else 0)

    def invalidate(self):
        self.analysis = None
        self.build_result = None
        self.summary.setRowCount(0)
        self.evidence.clear()
        self.update_actions()

    def update_actions(self):
        busy = bool(self.jobs)
        tools = self.context.tools.snapshot()
        device_ready = Tools.available(tools, "adb")
        self.source.setEnabled(not busy)
        self.analyze_button.setEnabled(not busy and bool(self.source.text()) and Tools.available(tools, "java", "apktool"))
        self.original_button.setEnabled(not busy and bool(self.analysis and self.analysis.main_activity) and device_ready)
        build_available = bool(self.analysis and self.analysis.supported and
                               not (self.analysis.workspace / "dist").exists())
        self.build_button.setEnabled(not busy and build_available and not self.build_result and
                                     Tools.available(tools, "java", "apktool", "keytool", "build_tools"))
        self.install_button.setEnabled(not busy and self.build_result is not None and device_ready)
        self.open_button.setEnabled(self.analysis is not None)

    def submit(self, stage):
        tools = self.context.tools.snapshot()
        preferences = self.context.preferences
        source = self.source.text()
        analysis, build_result = self.analysis, self.build_result
        target = ""
        if stage == "analyze":
            if not Path(source).is_file() or Path(source).suffix.lower() != ".xapk":
                raise ValueError("请选择有效的 XAPK 文件。")
            Tools.require(tools, "java", "apktool")
            preferences.set("recent/gpcheck", source)
            output = str(preferences.output)
            self.invalidate()
            operation = lambda ctx: operations.analyze(ctx, source, output, tools)
            title = "分析 " + Path(source).name
        elif stage == "build":
            Tools.require(tools, "java", "keytool", "apktool", "build_tools")
            key = str(preferences.get("signing/key", str(preferences.root / "signing" / "lab.jks")))
            alias = str(preferences.get("signing/alias", "android-lab"))
            password = self.password.text()
            if not alias or not password:
                raise ValueError("签名别名和密码不能为空。")
            operation = lambda ctx: operations.build(ctx, analysis, tools, key, alias, password)
            title = "构建补丁 " + analysis.app_name
        else:
            Tools.require(tools, "adb")
            target = self.context.target()
            permissions = self.permissions.isChecked()
            patch = build_result if stage == "patched" else None
            operation = lambda ctx: operations.verify(ctx, analysis, patch, target, tools, permissions)
            title = ("补丁" if patch else "原包") + "安装与验证 " + analysis.app_name
        task = self.context.tasks.submit(title, "gpcheck", operation, target)
        self.jobs[task.id] = stage
        self.update_actions()
        self.notify("任务已提交：" + title)

    def completed(self, task):
        stage = self.jobs.pop(task.id, None)
        if not stage:
            return
        result = task.outcome.value if task.outcome else None
        if result is not None:
            if stage == "analyze":
                self.analysis = result
                set_rows(self.summary, [("应用", result.app_name), ("包名", result.package_name),
                                        ("版本", result.version_name), ("Application", result.application_name),
                                        ("检测置信度", result.confidence),
                                        ("补丁支持", "支持" if result.supported else "未发现受支持的补丁模式")])
                self.evidence.setPlainText("\n".join(result.evidence + [a.description for a in result.actions]))
            elif stage == "build":
                self.build_result = result
                self.evidence.setPlainText(f"输出：{result.patched_xapk}\n证书 SHA-256：{result.certificate_sha256}")
            else:
                self.evidence.setPlainText(
                    f"验证：{'通过' if result.success else '需复核'}\n安装来源：{result.installer_package}\n"
                    f"前台：{result.foreground}\nPID：{result.pid}\n截图：{result.screenshot or ''}\n" +
                    "\n".join(result.suspicious_logs))
        self.update_actions()
        self.notify(STATUS[task.status] + ("：" + task.message if task.message else ""),
                    task.status in {"failed", "partial"})

    def open_output(self):
        open_path(self.build_result.output_dir if self.build_result else self.analysis.workspace)
