import json, time
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QStyle
from .widgets import Page, button, set_rows, table

class HistoryPage(Page):
    def __init__(self, context):
        super().__init__(context); self.context=context
        bar=QHBoxLayout(); self.state=QLabel("最近 500 条记录"); bar.addWidget(self.state,1)
        bar.addWidget(button("刷新",self.render,QStyle.StandardPixmap.SP_BrowserReload)); bar.addWidget(button("导出 CSV",self.export,QStyle.StandardPixmap.SP_DialogSaveButton)); self.layout.addLayout(bar)
        self.rows=table(["时间","设备","类型","包名","指标"]); self.layout.addWidget(self.rows,1); self.render()
    def render(self):
        rows=[]
        for serial,kind,package,ts,values in self.context.metrics.store.recent(limit=500):
            values=json.loads(values); rows.append((time.strftime("%Y-%m-%d %H:%M:%S",time.localtime(ts)),serial,"设备" if kind=="device_metrics" else "App",package or "-", "；".join(f"{k}: {v}" for k,v in list(values.items())[:3])))
        set_rows(self.rows,rows); self.state.setText(f"最近 {len(rows)} 条记录")
    def export(self):
        path,_=QFileDialog.getSaveFileName(self,"导出监测记录","metrics.csv","CSV (*.csv)")
        if path: self.context.metrics.store.export_csv(__import__('pathlib').Path(path)); self.notify("已导出监测记录。")
