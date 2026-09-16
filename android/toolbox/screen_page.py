from PySide6.QtWidgets import QComboBox, QHBoxLayout, QStyle

from .screen_control import QUALITY
from .widgets import Page, button, form, set_rows, table


class ScreenPage(Page):
    def __init__(self, context):
        super().__init__(context)
        fields, layout = form()
        self.quality = QComboBox()
        self.quality.addItems([entry[0] for entry in QUALITY])
        self.quality.setCurrentIndex(1)
        layout.addRow("画质", self.quality)
        self.layout.addWidget(fields)
        actions = QHBoxLayout()
        actions.addWidget(button("打开屏幕控制", lambda: self.guard(self.open),
                                 QStyle.StandardPixmap.SP_ComputerIcon, True))
        actions.addStretch()
        self.layout.addLayout(actions)
        self.windows = table(["设备", "窗口"])
        self.windows.cellDoubleClicked.connect(lambda row, _: self.activate(row))
        self.layout.addWidget(self.windows, 1)
        context.screens.changed.connect(self.render)
        self.render()

    def open(self):
        self.context.screens.open(self.context.target(), self.quality.currentIndex())

    def activate(self, row):
        item = self.windows.item(row, 0)
        if item:
            self.guard(lambda: self.context.screens.open(item.text()))

    def render(self):
        set_rows(self.windows, [(serial, "已打开") for serial in self.context.screens.windows])
