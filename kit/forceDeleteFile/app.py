"""Tk desktop interface for ForceDeleteFile."""

from __future__ import annotations

import ctypes
import os
import queue
import sys
import threading
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
import tkinter as tk
from tkinter import ttk
from typing import Sequence

try:
    from tkinterdnd2 import COPY, DND_FILES, TkinterDnD

    DND_AVAILABLE = True
except ImportError:
    COPY = "copy"
    DND_FILES = "DND_Files"
    TkinterDnD = None
    DND_AVAILABLE = False

try:
    from .delete_service import DeleteResult, DeleteStatus, ForceDeleteService
    from .windows_lock import LockingProcess, is_current_process_elevated
except ImportError:  # Allow `python app.py`.
    from delete_service import DeleteResult, DeleteStatus, ForceDeleteService
    from windows_lock import LockingProcess, is_current_process_elevated


BG = "#f4f5f7"
SURFACE = "#ffffff"
BORDER = "#d7dbe0"
TEXT = "#1f2328"
MUTED = "#66707a"
DANGER = "#b42318"
DANGER_ACTIVE = "#8f1d14"
SUCCESS = "#18794e"
WARNING = "#9a6700"


STATUS_TEXT = {
    DeleteStatus.DELETED: "已删除",
    DeleteStatus.NOT_FOUND: "不存在",
    DeleteStatus.SCHEDULED: "等待重启",
    DeleteStatus.FAILED: "失败",
    DeleteStatus.CANCELLED: "已取消",
}


@dataclass(slots=True)
class LogEvent:
    level: str
    message: str


@dataclass(slots=True)
class ItemStatusEvent:
    path: Path
    status: str


@dataclass(slots=True)
class ResultEvent:
    result: DeleteResult


@dataclass(slots=True)
class LockPromptEvent:
    path: Path
    processes: tuple[LockingProcess, ...]
    ready: threading.Event = field(default_factory=threading.Event)
    approved: bool = False


@dataclass(slots=True)
class FinishedEvent:
    results: tuple[DeleteResult, ...]


