"""
XAPK 安装器 - GUI 入口。

用法:
    py install_xapk.py            # 启动 GUI（默认）
    py install_xapk.py app.xapk   # 仍然支持纯命令行模式
    pyw install_xapk.py           # 无控制台窗口启动 GUI

GUI 功能:
    - 把 .xapk / .apks / .apkm 文件拖入窗口（需要 tkinterdnd2）
    - 或点击"浏览…"选择文件
    - 选择目标设备、覆盖安装 / 降级安装等选项
    - 点击"安装"在后台线程执行，安装日志实时显示

未来扩展可以在这里继续加 Tab：批量安装、卸载、查包信息、抓 logcat 等。
"""

from __future__ import annotations

import argparse
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from xapk_installer import (
    InstallError,
    install_many,
    install_xapk,
    list_devices,
)

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _DND_OK = True
except ImportError:
    _DND_OK = False


# -------- 后台线程与日志队列 --------

class _LogPump:
    """跨线程日志泵：后台线程往 queue 里塞，主线程 after 轮询写到 Text。"""

    def __init__(self, text_widget: tk.Text):
        self.text = text_widget
        self.q: queue.Queue[str | None] = queue.Queue()
        self.text.after(80, self._drain)

    def log(self, msg: str) -> None:
        self.q.put(msg)

    def _drain(self) -> None:
        try:
            while True:
                msg = self.q.get_nowait()
                if msg is None:
                    continue
                self.text.configure(state="normal")
                self.text.insert("end", msg + "\n")
                self.text.see("end")
                self.text.configure(state="disabled")
        except queue.Empty:
            pass
        self.text.after(80, self._drain)


# -------- 主窗口 --------

