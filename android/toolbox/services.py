from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QSettings, QTimer, Signal

from ..removeGpCheck import gpcheck_core as gp


class Cancelled(Exception):
    pass


@dataclass(frozen=True)
class Device:
    serial: str
    state: str
    model: str = ""

    @property
    def emulator(self):
        return bool(re.fullmatch(r"emulator-\d+", self.serial))


def parse_devices(output: str) -> list[Device]:
    devices = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 2 or parts[1] not in {"device", "offline", "unauthorized", "recovery", "sideload"}:
            continue
        model = next((p[6:].replace("_", " ") for p in parts[2:] if p.startswith("model:")), "")
        devices[parts[0]] = Device(parts[0], parts[1], model)
    return list(devices.values())


class Preferences:
    def __init__(self, root: Path | None = None):
        self.root = root or Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AndroidToolbox"
        self.root.mkdir(parents=True, exist_ok=True)
        self.logs = self.root / "logs"
        self.logs.mkdir(exist_ok=True)
        self.store = QSettings(str(self.root / "settings.ini"), QSettings.Format.IniFormat)

    def get(self, key, default=""):
        return self.store.value(key, default)

    def set(self, key, value):
        self.store.setValue(key, value)
        self.store.sync()

    @property
    def output(self):
        return Path(self.get("output", str(self.root / "workspace")))


class Tools(QObject):
    changed = Signal()
    KEYS = ("adb", "java", "keytool", "apktool", "build_tools")

    def __init__(self, preferences: Preferences):
        super().__init__()
        self.preferences = preferences

    def snapshot(self) -> dict[str, str]:
        root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        runtime = root / "runtime"
        discovered = gp.discover_toolchain(Path(__file__).resolve().parents[1] / "removeGpCheck")
        bundled = {
            "adb": runtime / "platform-tools" / "adb.exe",
            "java": runtime / "jdk" / "bin" / "java.exe",
            "keytool": runtime / "jdk" / "bin" / "keytool.exe",
            "apktool": runtime / "apktool" / "apktool.jar",
            "build_tools": runtime / "build-tools",
        }
        fallback = {"adb": discovered.adb, "java": discovered.java, "keytool": discovered.keytool,
                    "apktool": discovered.apktool_jar, "build_tools": discovered.build_tools}
        values = {}
        for key in self.KEYS:
            explicit = str(self.preferences.get("tools/" + key)).strip()
            candidate = explicit or (str(bundled[key]) if bundled[key].exists() else str(fallback[key]))
            resolved = shutil.which(candidate) if key in {"adb", "java", "keytool"} else None
            values[key] = str(Path(resolved or candidate).resolve()) if candidate not in {"", "."} else ""
        return values

    @staticmethod
    def require(values, *keys):
        missing = []
        for key in keys:
            path = Path(values.get(key, ""))
            valid = path.is_file() if key != "build_tools" else (
                (path / "zipalign.exe").is_file() and (path / "lib" / "apksigner.jar").is_file())
            if not valid:
                missing.append(key)
        if missing:
            raise RuntimeError("缺少可用工具：" + "、".join(missing) + "。请在设置中配置。")

    @staticmethod
    def available(values, *keys):
        try:
            Tools.require(values, *keys)
            return True
        except RuntimeError:
            return False

    @staticmethod
    def chain(values, context, serial=None):
        return gp.Toolchain(java=Path(values["java"]), keytool=Path(values["keytool"]),
                            adb=Path(values["adb"]), apktool_jar=Path(values["apktool"]),
                            build_tools=Path(values["build_tools"]), serial=serial, runner=context.run)


