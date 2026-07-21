from __future__ import annotations

import os
import queue
import threading
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    RootWindow = TkinterDnD.Tk
    HAS_DND = True
except ImportError:
    DND_FILES = None
    RootWindow = tk.Tk
    HAS_DND = False

from gpcheck_core import (
    AnalysisResult,
    BuildResult,
    GpCheckError,
    Toolchain,
    analyze_xapk,
    build_patched_xapk,
    discover_toolchain,
    install_and_verify,
)


APP_ROOT = Path(__file__).resolve().parent


class PairIpLabApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("XAPK PairIP Lab")
        self.root.geometry("1080x780")
        self.root.minsize(920, 680)

        self.analysis: AnalysisResult | None = None
        self.build_result: BuildResult | None = None
        self.busy = False
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()

        discovered = discover_toolchain(APP_ROOT)
        self.xapk_var = tk.StringVar()
        self.workspace_var = tk.StringVar(value=str(APP_ROOT / "workspace"))
        self.apktool_var = tk.StringVar(value=str(discovered.apktool_jar))
        self.build_tools_var = tk.StringVar(value=str(discovered.build_tools))
        self.keystore_var = tk.StringVar(value=str(APP_ROOT / "lab-signing.jks"))
        self.alias_var = tk.StringVar(value="android-lab")
        self.password_var = tk.StringVar(value="android")
        self.status_var = tk.StringVar(value="就绪")
        self.grant_permissions_var = tk.BooleanVar(value=True)

        self._configure_style()
        self._build_ui()
        self._configure_drop()
        self.root.after(100, self._poll_events)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure("Subtle.TLabel", foreground="#5f6368")
        style.configure("Status.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), padding=(14, 8))
        style.configure("TButton", padding=(10, 6))
        style.configure("Treeview", rowheight=25)
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=1)

        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="XAPK PairIP Lab", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(header, textvariable=self.status_var, style="Status.TLabel").grid(
            row=0, column=1, sticky="e"
        )

        source = ttk.LabelFrame(outer, text="样本", padding=10)
        source.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        source.columnconfigure(0, weight=1)
        self.xapk_entry = ttk.Entry(source, textvariable=self.xapk_var)
        self.xapk_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(source, text="选择 XAPK", command=self._select_xapk).grid(row=0, column=1)
        self.analyze_button = ttk.Button(
            source,
            text="分析",
            style="Primary.TButton",
            command=self._start_analysis,
        )
        self.analyze_button.grid(row=0, column=2, padx=(8, 0))

        settings = ttk.LabelFrame(outer, text="工具链与输出", padding=10)
        settings.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        settings.columnconfigure(1, weight=1)
        settings.columnconfigure(3, weight=1)

        self._path_row(settings, 0, "工作目录", self.workspace_var, self._select_workspace)
        self._path_row(settings, 1, "Apktool JAR", self.apktool_var, self._select_apktool)
        self._path_row(settings, 2, "Build Tools", self.build_tools_var, self._select_build_tools)
        self._path_row(settings, 3, "实验密钥", self.keystore_var, self._select_keystore)

        ttk.Label(settings, text="别名").grid(row=4, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(settings, textvariable=self.alias_var, width=24).grid(
            row=4, column=1, sticky="w", pady=(6, 0)
        )
        ttk.Label(settings, text="密码").grid(row=4, column=2, sticky="w", padx=(16, 6), pady=(6, 0))
        ttk.Entry(settings, textvariable=self.password_var, show="*", width=24).grid(
            row=4, column=3, sticky="w", pady=(6, 0)
        )

        body = ttk.Panedwindow(outer, orient=tk.HORIZONTAL)
        body.grid(row=3, column=0, sticky="nsew")

        result_panel = ttk.Frame(body, padding=(0, 0, 8, 0))
        log_panel = ttk.Frame(body, padding=(8, 0, 0, 0))
        body.add(result_panel, weight=5)
        body.add(log_panel, weight=6)
        result_panel.rowconfigure(0, weight=1)
        result_panel.columnconfigure(0, weight=1)
        log_panel.rowconfigure(1, weight=1)
        log_panel.columnconfigure(0, weight=1)

        self.result_tree = ttk.Treeview(
            result_panel,
            columns=("field", "value"),
            show="headings",
            selectmode="browse",
        )
        self.result_tree.heading("field", text="字段")
        self.result_tree.heading("value", text="检测结果")
        self.result_tree.column("field", width=145, stretch=False)
        self.result_tree.column("value", width=390, stretch=True)
        self.result_tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll = ttk.Scrollbar(result_panel, orient=tk.VERTICAL, command=self.result_tree.yview)
        tree_scroll.grid(row=0, column=1, sticky="ns")
        self.result_tree.configure(yscrollcommand=tree_scroll.set)

        actions_frame = ttk.LabelFrame(result_panel, text="拟执行修改", padding=8)
        actions_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        actions_frame.columnconfigure(0, weight=1)
        self.actions_text = tk.Text(
            actions_frame,
            height=6,
            wrap=tk.WORD,
            state=tk.DISABLED,
            background="#ffffff",
            relief=tk.FLAT,
            font=("Consolas", 9),
        )
        self.actions_text.grid(row=0, column=0, sticky="ew")

        ttk.Label(log_panel, text="执行日志", style="Subtle.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        self.log_text = ScrolledText(
            log_panel,
            wrap=tk.WORD,
            state=tk.DISABLED,
            background="#111827",
            foreground="#e5e7eb",
            insertbackground="#ffffff",
            font=("Consolas", 9),
            relief=tk.FLAT,
        )
        self.log_text.grid(row=1, column=0, sticky="nsew")

        footer = ttk.Frame(outer)
        footer.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        footer.columnconfigure(3, weight=1)
        self.build_button = ttk.Button(
            footer,
            text="构建实验版 XAPK",
            style="Primary.TButton",
            command=self._start_build,
            state=tk.DISABLED,
        )
        self.build_button.grid(row=0, column=0, padx=(0, 8))
        self.install_button = ttk.Button(
            footer,
            text="安装并验证",
            command=self._start_install,
            state=tk.DISABLED,
        )
        self.install_button.grid(row=0, column=1, padx=(0, 8))
        self.open_button = ttk.Button(
            footer,
            text="打开输出目录",
            command=self._open_output,
            state=tk.DISABLED,
        )
        self.open_button.grid(row=0, column=2)
        ttk.Checkbutton(
            footer,
            text="安装后配置清理权限",
            variable=self.grant_permissions_var,
        ).grid(row=0, column=4, sticky="e", padx=(12, 10))
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=150)
        self.progress.grid(row=0, column=5, sticky="e")

        ttk.Label(
            outer,
            text="仅用于已授权样本；未知模式只分析，不自动修改。",
            style="Subtle.TLabel",
        ).grid(row=5, column=0, sticky="w", pady=(8, 0))

    def _path_row(
        self,
        parent: ttk.LabelFrame,
        row: int,
        label: str,
        variable: tk.StringVar,
        browse_command,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(parent, textvariable=variable).grid(
            row=row, column=1, columnspan=3, sticky="ew", padx=(8, 8), pady=3
        )
        ttk.Button(parent, text="浏览", command=browse_command, width=8).grid(
            row=row, column=4, pady=3
        )

    def _configure_drop(self) -> None:
        if not HAS_DND:
            self._append_log("tkinterdnd2 未安装，仍可使用“选择 XAPK”按钮。")
            return
        for widget in (self.root, self.xapk_entry):
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)

    def _on_drop(self, event) -> None:
        paths = self.root.tk.splitlist(event.data)
        if not paths:
            return
        path = Path(paths[0])
        if path.suffix.lower() != ".xapk":
            messagebox.showerror("文件类型", "请选择 .xapk 文件。")
            return
        self.xapk_var.set(str(path))
        self._start_analysis()

    def _select_xapk(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 XAPK",
            filetypes=[("XAPK", "*.xapk"), ("All files", "*.*")],
        )
        if path:
            self.xapk_var.set(path)

    def _select_workspace(self) -> None:
        path = filedialog.askdirectory(title="选择工作目录")
        if path:
            self.workspace_var.set(path)

    def _select_apktool(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 Apktool JAR",
            filetypes=[("JAR", "*.jar"), ("All files", "*.*")],
        )
        if path:
            self.apktool_var.set(path)

    def _select_build_tools(self) -> None:
        path = filedialog.askdirectory(title="选择 Android Build Tools 目录")
        if path:
            self.build_tools_var.set(path)

    def _select_keystore(self) -> None:
        path = filedialog.asksaveasfilename(
            title="选择或创建实验密钥",
            defaultextension=".jks",
            filetypes=[("Java KeyStore", "*.jks *.keystore"), ("All files", "*.*")],
        )
        if path:
            self.keystore_var.set(path)

    def _toolchain(self) -> Toolchain:
        discovered = discover_toolchain(APP_ROOT)
        return Toolchain(
            java=discovered.java,
            keytool=discovered.keytool,
            adb=discovered.adb,
            apktool_jar=Path(self.apktool_var.get().strip()),
            build_tools=Path(self.build_tools_var.get().strip()),
        )

    def _start_analysis(self) -> None:
        if self.busy:
            return
        xapk = Path(self.xapk_var.get().strip())
        workspace = Path(self.workspace_var.get().strip())
        self.analysis = None
        self.build_result = None
        self._clear_results()
        self._run_async(
            "正在分析",
            lambda: analyze_xapk(xapk, workspace, self._toolchain(), self._thread_log),
            self._analysis_complete,
        )

    def _analysis_complete(self, result: AnalysisResult) -> None:
        self.analysis = result
        self.build_result = None
        self._show_analysis(result)
        self.build_button.configure(state=tk.NORMAL if result.supported else tk.DISABLED)
        self.install_button.configure(state=tk.DISABLED)
        self.open_button.configure(state=tk.NORMAL)

    def _start_build(self) -> None:
        if self.busy or not self.analysis:
            return
        analysis = self.analysis
        keystore = Path(self.keystore_var.get().strip())
        alias = self.alias_var.get().strip()
        password = self.password_var.get()
        if not alias or not password:
            messagebox.showerror("签名参数", "密钥别名和密码不能为空。")
            return
        actions = "\n".join(f"- {item.description}" for item in analysis.actions)
        if not messagebox.askyesno(
            "确认构建",
            f"将对工作副本执行以下修改：\n\n{actions}\n\n原始 XAPK 不会被覆盖。",
        ):
            return
        self._run_async(
            "正在构建",
            lambda: build_patched_xapk(
                analysis,
                self._toolchain(),
                keystore,
                alias,
                password,
                self._thread_log,
            ),
            self._build_complete,
        )

    def _build_complete(self, result: BuildResult) -> None:
        self.build_result = result
        self.build_button.configure(state=tk.DISABLED)
        self.install_button.configure(state=tk.NORMAL)
        self.open_button.configure(state=tk.NORMAL)
        self._append_log(f"证书 SHA-256: {result.certificate_sha256}")
        self._append_log(f"实验版 XAPK: {result.patched_xapk}")
        messagebox.showinfo("构建完成", f"实验版已生成：\n{result.patched_xapk}")

    def _start_install(self) -> None:
        if self.busy or not self.analysis or not self.build_result:
            return
        if not messagebox.askyesno(
            "确认安装",
            "将使用 adb 覆盖安装同签名版本。不同签名的已安装版本不会被自动卸载。继续吗？",
        ):
            return
        analysis = self.analysis
        build = self.build_result
        self._run_async(
            "正在安装并验证",
            lambda: install_and_verify(
                analysis,
                build,
                self._toolchain(),
                self.grant_permissions_var.get(),
                self._thread_log,
            ),
            self._install_complete,
        )

    def _install_complete(self, result) -> None:
        selected = ", ".join(path.name for path in result.selected_apks)
        self._append_log(f"设备安装集: {selected}")
        self._append_log(f"PID: {result.pid or 'none'}")
        self._append_log(f"前台窗口: {result.foreground or 'none'}")
        if result.screenshot:
            self._append_log(f"启动截图: {result.screenshot}")
        if result.success:
            messagebox.showinfo("验证通过", "应用进程和前台窗口正常，未发现 PairIP 或崩溃日志。")
        else:
            messagebox.showwarning("需要复核", "安装完成，但动态验证未全部通过。请查看执行日志。")

    def _open_output(self) -> None:
        path: Path | None = None
        if self.build_result:
            path = self.build_result.output_dir
        elif self.analysis:
            path = self.analysis.workspace
        if path and path.exists():
            os.startfile(path)

    def _show_analysis(self, result: AnalysisResult) -> None:
        pattern = []
        if result.application_name == "com.pairip.application.Application":
            pattern.append("Application 包装型")
        if result.provider_found:
            pattern.append("Provider 自动初始化型")
        rows = [
            ("应用", result.app_name),
            ("包名", result.package_name),
            ("版本", f"{result.version_name} ({result.version_code})"),
            ("启动 Activity", result.main_activity or "未找到"),
            ("Application", result.application_name or "默认"),
            ("业务 Application", result.original_application_name or "不适用/未识别"),
            ("PairIP Provider", "存在" if result.provider_found else "未发现"),
            ("PairIP Activity", "存在" if result.pairip_activity_found else "未发现"),
            ("模式", " + ".join(pattern) if pattern else "未知"),
            ("置信度", result.confidence),
            ("可自动处理", "是" if result.supported else "否"),
            ("XAPK SHA-256", result.xapk_sha256),
            ("工作目录", str(result.workspace)),
        ]
        for field, value in rows:
            self.result_tree.insert("", tk.END, values=(field, value))

        lines = [item.description for item in result.actions]
        if result.evidence:
            lines.append("")
            lines.extend(f"证据: {item}" for item in result.evidence)
        self._set_actions("\n".join(lines) if lines else "没有可自动执行的修改。")

    def _clear_results(self) -> None:
        for item in self.result_tree.get_children():
            self.result_tree.delete(item)
        self._set_actions("")
        self.build_button.configure(state=tk.DISABLED)
        self.install_button.configure(state=tk.DISABLED)
        self.open_button.configure(state=tk.DISABLED)

    def _set_actions(self, text: str) -> None:
        self.actions_text.configure(state=tk.NORMAL)
        self.actions_text.delete("1.0", tk.END)
        self.actions_text.insert(tk.END, text)
        self.actions_text.configure(state=tk.DISABLED)

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, message.rstrip() + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _thread_log(self, message: str) -> None:
        self.events.put(("log", message))

    def _run_async(self, label: str, operation, on_success) -> None:
        self.busy = True
        self.status_var.set(label)
        self.progress.start(12)
        self._set_controls_busy(True)

        def worker() -> None:
            try:
                value = operation()
                self.events.put(("success", (value, on_success)))
            except Exception as exc:
                self.events.put(("error", (exc, traceback.format_exc())))

        threading.Thread(target=worker, daemon=True).start()

    def _set_controls_busy(self, busy: bool) -> None:
        self.analyze_button.configure(state=tk.DISABLED if busy else tk.NORMAL)
        if busy:
            self.build_button.configure(state=tk.DISABLED)
            self.install_button.configure(state=tk.DISABLED)

    def _finish_task(self) -> None:
        self.busy = False
        self.status_var.set("就绪")
        self.progress.stop()
        self._set_controls_busy(False)
        if self.analysis and self.analysis.supported:
            self.build_button.configure(state=tk.NORMAL if not self.build_result else tk.DISABLED)
        if self.build_result:
            self.install_button.configure(state=tk.NORMAL)

    def _poll_events(self) -> None:
        try:
            while True:
                event_type, payload = self.events.get_nowait()
                if event_type == "log":
                    self._append_log(str(payload))
                elif event_type == "success":
                    value, callback = payload
                    self._finish_task()
                    callback(value)
                elif event_type == "error":
                    exc, trace = payload
                    self._finish_task()
                    self._append_log(trace)
                    title = "处理失败"
                    message = str(exc)
                    if isinstance(exc, GpCheckError):
                        title = "无法继续"
                    messagebox.showerror(title, message)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)


def main() -> None:
    root = RootWindow()
    PairIpLabApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