class XapkGui:
    SUPPORTED_EXTS = (".xapk", ".apks", ".apkm", ".apk", ".zip")

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("XAPK 安装器")
        self.root.geometry("720x560")
        self.root.minsize(620, 480)

        self.files: list[Path] = []
        self.installing = False

        self._build_ui()
        self.log_pump = _LogPump(self.log_text)
        self.refresh_devices()

        self._log_intro()

    # --- UI 构建 ---

    def _build_ui(self) -> None:
        pad = {"padx": 10, "pady": 6}

        top = ttk.Frame(self.root)
        top.pack(fill="x", **pad)

        self.drop_label = tk.Label(
            top,
            text=(
                "把 .xapk / .apks / .apkm 文件拖到这里\n或点击下方“浏览…”按钮选择"
                if _DND_OK
                else "拖拽功能不可用（未安装 tkinterdnd2）\n请点击下方“浏览…”按钮选择文件"
            ),
            relief="groove",
            borderwidth=2,
            height=4,
            background="#f5f5f5",
            fg="#666",
            font=("Microsoft YaHei UI", 10),
        )
        self.drop_label.pack(fill="x", expand=True)

        if _DND_OK:
            self.drop_label.drop_target_register(DND_FILES)
            self.drop_label.dnd_bind("<<Drop>>", self._on_drop)

        # 文件列表
        list_frame = ttk.LabelFrame(self.root, text="待安装文件")
        list_frame.pack(fill="both", expand=False, **pad)

        self.file_list = tk.Listbox(list_frame, height=4, activestyle="dotbox")
        self.file_list.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=6)
        if _DND_OK:
            self.file_list.drop_target_register(DND_FILES)
            self.file_list.dnd_bind("<<Drop>>", self._on_drop)

        btns = ttk.Frame(list_frame)
        btns.pack(side="left", fill="y", padx=8, pady=6)
        ttk.Button(btns, text="浏览…", command=self.browse).pack(fill="x")
        ttk.Button(btns, text="移除", command=self.remove_selected).pack(fill="x", pady=(6, 0))
        ttk.Button(btns, text="清空", command=self.clear_files).pack(fill="x", pady=(6, 0))

        # 选项区
        opts = ttk.LabelFrame(self.root, text="选项")
        opts.pack(fill="x", **pad)

        line1 = ttk.Frame(opts)
        line1.pack(fill="x", padx=8, pady=4)
        ttk.Label(line1, text="目标设备:").pack(side="left")
        self.device_var = tk.StringVar()
        self.device_combo = ttk.Combobox(
            line1, textvariable=self.device_var, state="readonly", width=30
        )
        self.device_combo.pack(side="left", padx=(6, 6))
        ttk.Button(line1, text="刷新", command=self.refresh_devices).pack(side="left")

        line2 = ttk.Frame(opts)
        line2.pack(fill="x", padx=8, pady=4)
        self.keep_data_var = tk.BooleanVar(value=True)
        self.downgrade_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            line2, text="覆盖安装并保留数据 (-r)", variable=self.keep_data_var
        ).pack(side="left")
        ttk.Checkbutton(
            line2, text="允许降级安装 (-d)", variable=self.downgrade_var
        ).pack(side="left", padx=(16, 0))

        # 操作按钮
        action = ttk.Frame(self.root)
        action.pack(fill="x", **pad)
        self.install_btn = ttk.Button(action, text="安  装", command=self.start_install)
        self.install_btn.pack(side="right")
        ttk.Button(action, text="清空日志", command=self.clear_log).pack(side="right", padx=(0, 8))

        # 日志
        log_frame = ttk.LabelFrame(self.root, text="日志")
        log_frame.pack(fill="both", expand=True, **pad)
        self.log_text = tk.Text(
            log_frame, height=12, state="disabled", wrap="word",
            font=("Consolas", 9), background="#1e1e1e", foreground="#dcdcdc",
            insertbackground="#dcdcdc",
        )
        self.log_text.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=6)
        sb = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        sb.pack(side="right", fill="y", pady=6, padx=(0, 8))
        self.log_text.configure(yscrollcommand=sb.set)

    def _log_intro(self) -> None:
        self.log("XAPK 安装器已就绪。")
        if not _DND_OK:
            self.log("提示: 若想启用文件拖拽，请运行: pip install tkinterdnd2")

    # --- 事件 ---

    def _on_drop(self, event) -> None:
        raw = event.data
        paths = self.root.tk.splitlist(raw)
        added = 0
        for p in paths:
            path = Path(p)
            if path.suffix.lower() not in self.SUPPORTED_EXTS:
                self.log(f"忽略非 XAPK 文件: {path.name}")
                continue
            if not path.exists():
                self.log(f"忽略不存在的路径: {path}")
                continue
            if path not in self.files:
                self.files.append(path)
                self.file_list.insert("end", str(path))
                added += 1
        if added:
            self.log(f"添加了 {added} 个文件，共 {len(self.files)} 个待安装。")

    def browse(self) -> None:
        paths = filedialog.askopenfilenames(
            title="选择 XAPK 文件",
            filetypes=[
                ("XAPK / split apk", "*.xapk *.apks *.apkm"),
                ("APK", "*.apk"),
                ("所有文件", "*.*"),
            ],
        )
        for p in paths:
            path = Path(p)
            if path not in self.files:
                self.files.append(path)
                self.file_list.insert("end", str(path))

    def remove_selected(self) -> None:
        for idx in reversed(self.file_list.curselection()):
            self.file_list.delete(idx)
            del self.files[idx]

    def clear_files(self) -> None:
        self.files.clear()
        self.file_list.delete(0, "end")

    def refresh_devices(self) -> None:
        devices = list_devices()
        if not devices:
            self.device_combo["values"] = ["(没有检测到设备)"]
            self.device_combo.current(0)
        else:
            self.device_combo["values"] = devices
            self.device_combo.current(0)
        self.log(f"检测到 {len(devices)} 台设备" + (f": {devices}" if devices else ""))

    def clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def log(self, msg: str) -> None:
        self.log_pump.log(msg)

    # --- 安装 ---

    def start_install(self) -> None:
        if self.installing:
            return
        if not self.files:
            messagebox.showwarning("提示", "请先拖入或选择 XAPK 文件。")
            return

        sel = self.device_var.get()
        devices = list_devices()
        if sel not in devices:
            messagebox.showerror("错误", "没有可用设备，请连接手机并刷新。")
            return

        self.installing = True
        self.install_btn.configure(state="disabled", text="安装中…")

        files = list(self.files)
        opts = dict(
            serial=sel,
            keep_data=self.keep_data_var.get(),
            downgrade=self.downgrade_var.get(),
        )

        threading.Thread(
            target=self._run_install,
            args=(files, opts),
            daemon=True,
        ).start()

    def _run_install(self, files: list[Path], opts: dict) -> None:
        try:
            install_many(files, log=self.log, **opts)
        except InstallError as e:
            self.log(f"错误: {e}")
        except Exception as e:  # pragma: no cover - 兜底
            self.log(f"未预期错误: {e!r}")
        finally:
            self.root.after(0, self._on_install_done)

    def _on_install_done(self) -> None:
        self.installing = False
        self.install_btn.configure(state="normal", text="安  装")


# -------- 启动入口 --------

def _run_gui() -> int:
    root = TkinterDnD.Tk() if _DND_OK else tk.Tk()
    try:
        root.tk.call("tk", "scaling", 1.2)
    except tk.TclError:
        pass
    XapkGui(root)
    root.mainloop()
    return 0


def _run_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="安装 XAPK 到 Android 手机")
    parser.add_argument("xapk", nargs="+", help="一个或多个 XAPK 文件路径")
    parser.add_argument("-s", "--serial", help="adb 设备序列号（多设备时必填）")
    parser.add_argument("--keep-data", action="store_true",
                        help="覆盖安装并保留数据（adb install -r）")
    parser.add_argument("--downgrade", action="store_true",
                        help="允许降级安装（adb install -d）")
    args = parser.parse_args(argv)
    try:
        install_many(
            [Path(p) for p in args.xapk],
            serial=args.serial,
            keep_data=args.keep_data,
            downgrade=args.downgrade,
        )
    except InstallError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        return _run_gui()
    return _run_cli(argv)


if __name__ == "__main__":
    sys.exit(main())