class ForceDeleteApp:
    def __init__(self, root: tk.Tk, initial_paths: Sequence[str] = ()) -> None:
        self.root = root
        self.events: queue.Queue[object] = queue.Queue()
        self.cancel_event = threading.Event()
        self.running = False
        self.rows: dict[str, str] = {}

        self.schedule_on_reboot = tk.BooleanVar(value=True)
        self.summary_text = tk.StringVar(value="0 个文件")
        self.activity_text = tk.StringVar(value="就绪")
        self.admin_text = tk.StringVar(
            value="管理员模式" if is_current_process_elevated() else "普通权限"
        )

        self._configure_window()
        self._configure_styles()
        self._build_ui()
        self._register_drop_target()
        self.add_paths(initial_paths)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(80, self._drain_events)

    def _configure_window(self) -> None:
        self.root.title("ForceDelete File")
        self.root.geometry("980x720")
        self.root.minsize(760, 560)
        self.root.configure(bg=BG)
        self.root.option_add("*Font", ("Microsoft YaHei UI", 10))

        self.root.update_idletasks()
        width, height = 980, 720
        x = max((self.root.winfo_screenwidth() - width) // 2, 0)
        y = max((self.root.winfo_screenheight() - height) // 2, 0)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        available = style.theme_names()
        if "vista" in available:
            style.theme_use("vista")
        elif "clam" in available:
            style.theme_use("clam")

        style.configure("TFrame", background=BG)
        style.configure("Surface.TFrame", background=SURFACE)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Surface.TLabel", background=SURFACE, foreground=TEXT)
        style.configure(
            "Title.TLabel",
            background=BG,
            foreground=TEXT,
            font=("Microsoft YaHei UI", 17, "bold"),
        )
        style.configure(
            "Muted.TLabel", background=BG, foreground=MUTED, font=("Microsoft YaHei UI", 9)
        )
        style.configure(
            "SurfaceMuted.TLabel",
            background=SURFACE,
            foreground=MUTED,
            font=("Microsoft YaHei UI", 9),
        )
        style.configure("Treeview", rowheight=28, background=SURFACE, fieldbackground=SURFACE)
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"))

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=(24, 18, 24, 20))
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 14))
        ttk.Label(header, text="ForceDelete File", style="Title.TLabel").pack(side="left")
        ttk.Label(header, textvariable=self.admin_text, style="Muted.TLabel").pack(
            side="right", pady=(6, 0)
        )

        toolbar = ttk.Frame(outer)
        toolbar.pack(fill="x", pady=(0, 10))
        self.add_button = ttk.Button(toolbar, text="添加文件", command=self._choose_files)
        self.add_button.pack(side="left")
        self.remove_button = ttk.Button(
            toolbar, text="移除所选", command=self._remove_selected
        )
        self.remove_button.pack(side="left", padx=(8, 0))
        self.clear_button = ttk.Button(toolbar, text="清空列表", command=self._clear_files)
        self.clear_button.pack(side="left", padx=(8, 0))
        ttk.Label(toolbar, textvariable=self.summary_text, style="Muted.TLabel").pack(
            side="right", pady=(5, 0)
        )

        self.drop_area = tk.Label(
            outer,
            text="拖放文件",
            height=3,
            bg=SURFACE,
            fg=MUTED,
            bd=1,
            relief="solid",
            highlightthickness=0,
            font=("Microsoft YaHei UI", 11),
        )
        self.drop_area.pack(fill="x", pady=(0, 10))

        table_frame = ttk.Frame(outer, style="Surface.TFrame")
        table_frame.pack(fill="both", expand=True)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            table_frame,
            columns=("name", "status", "path"),
            show="headings",
            selectmode="extended",
        )
        self.tree.heading("name", text="文件")
        self.tree.heading("status", text="状态")
        self.tree.heading("path", text="路径")
        self.tree.column("name", width=210, minwidth=120, stretch=False)
        self.tree.column("status", width=100, minwidth=90, anchor="center", stretch=False)
        self.tree.column("path", width=600, minwidth=260)

        tree_y = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        tree_x = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=tree_y.set, xscrollcommand=tree_x.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        tree_y.grid(row=0, column=1, sticky="ns")
        tree_x.grid(row=1, column=0, sticky="ew")

        options = ttk.Frame(outer)
        options.pack(fill="x", pady=(12, 10))
        self.reboot_check = ttk.Checkbutton(
            options,
            text="无法立即删除时，安排在重启后删除",
            variable=self.schedule_on_reboot,
        )
        self.reboot_check.pack(side="left")

        self.progress = ttk.Progressbar(options, mode="indeterminate", length=150)
        self.progress.pack(side="right", padx=(10, 0))
        ttk.Label(options, textvariable=self.activity_text, style="Muted.TLabel").pack(
            side="right"
        )

        action_bar = ttk.Frame(outer)
        action_bar.pack(fill="x", pady=(0, 12))
        self.delete_button = tk.Button(
            action_bar,
            text="强制删除",
            command=self._start_delete,
            bg=DANGER,
            activebackground=DANGER_ACTIVE,
            fg="white",
            activeforeground="white",
            relief="flat",
            bd=0,
            padx=22,
            pady=8,
            cursor="hand2",
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        self.delete_button.pack(side="right")
        self.stop_button = ttk.Button(
            action_bar, text="停止", command=self._request_stop, state="disabled"
        )
        self.stop_button.pack(side="right", padx=(0, 8))

        log_header = ttk.Frame(outer)
        log_header.pack(fill="x")
        ttk.Label(log_header, text="日志").pack(side="left")
        ttk.Button(log_header, text="清空日志", command=self._clear_log).pack(side="right")

        log_frame = ttk.Frame(outer, style="Surface.TFrame")
        log_frame.pack(fill="x", pady=(6, 0))
        self.log = tk.Text(
            log_frame,
            height=8,
            wrap="word",
            state="disabled",
            bg=SURFACE,
            fg=TEXT,
            insertbackground=TEXT,
            bd=1,
            relief="solid",
            highlightthickness=0,
            padx=10,
            pady=8,
            font=("Cascadia Mono", 9),
        )
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=log_scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

        self.log.tag_configure("INFO", foreground="#3b4856")
        self.log.tag_configure("WARNING", foreground=WARNING)
        self.log.tag_configure("ERROR", foreground=DANGER)
        self.log.tag_configure("SUCCESS", foreground=SUCCESS)

    def _register_drop_target(self) -> None:
        if not DND_AVAILABLE:
            self._append_log("WARNING", "未安装 tkinterdnd2，拖放不可用")
            self.drop_area.configure(text="添加文件")
            return

        for widget in (self.drop_area, self.tree):
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)
            widget.dnd_bind("<<DropEnter>>", self._on_drop_enter)
            widget.dnd_bind("<<DropLeave>>", self._on_drop_leave)

    def _on_drop_enter(self, _event) -> str:
        self.drop_area.configure(bg="#eef3f8", fg=TEXT)
        return COPY

    def _on_drop_leave(self, _event) -> str:
        self.drop_area.configure(bg=SURFACE, fg=MUTED)
        return COPY

    def _on_drop(self, event) -> str:
        self.drop_area.configure(bg=SURFACE, fg=MUTED)
        paths = self.root.tk.splitlist(event.data)
        self.add_paths(paths)
        return COPY

    @staticmethod
    def _path_key(path: Path) -> str:
        return os.path.normcase(os.path.abspath(path))

    def add_paths(self, raw_paths: Sequence[str]) -> None:
        added = 0
        for raw_path in raw_paths:
            path = Path(raw_path).expanduser().absolute()
            if not os.path.lexists(path):
                self._append_log("WARNING", f"文件不存在，未添加: {path}")
                continue
            if path.is_dir() and not path.is_symlink():
                self._append_log("WARNING", f"暂不支持文件夹，未添加: {path}")
                continue

            key = self._path_key(path)
            if key in self.rows:
                continue
            item_id = self.tree.insert(
                "", "end", values=(path.name, "等待", str(path))
            )
            self.rows[key] = item_id
            added += 1

        if added:
            self._append_log("INFO", f"已添加 {added} 个文件")
        self._update_summary()

    def _choose_files(self) -> None:
        paths = filedialog.askopenfilenames(parent=self.root, title="选择要删除的文件")
        if paths:
            self.add_paths(paths)

    def _remove_selected(self) -> None:
        if self.running:
            return
        selected = self.tree.selection()
        for item_id in selected:
            values = self.tree.item(item_id, "values")
            if values:
                self.rows.pop(self._path_key(Path(values[2])), None)
            self.tree.delete(item_id)
        self._update_summary()

    def _clear_files(self) -> None:
        if self.running:
            return
        for item_id in self.tree.get_children():
            self.tree.delete(item_id)
        self.rows.clear()
        self._update_summary()

    def _listed_paths(self) -> tuple[Path, ...]:
        paths: list[Path] = []
        for item_id in self.tree.get_children():
            values = self.tree.item(item_id, "values")
            if values:
                paths.append(Path(values[2]))
        return tuple(paths)

    def _update_summary(self) -> None:
        self.summary_text.set(f"{len(self.tree.get_children())} 个文件")

    def _set_controls_running(self, running: bool) -> None:
        self.running = running
        normal_state = "disabled" if running else "normal"
        for button in (self.add_button, self.remove_button, self.clear_button):
            button.configure(state=normal_state)
        self.reboot_check.configure(state=normal_state)
        self.delete_button.configure(state=normal_state)
        self.stop_button.configure(state="normal" if running else "disabled")
        if running:
            self.progress.start(12)
        else:
            self.progress.stop()

    def _start_delete(self) -> None:
        paths = self._listed_paths()
        if not paths:
            messagebox.showinfo("ForceDelete File", "请先添加文件。", parent=self.root)
            return

        confirmed = messagebox.askyesno(
            "确认永久删除",
            f"即将永久删除 {len(paths)} 个文件。\n\n"
            "此操作不经过回收站，无法撤销。是否继续？",
            icon="warning",
            parent=self.root,
        )
        if not confirmed:
            return

        self.cancel_event.clear()
        self._set_controls_running(True)
        self.activity_text.set("正在处理")
        schedule_on_reboot = self.schedule_on_reboot.get()

        for path in paths:
            self._set_item_status(path, "排队中")

        worker = threading.Thread(
            target=self._delete_worker,
            args=(paths, schedule_on_reboot),
            daemon=True,
            name="force-delete-worker",
        )
        worker.start()

    def _delete_worker(
        self,
        paths: Sequence[Path],
        schedule_on_reboot: bool,
    ) -> None:
        service = ForceDeleteService(
            lambda level, message: self.events.put(LogEvent(level, message))
        )
        results: list[DeleteResult] = []
        for path in paths:
            if self.cancel_event.is_set():
                result = DeleteResult(path, DeleteStatus.CANCELLED, "操作已取消")
            else:
                self.events.put(ItemStatusEvent(path, "处理中"))
                try:
                    result = service.delete(
                        path,
                        confirm_close=self._request_lock_close,
                        schedule_on_reboot=schedule_on_reboot,
                        cancelled=self.cancel_event.is_set,
                    )
                except Exception as error:
                    self.events.put(
                        LogEvent("ERROR", f"处理文件时发生意外错误: {error}")
                    )
                    result = DeleteResult(
                        path,
                        DeleteStatus.FAILED,
                        f"意外错误: {error}",
                        error=error,
                    )
            results.append(result)
            self.events.put(ResultEvent(result))
        self.events.put(FinishedEvent(tuple(results)))

    def _request_lock_close(
        self,
        path: Path,
        processes: Sequence[LockingProcess],
    ) -> bool:
        event = LockPromptEvent(path, tuple(processes))
        self.events.put(event)
        while not event.ready.wait(0.1):
            if self.cancel_event.is_set():
                return False
        return event.approved

    def _handle_lock_prompt(self, event: LockPromptEvent) -> None:
        unsafe = tuple(
            process for process in event.processes if process.is_unsafe_to_shutdown
        )
        lines = [
            f"{process.display_name}  |  PID {process.pid}  |  {process.type_name}"
            for process in event.processes[:12]
        ]
        if len(event.processes) > 12:
            lines.append(f"另有 {len(event.processes) - 12} 个程序")

        if unsafe:
            messagebox.showwarning(
                "无法安全关闭占用者",
                f"文件：\n{event.path}\n\n占用程序：\n"
                + "\n".join(lines)
                + "\n\n检测到系统关键进程或本程序，不会强制关闭。",
                parent=self.root,
            )
            event.approved = False
        else:
            event.approved = messagebox.askyesno(
                "文件正在使用",
                f"文件：\n{event.path}\n\n占用程序：\n"
                + "\n".join(lines)
                + "\n\n关闭这些程序可能丢失未保存的数据。是否继续？",
                icon="warning",
                parent=self.root,
            )
        event.ready.set()

    def _set_item_status(self, path: Path, status: str) -> None:
        item_id = self.rows.get(self._path_key(path))
        if not item_id or not self.tree.exists(item_id):
            return
        values = list(self.tree.item(item_id, "values"))
        values[1] = status
        self.tree.item(item_id, values=values)

    def _handle_result(self, result: DeleteResult) -> None:
        self._set_item_status(result.path, STATUS_TEXT[result.status])

    def _handle_finished(self, event: FinishedEvent) -> None:
        self._set_controls_running(False)
        counts = Counter(result.status for result in event.results)
        deleted = counts[DeleteStatus.DELETED]
        scheduled = counts[DeleteStatus.SCHEDULED]
        failed = counts[DeleteStatus.FAILED]
        cancelled = counts[DeleteStatus.CANCELLED]
        self.activity_text.set(
            f"完成：删除 {deleted}，重启处理 {scheduled}，失败 {failed}，取消 {cancelled}"
        )

    def _drain_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                if isinstance(event, LogEvent):
                    self._append_log(event.level, event.message)
                elif isinstance(event, ItemStatusEvent):
                    self._set_item_status(event.path, event.status)
                elif isinstance(event, ResultEvent):
                    self._handle_result(event.result)
                elif isinstance(event, LockPromptEvent):
                    self._handle_lock_prompt(event)
                elif isinstance(event, FinishedEvent):
                    self._handle_finished(event)
        except queue.Empty:
            pass
        if self.root.winfo_exists():
            self.root.after(80, self._drain_events)

    def _append_log(self, level: str, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log.configure(state="normal")
        self.log.insert("end", f"{timestamp} [{level}] {message}\n", level)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _request_stop(self) -> None:
        if self.running:
            self.cancel_event.set()
            self.activity_text.set("正在停止")
            self._append_log("WARNING", "已请求停止，将在当前步骤完成后生效")

    def _on_close(self) -> None:
        if self.running and not messagebox.askyesno(
            "退出",
            "删除任务仍在运行，是否停止任务并退出？",
            icon="warning",
            parent=self.root,
        ):
            return
        self.cancel_event.set()
        self.root.destroy()


def _enable_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


def main(initial_paths: Sequence[str] | None = None) -> None:
    _enable_dpi_awareness()
    paths = tuple(initial_paths if initial_paths is not None else sys.argv[1:])
    root = TkinterDnD.Tk() if DND_AVAILABLE else tk.Tk()
    ForceDeleteApp(root, paths)
    root.mainloop()


if __name__ == "__main__":
    main()
