from __future__ import annotations
import os, queue, re, subprocess, threading, time, sqlite3, json
from dataclasses import dataclass
from PySide6.QtCore import QObject, QTimer, Signal

@dataclass(frozen=True)
class MetricSample:
    serial: str
    kind: str
    timestamp: float
    values: tuple[tuple[str, str], ...]
    raw: str = ""

class MetricStore:
    def __init__(self, root):
        self.path = root / "metrics.sqlite3"; self.lock = threading.Lock()
        db=sqlite3.connect(self.path)
        try: db.execute("create table if not exists samples (id integer primary key, serial text, kind text, package text, ts real, payload text)"); db.commit()
        finally: db.close()
    def add(self, sample, package=""):
        with self.lock:
            db=sqlite3.connect(self.path)
            try: db.execute("insert into samples(serial,kind,package,ts,payload) values(?,?,?,?,?)", (sample.serial,sample.kind,package,sample.timestamp,json.dumps(dict(sample.values),ensure_ascii=False))); db.commit()
            finally: db.close()
    def recent(self, serial="", kind="", limit=500):
        query="select serial,kind,package,ts,payload from samples where 1=1"; args=[]
        if serial: query += " and serial=?"; args.append(serial)
        if kind: query += " and kind=?"; args.append(kind)
        query += " order by ts desc limit ?"; args.append(limit)
        with self.lock:
            db=sqlite3.connect(self.path)
            try: return db.execute(query,args).fetchall()
            finally: db.close()
    def export_csv(self, path, serial="", kind=""):
        import csv
        rows=self.recent(serial,kind,10000); keys=sorted({k for *_, values in rows for k in json.loads(values)})
        with path.open("w",newline="",encoding="utf-8-sig") as f:
            writer=csv.writer(f); writer.writerow(["serial","kind","package","time",*keys])
            for s,k,p,ts,values in rows:
                values=json.loads(values); writer.writerow([s,k,p,time.strftime("%Y-%m-%d %H:%M:%S",time.localtime(ts)),*[values.get(key,"") for key in keys]])

def _num(pattern, text, default="N/A"):
    m = re.search(pattern, text, re.M)
    return m.group(1) if m else default

def _run(adb, serial, command):
    p = subprocess.run([adb, "-s", serial, "shell", *command], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=8,
                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    return p.stdout if p.returncode == 0 else "读取失败: " + (p.stderr.strip() or p.stdout.strip())

def collect_metrics(adb, serial, kind, previous=None):
    raw = {}
    if kind == "device_metrics":
        for name, cmd in (("stat", ["cat", "/proc/stat"]), ("mem", ["cat", "/proc/meminfo"]),
                          ("battery", ["dumpsys", "battery"]), ("thermal", ["dumpsys", "thermalservice"])):
            raw[name] = _run(adb, serial, cmd)
        values = []
        line = next((x for x in raw["stat"].splitlines() if x.startswith("cpu ")), "")
        fields = [int(x) for x in line.split()[1:] if x.isdigit()]
        if previous and fields:
            total = sum(fields) - sum(previous); idle = fields[3] - previous[3]
            values.append(("CPU 总使用率", f"{max(0, min(100, (1 - idle / total) * 100)):.1f}%" if total else "N/A"))
        else: values.append(("CPU 总使用率", "首次采样"))
        values += [("内存总量", _num(r"MemTotal:\s+(\d+) kB", raw["mem"])),
                   ("可用内存", _num(r"MemAvailable:\s+(\d+) kB", raw["mem"])),
                   ("电量", _num(r"^\s*level:\s*(\d+)", raw["battery"]) + "%"),
                   ("电池温度", (_num(r"^\s*temperature:\s*(-?\d+)", raw["battery"]) + " /10 °C")),
                   ("温度服务", "读取失败" if raw["thermal"].startswith("读取失败:") else "可用")]
        return MetricSample(serial, kind, time.time(), tuple(values), "\n\n".join(raw.values())), fields
    package = previous or ""
    pid = _run(adb, serial, ["pidof", package]).strip() if package else ""
    mem = _run(adb, serial, ["dumpsys", "meminfo", "-s", package]) if package else ""
    top = _run(adb, serial, ["top", "-b", "-n", "1", "-p", pid.split()[0]]) if pid else ""
    values = [("包名", package or "未指定"), ("PID", pid or "未运行"),
              ("CPU", _num(r"\s(\d+(?:\.\d+)?)%\s+\d+.*\s+" + re.escape(pid.split()[0] if pid else "__none__") + r"\b", top)),
              ("TOTAL PSS", _num(r"TOTAL PSS:\s+(\d+)", mem) + " kB"),
              ("Native PSS", _num(r"Native Heap\s+\d+\s+(\d+)", mem) + " kB"),
              ("Graphics PSS", _num(r"Graphics\s+\d+\s+(\d+)", mem) + " kB")]
    return MetricSample(serial, kind, time.time(), tuple(values), mem + "\n" + top), package

class MetricsManager(QObject):
    updated = Signal(object)
    failed = Signal(str, str, str)
    def __init__(self, context):
        super().__init__(context); self.context=context; self.store=MetricStore(context.preferences.root); self.jobs={}; self.events=queue.Queue(); self.timer=QTimer(self); self.timer.timeout.connect(self.poll); self.timer.start(100)
    def subscribe(self, owner, serial, kind, package=""):
        self.unsubscribe(owner); self.jobs[(serial,kind,package)] = {"owner":owner,"package":package,"last":None,"busy":False,"next":0,"stop":False}
    def unsubscribe(self, owner):
        for key in list(self.jobs):
            if self.jobs[key]["owner"] is owner: self.jobs.pop(key)
    def poll(self):
        while not self.events.empty():
            job, result = self.events.get_nowait(); job["busy"]=False
            if not job["stop"] and isinstance(result, MetricSample): self.store.add(result, job.get("package", "")); self.updated.emit(result)
        online={d.serial for d in self.context.devices.items if d.state=="device"}
        for key,job in list(self.jobs.items()):
            if job["busy"] or time.monotonic()<job["next"]: continue
            if key[0] not in online: self.failed.emit(*key[:2], "设备已断开"); job["next"]=time.monotonic()+2; continue
            try: adb=self.context.tools.snapshot()["adb"]
            except Exception as e: self.failed.emit(*key[:2],str(e)); continue
            job["busy"]=True; job["next"]=time.monotonic()+2
            def worker(key=key,job=job,adb=adb):
                try: result, state=collect_metrics(adb,key[0],key[1], job["last"] if key[1]=="device_metrics" else key[2]); job["last"]=state
                except Exception as e: result=e
                self.events.put((job,result))
            threading.Thread(target=worker,daemon=True).start()
    def close(self): self.timer.stop(); self.jobs.clear()
