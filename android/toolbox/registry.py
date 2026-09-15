from dataclasses import dataclass
from importlib import import_module

from PySide6.QtWidgets import QStyle


@dataclass(frozen=True)
class ToolSpec:
    id: str
    title: str
    category: str
    icon: QStyle.StandardPixmap
    factory: str
    dependencies: tuple[str, ...] = ()

    def create(self, context):
        module, name = self.factory.rsplit(":", 1)
        return getattr(import_module(module), name)(context)


class Registry:
    def __init__(self):
        self.entries = {}

    def register(self, spec):
        if spec.id in self.entries:
            raise ValueError("Duplicate tool id: " + spec.id)
        self.entries[spec.id] = spec


def builtins():
    registry = Registry()
    prefix = "android.toolbox."
    for spec in (
        ToolSpec("install", "安装包安装", "应用工具", QStyle.StandardPixmap.SP_FileIcon,
                 prefix + "install_page:InstallPage", ("adb",)),
        ToolSpec("gpcheck", "GPCheck 处理", "应用工具", QStyle.StandardPixmap.SP_FileDialogDetailedView,
                 prefix + "gpcheck_page:GpCheckPage", ("java", "apktool")),
        ToolSpec("emulators", "模拟器管理", "设备工具", QStyle.StandardPixmap.SP_ComputerIcon,
                 prefix + "emulator_page:EmulatorPage", ("adb",)),
        ToolSpec("tasks", "任务记录", "工作区", QStyle.StandardPixmap.SP_FileDialogListView,
                 prefix + "task_page:TaskPage"),
        ToolSpec("settings", "设置", "工作区", QStyle.StandardPixmap.SP_FileDialogInfoView,
                 prefix + "settings_page:SettingsPage"),
    ):
        registry.register(spec)
    return registry