class Devices(QObject):
    changed = Signal(object, str)

    def __init__(self, tools):
        super().__init__()
        self.tools = tools
        self.items = []
        self.error = ""
        self.busy = False
        self.events = queue.Queue()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(100)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh_timer.start(5000)

    def refresh(self):
        if self.busy:
            return
        self.busy = True
        values = self.tools.snapshot()

        def worker():
            try:
                Tools.require(values, "adb")
                result = subprocess.run([values["adb"], "devices", "-l"], capture_output=True,
                                        text=True, encoding="utf-8", errors="replace", timeout=10,
                                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                if result.returncode:
                    raise RuntimeError(result.stderr.strip() or "ADB 设备查询失败")
                self.events.put((parse_devices(result.stdout), ""))
            except Exception as exc:
                self.events.put(([], str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            self.items, self.error = self.events.get_nowait()
        except queue.Empty:
            return
        self.busy = False
        self.changed.emit(self.items, self.error)


@dataclass
class Outcome:
    status: str = "success"
    items: list[dict] = field(default_factory=list)
    output: str = ""
    value: object = None


@dataclass
class Task:
    title: str
    module: str
    operation: Callable | None
    target: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    status: str = "queued"
    message: str = ""
    outcome: Outcome | None = None
    stop: threading.Event = field(default_factory=threading.Event)
    logs: deque = field(default_factory=lambda: deque(maxlen=2000))

    def record(self):
        return {"id": self.id, "title": self.title, "module": self.module, "target": self.target,
                "created": self.created, "status": self.status, "message": self.message,
                "items": self.outcome.items if self.outcome else [],
                "output": self.outcome.output if self.outcome else ""}


class Execution:
    def __init__(self, task: Task, events, log_path: Path):
        self.task = task
        self.events = events
        self.log_path = log_path

    def checkpoint(self):
        if self.task.stop.is_set():
            raise Cancelled("已停止后续步骤；已完成的操作保留。")

    def log(self, message):
        line = f"{datetime.now():%H:%M:%S}  {message}"
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        self.events.put(("log", self.task.id, line))

    def item(self, name, status, detail=""):
        self.events.put(("item", self.task.id, {"name": name, "status": status, "detail": detail}))

    def run(self, command, log=None, cwd=None, check=True, stream_output=True, timeout=600):
        self.checkpoint()
        args = [str(value) for value in command]
        self.log("> " + subprocess.list2cmdline(gp._redact_command(args)))
        process = subprocess.Popen(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace",
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        lines = queue.Queue()

        def read():
            try:
                for line in process.stdout:
                    lines.put(line.rstrip())
            finally:
                lines.put(None)

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        deadline = time.monotonic() + timeout
        output = []
        try:
            while True:
                if time.monotonic() > deadline:
                    raise TimeoutError(f"命令超时（{timeout} 秒）：{Path(args[0]).name}")
                try:
                    line = lines.get(timeout=0.1)
                except queue.Empty:
                    continue
                if line is None:
                    break
                output.append(line)
                if stream_output:
                    self.log(line)
            code = process.wait(timeout=max(0.1, deadline - time.monotonic()))
        finally:
            if process.poll() is None:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                else:
                    process.kill()
                process.wait()
            reader.join(timeout=2)
            process.stdout.close()
        text = "\n".join(output)
        if check and code:
            raise RuntimeError(f"{Path(args[0]).name} 失败（{code}）\n{text[-2500:]}")
        return code, text


class Tasks(QObject):
    changed = Signal()
    finished = Signal(object)

    def __init__(self, preferences):
        super().__init__()
        self.preferences = preferences
        self.tasks = []
        self.events = queue.Queue()
        self.active = None
        self.accepting = True
        self.history_path = preferences.root / "tasks.json"
        try:
            for entry in json.loads(self.history_path.read_text(encoding="utf-8")):
                if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(entry.get("id", ""))):
                    continue
                task = Task(entry["title"], entry["module"], None, entry.get("target", ""))
                for key in ("id", "created", "status", "message"):
                    setattr(task, key, entry.get(key, getattr(task, key)))
                if task.status in {"queued", "running", "stopping"}:
                    task.status, task.message = "interrupted", "上次程序退出时未完成"
                if task.status not in {"success", "partial", "failed", "cancelled", "interrupted"}:
                    task.status, task.message = "interrupted", "无法识别旧任务状态"
                task.outcome = Outcome(task.status, entry.get("items", []), entry.get("output", ""))
                self.tasks.append(task)
        except (OSError, ValueError, TypeError, KeyError):
            self.tasks = []
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(80)

    def submit(self, title, module, operation, target=""):
        if not self.accepting:
            raise RuntimeError("程序正在等待退出")
        task = Task(title, module, operation, target)
        self.tasks.append(task)
        self.save()
        self.changed.emit()
        self.start_next()
        return task

    def save(self):
        completed = [t for t in self.tasks if t.status not in {"queued", "running", "stopping"}]
        for task in completed[:-100]:
            (self.preferences.logs / f"{task.id}.log").unlink(missing_ok=True)
            self.tasks.remove(task)
        temporary = self.history_path.with_suffix(".tmp")
        temporary.write_text(json.dumps([t.record() for t in self.tasks], ensure_ascii=False,
                                        indent=2), encoding="utf-8")
        temporary.replace(self.history_path)

    def start_next(self):
        if self.active:
            return
        task = next((t for t in self.tasks if t.status == "queued"), None)
        if not task:
            return
        self.active = task
        task.status = "running"
        self.save()
        self.changed.emit()

        def worker():
            context = Execution(task, self.events, self.preferences.logs / f"{task.id}.log")
            try:
                context.checkpoint()
                outcome = task.operation(context) or Outcome()
                if not isinstance(outcome, Outcome) or outcome.status not in {"success", "partial", "failed"}:
                    raise ValueError("任务必须返回有效的 Outcome 结果。")
                self.events.put(("done", task.id, (outcome.status, "", outcome)))
            except Cancelled as exc:
                context.log(str(exc))
                self.events.put(("done", task.id, ("cancelled", str(exc), None)))
            except Exception as exc:
                context.log("失败：" + str(exc))
                self.events.put(("done", task.id, ("failed", str(exc), None)))
        threading.Thread(target=worker, daemon=False).start()

    def cancel(self, task):
        if task.status == "queued":
            task.status = "cancelled"
            task.operation = None
            self.finished.emit(task)
        elif task.status == "running":
            task.status = "stopping"
            task.stop.set()
        self.save()
        self.changed.emit()

    def poll(self):
        dirty = False
        for _ in range(300):
            try:
                kind, task_id, value = self.events.get_nowait()
            except queue.Empty:
                break
            task = next(t for t in self.tasks if t.id == task_id)
            if kind == "log":
                task.logs.append(value)
            elif kind == "item":
                if task.outcome is None:
                    task.outcome = Outcome()
                task.outcome.items.append(value)
            else:
                task.status, task.message, outcome = value
                if outcome:
                    task.outcome = outcome
                task.operation = None
                self.active = None
                self.save()
                self.finished.emit(task)
            dirty = True
        if dirty:
            self.changed.emit()
        self.start_next()

    def clear_completed(self):
        for task in list(self.tasks):
            if task.status not in {"queued", "running", "stopping"}:
                (self.preferences.logs / f"{task.id}.log").unlink(missing_ok=True)
                self.tasks.remove(task)
        self.save()
        self.changed.emit()


class AppContext:
    def __init__(self, root=None):
        self.preferences = Preferences(root)
        self.tools = Tools(self.preferences)
        self.devices = Devices(self.tools)
        self.tasks = Tasks(self.preferences)
        self.selected_serial = ""

    def target(self):
        if not any(d.serial == self.selected_serial and d.state == "device" for d in self.devices.items):
            raise RuntimeError("请选择已连接并授权的目标设备。")
        return self.selected_serial
