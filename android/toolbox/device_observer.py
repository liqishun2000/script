"""Read-only device observations and shared, bounded polling sessions."""
from __future__ import annotations

import os
import queue
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, QTimer, Signal


@dataclass(frozen=True)
class Observation:
    serial: str
    kind: str
    timestamp: float
    rows: tuple[tuple[str, str], ...]
    raw: str


def match(pattern, text, default="未提供"):
    found = re.search(pattern, text, re.MULTILINE)
    return found.group(1).strip() if found else default


def parse_details(raw: dict[str, str]):
    props = dict(re.findall(r"^\[([^]]+)\]: \[(.*)\]$", raw.get("属性", ""), re.MULTILINE))
    rows = [(label, props.get(key) or "未提供") for label, key in (
        ("制造商", "ro.product.manufacturer"), ("型号", "ro.product.model"),
        ("设备代号", "ro.product.device"), ("Android", "ro.build.version.release"),
        ("API", "ro.build.version.sdk"), ("安全补丁", "ro.build.version.security_patch"),
        ("系统版本", "ro.build.display.id"), ("ABI", "ro.product.cpu.abilist"),
        ("芯片", "ro.hardware"))]
    memory = raw.get("内存", "")
    for label, key in (("总内存", "MemTotal"), ("可用内存", "MemAvailable"), ("交换空间", "SwapTotal")):
        kb = match(rf"^{key}:\s+(\d+) kB", memory, "")
        rows.append((label, f"{int(kb) / 1048576:.2f} GiB" if kb else "未提供"))
    cpu = raw.get("CPU", "").strip()
    rows.append(("在线 CPU", cpu or "未提供"))
    for label in ("分辨率", "密度", "存储"):
        rows.append((label, raw.get(label, "未提供").strip()))
    uptime = match(r"^(\d+(?:\.\d+)?)", raw.get("运行时间", ""), "")
    rows.append(("运行时间", f"{float(uptime) / 3600:.1f} 小时" if uptime else "未提供"))
    battery = raw.get("电池", "")
    level = match(r"^\s*level:\s*(\d+)", battery, "")
    scale = match(r"^\s*scale:\s*(\d+)", battery, "")
    rows.append(("电量", f"{int(level) / int(scale):.0%}" if level and scale and int(scale) else "未提供"))
    temp = match(r"^\s*temperature:\s*(-?\d+)", battery, "")
    rows.append(("电池温度", f"{int(temp) / 10:.1f} °C" if temp else "未提供"))
    rows.append(("供电", " / ".join(k for k in ("AC", "USB", "Wireless")
                                     if re.search(rf"{k} powered: true", battery)) or "电池 / 未提供"))
    rows.append(("Shell 身份", raw.get("权限", "未提供").strip()))
    return rows


def parse_foreground(raw: dict[str, str]):
    activity = raw.get("Activity", "")
    windows = raw.get("Window", "")
    component = match(r"(?:mResumedActivity|topResumedActivity|mFocusedActivity)[^\n]*?\s([\w.$]+/[\w.$]+)", activity)
    focus = match(r"mCurrentFocus=(.*)", windows)
    focused_app = match(r"mFocusedApp=(.*)", windows)
    display = match(r"mTopFocusedDisplayId=(\d+)", windows)
    focused_block = ""
    for block in re.split(r"(?=^\s*Window #\d+ )", windows, flags=re.MULTILINE):
        if focus.startswith("Window{") and re.match(r"\s*Window #\d+ " + re.escape(focus) + r":", block):
            focused_block = block
            break
    display = match(r"mDisplayId=(\d+)", focused_block, display)
    return [("前台包名", component.split("/", 1)[0] if "/" in component else "未提供"),
            ("Activity", component), ("焦点 Window", focus), ("焦点应用", focused_app),
            ("焦点显示屏", display), ("Window 类型", match(r"\bty=([^\s}]+)", focused_block)),
            ("Window 边界", match(r"mFrame=(\[[^\n ]+)", focused_block)),
            ("PID", raw.get("PID", "").strip() or "未提供")]


