from PySide6.QtWidgets import QHBoxLayout, QLabel, QStyle

from . import operations
from .services import Tools
from .widgets import Page, STATUS, button, icon_button, table, set_rows


class EmulatorPage(Page):
    def __init__(self, context):
        super().__init__(context)
        self.pending = set()
        self.rows = []
        self.results = {}
        toolbar = QHBoxLayout()
        self.count = QLabel()
        toolbar.addWidget(self.count)
        toolbar.addStretch()
        toolbar.addWidget(icon_button("刷新设备", context.devices.refresh,
                                       QStyle.StandardPixmap.SP_BrowserReload))
        self.layout.addLayout(toolbar)
        self.devices = table(["设备", "序列号", "类型", "状态", "关闭结果"])
        self.layout.addWidget(self.devices, 1)
        actions = QHBoxLayout()
        self.selected = button("关闭选中模拟器", lambda: self.guard(lambda: self.close(False)),
                               QStyle.StandardPixmap.SP_DialogCloseButton)
        self.all = button("关闭全部模拟器", lambda: self.guard(lambda: self.close(True)),
                          QStyle.StandardPixmap.SP_ComputerIcon, True)
        actions.addWidget(self.selected)
        actions.addWidget(self.all)
        actions.addStretch()
        self.layout.addLayout(actions)
        self.devices.itemSelectionChanged.connect(self.update_actions)
        context.devices.changed.connect(self.render)
        context.tasks.finished.connect(self.completed)
        context.tools.changed.connect(self.update_actions)
        self.render(context.devices.items, context.devices.error)

    def render(self, devices, error=""):
        selected = {self.rows[i.row()].serial for i in self.devices.selectionModel().selectedRows()
                    if i.row() < len(self.rows)}
        self.rows = list(devices)
        set_rows(self.devices, [(d.model or d.serial, d.serial, "模拟器" if d.emulator else "真机 / 其他",
                                STATUS.get(d.state, d.state), self.results.get(d.serial, "")) for d in devices])
        for row, device in enumerate(self.rows):
            if device.serial in selected:
                self.devices.selectRow(row)
        self.count.setText(f"{sum(d.emulator for d in devices)} 台模拟器 · {len(devices)} 台设备")
        if error:
            self.notify(error, True)
        self.update_actions()

    def update_actions(self):
        selected = [self.rows[i.row()] for i in self.devices.selectionModel().selectedRows()
                    if i.row() < len(self.rows)]
        ready = Tools.available(self.context.tools.snapshot(), "adb") and not self.pending
        self.selected.setEnabled(any(d.emulator for d in selected) and ready)
        self.all.setEnabled(any(d.emulator for d in self.rows) and ready)

    def close(self, all_devices):
        devices = self.rows if all_devices else [self.rows[i.row()] for i in self.devices.selectionModel().selectedRows()]
        serials = tuple(d.serial for d in devices if d.emulator)
        if not serials:
            raise ValueError("没有选中模拟器。")
        tools = self.context.tools.snapshot()
        Tools.require(tools, "adb")
        task = self.context.tasks.submit(f"关闭 {len(serials)} 台模拟器", "emulators",
                                         lambda ctx: operations.close_devices(ctx, serials, tools), ", ".join(serials))
        self.pending.add(task.id)
        self.update_actions()
        self.notify("关闭任务已提交：" + "、".join(serials))

    def completed(self, task):
        if task.id not in self.pending:
            return
        self.pending.remove(task.id)
        for item in task.outcome.items if task.outcome else []:
            self.results[item["name"]] = item["detail"]
        self.notify(STATUS[task.status] + ("：" + task.message if task.message else ""),
                    task.status in {"failed", "partial"})
        self.context.devices.refresh()
        self.update_actions()
