from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QStyle
from .widgets import Page, button, form, set_rows, table

class MetricsPage(Page):
    kind="device_metrics"
    def __init__(self, context):
        super().__init__(context); self.serial=""; self.latest=None
        bar=QHBoxLayout(); self.state=QLabel("未选择设备"); bar.addWidget(self.state,1)
        bar.addWidget(button("打开独立窗口",self.open_window,QStyle.StandardPixmap.SP_TitleBarMaxButton)); self.layout.addLayout(bar)
        self.values=table(["指标","值"]); self.layout.addWidget(self.values,1)
        context.selection_changed.connect(self.select); context.metrics.updated.connect(self.receive); context.metrics.failed.connect(self.failed)
    def showEvent(self,e): super().showEvent(e); self.select(self.context.selected_serial)
    def hideEvent(self,e): self.context.metrics.unsubscribe(self); super().hideEvent(e)
    def select(self,serial): self.serial=serial; self.context.metrics.unsubscribe(self); set_rows(self.values,[]); self.state.setText(serial or "未选择设备"); self.context.metrics.subscribe(self,serial,self.kind) if serial else None
    def receive(self,s):
        if s.serial==self.serial and s.kind==self.kind: self.latest=s; self.state.setText(f"{self.serial} · 实时采样"); set_rows(self.values,s.values)
    def failed(self,serial,kind,msg):
        if serial==self.serial and kind==self.kind: self.state.setText(msg)
    def open_window(self):
        package = self.package.currentText().strip() if hasattr(self.package, "currentText") else ""
        self.guard(lambda: self.context.metric_windows.open(self.serial,self.kind,package))

class AppMetricsPage(MetricsPage):
    kind="app_metrics"
    def __init__(self,context):
        super().__init__(context); self.package=QComboBox(); self.package.setEditable(True); self.package.setPlaceholderText("输入包名，例如 com.example.app"); self.layout.insertWidget(1,self.package); self.package.currentTextChanged.connect(self.select_package)
    def select_package(self,text):
        self.context.metrics.unsubscribe(self); self.context.metrics.subscribe(self,self.serial,self.kind,text) if self.serial and text else None
    def select(self,serial): super().select(serial); self.select_package(self.package.currentText())

class MetricsWindow(MetricsPage):
    def __init__(self,context,serial,kind,package=""):
        super().__init__(context); self.setWindowTitle("性能监测 · "+serial); self.resize(620,500)
        self.package=package; self.select(serial)
        if package and hasattr(self.package, "setCurrentText"): self.package.setCurrentText(package)
        self.show()

class MetricWindows:
    def __init__(self,context): self.context=context; self.windows={}
    def open(self,serial,kind,package=""):
        key=(serial,kind,package)
        if key not in self.windows: self.windows[key]=MetricsWindow(self.context,serial,kind,package)
        self.windows[key].raise_(); self.windows[key].activateWindow(); return self.windows[key]
    def close(self):
        for w in list(self.windows.values()): w.close()
        self.windows.clear()
