from pathlib import Path

from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QStyle

from .services import Tools
from .widgets import Page, FileField, button, form, table, set_rows


class SettingsPage(Page):
    def __init__(self, context):
        super().__init__(context)
        preferences = context.preferences
        fields, layout = form()
        self.tool_fields = {}
        labels = {"adb": "ADB", "java": "Java", "keytool": "Keytool", "apktool": "Apktool JAR",
                  "build_tools": "Android Build Tools", "scrcpy": "scrcpy"}
        detected = context.tools.snapshot()
        for key in Tools.KEYS:
            widget = FileField(str(preferences.get("tools/" + key)), directory=key == "build_tools")
            widget.edit.setPlaceholderText(detected[key] or "未发现")
            self.tool_fields[key] = widget
            layout.addRow(labels[key], widget)
        self.output = FileField(str(preferences.output), directory=True)
        layout.addRow("工作输出目录", self.output)
        self.keystore = FileField(str(preferences.get("signing/key", str(preferences.root / "signing" / "lab.jks"))))
        layout.addRow("签名密钥", self.keystore)
        self.alias = QLineEdit(str(preferences.get("signing/alias", "android-lab")))
        layout.addRow("签名别名", self.alias)
        self.layout.addWidget(fields)
        actions = QHBoxLayout()
        actions.addWidget(button("保存设置", lambda: self.guard(self.save), QStyle.StandardPixmap.SP_DialogSaveButton, True))
        actions.addWidget(button("自动发现工具", self.reset_tools, QStyle.StandardPixmap.SP_BrowserReload))
        actions.addStretch()
        self.layout.addLayout(actions)
        self.dependencies = table(["工具", "实际使用路径", "状态"])
        self.layout.addWidget(self.dependencies, 1)
        self.check()

    def save(self):
        if not self.output.text() or not self.keystore.text() or not self.alias.text().strip():
            raise ValueError("输出目录、密钥路径和签名别名不能为空。")
        preferences = self.context.preferences
        for key, widget in self.tool_fields.items():
            preferences.set("tools/" + key, widget.text())
        preferences.set("output", self.output.text())
        preferences.set("signing/key", self.keystore.text())
        preferences.set("signing/alias", self.alias.text().strip())
        self.check()
        self.context.devices.refresh()
        self.context.tools.changed.emit()
        self.notify("设置已保存。")

    def reset_tools(self):
        for key, widget in self.tool_fields.items():
            widget.edit.clear()
            self.context.preferences.set("tools/" + key, "")
        self.check()
        self.context.devices.refresh()
        self.context.tools.changed.emit()

    def check(self):
        tools = self.context.tools.snapshot()
        rows = []
        for key in Tools.KEYS:
            try:
                Tools.require(tools, key)
                status = "可用"
            except RuntimeError:
                status = "缺失 / 无效"
            rows.append((key, tools[key], status))
            self.tool_fields[key].edit.setPlaceholderText(tools[key] or "未发现")
        set_rows(self.dependencies, rows)