COMMANDS = {
    "details": {"属性": ["getprop"], "内存": ["cat", "/proc/meminfo"],
                "CPU": ["cat", "/sys/devices/system/cpu/online"], "分辨率": ["wm", "size"],
                "密度": ["wm", "density"], "存储": ["df", "-h", "/data"],
                "运行时间": ["cat", "/proc/uptime"], "电池": ["dumpsys", "battery"], "权限": ["id"]},
    "foreground": {"Activity": ["dumpsys", "activity", "activities"],
                   "Window": ["dumpsys", "window", "displays"]},
}


def collect(adb, serial, kind, stop):
    raw = {}

    def run(args):
        if stop.is_set():
            raise InterruptedError()
        result = subprocess.run([adb, "-s", serial, "shell", *args], capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=8,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if result.returncode:
            return "读取失败：" + (result.stderr.strip() or result.stdout.strip())[:400]
        return result.stdout

    for name, command in COMMANDS[kind].items():
        raw[name] = run(command)
    if kind == "foreground":
        raw["Window"] += "\n" + run(["dumpsys", "window", "windows"])
        package = parse_foreground(raw)[0][1]
        if re.fullmatch(r"[\w.]+", package, re.ASCII):
            raw["PID"] = run(["pidof", package])
    rows = parse_details(raw) if kind == "details" else parse_foreground(raw)
    errors = [f"{name}: {value}" for name, value in raw.items() if value.startswith("读取失败：")]
    rows.extend(("读取状态", error) for error in errors)
    return Observation(serial, kind, time.time(), tuple(rows),
                       "\n\n".join(f"[{name}]\n{value}" for name, value in raw.items()))


@dataclass
class Session:
    users: set = field(default_factory=set)
    generation: int = 0
    due: float = 0
    busy: bool = False
    stop: threading.Event = field(default_factory=threading.Event)


class DeviceSessionManager(QObject):
    updated = Signal(object)
    failed = Signal(str, str, str)

    def __init__(self, context):
        super().__init__(context)
        self.context = context
        self.sessions = {}
        self.events = queue.Queue()
        self.closed = False
        context.devices.changed.connect(self.devices_changed)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(100)

    def devices_changed(self, devices, error):
        online = {d.serial for d in devices if d.state == "device"}
        for key, session in self.sessions.items():
            if key[0] not in online and not session.stop.is_set():
                session.stop.set()
                session.generation += 1
                session.due = 0
                self.failed.emit(*key, error or "设备已断开或尚未授权")

    def subscribe(self, owner, serial, kind):
        self.unsubscribe(owner)
        if serial and not self.closed:
            session = self.sessions.setdefault((serial, kind), Session())
            if not session.users:
                session.due = 0
            session.users.add(owner)

    def unsubscribe(self, owner):
        for session in self.sessions.values():
            session.users.discard(owner)
            if not session.users:
                session.stop.set()
                session.generation += 1

    def refresh(self, serial, kind):
        session = self.sessions.get((serial, kind))
        if session:
            session.due = 0

    def poll(self):
        self.devices_changed(self.context.devices.items, self.context.devices.error)
        while not self.events.empty():
            key, session, generation, result = self.events.get_nowait()
            session.busy = False
            if session.generation != generation or not session.users or self.closed:
                continue
            if isinstance(result, Exception):
                self.failed.emit(*key, str(result))
            else:
                self.updated.emit(result)
        online = {d.serial for d in self.context.devices.items if d.state == "device"}
        for key, session in list(self.sessions.items()):
            if not session.users:
                if not session.busy:
                    del self.sessions[key]
                continue
            if key[0] not in online:
                if not session.stop.is_set():
                    session.stop.set()
                    session.generation += 1
                    session.due = 0
                    self.failed.emit(*key, "设备已断开或尚未授权")
                continue
            if session.busy or time.monotonic() < session.due:
                continue
            session.stop = threading.Event()
            session.busy = True
            session.due = time.monotonic() + (30 if key[1] == "details" else 2)
            generation = session.generation
            try:
                values = self.context.tools.snapshot()
                self.context.tools.require(values, "adb")
            except Exception as exc:
                self.events.put((key, session, generation, exc))
                continue

            def worker(key=key, session=session, generation=generation, adb=values["adb"], stop=session.stop):
                try:
                    result = collect(adb, *key, stop)
                except Exception as exc:
                    result = exc
                self.events.put((key, session, generation, result))
            threading.Thread(target=worker, daemon=True).start()

    def close(self):
        self.closed = True
        self.timer.stop()
        for session in self.sessions.values():
            session.stop.set()
            session.users.clear()
