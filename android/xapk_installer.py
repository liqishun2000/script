"""
XAPK / APKS / APKM 核心安装逻辑（无 GUI 依赖）。

提供给 CLI 和 GUI 两种入口复用。所有输出通过 `log` 回调暴露，
方便 GUI 把输出渲染到日志窗口。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Callable, Iterable

LogFunc = Callable[[str], None]

ADB_PATH = "adb"

if os.name == "nt":
    _SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW  # 隐藏 adb 黑窗口
else:
    _SUBPROCESS_FLAGS = 0


class InstallError(RuntimeError):
    """安装流程中的可预期错误，GUI / CLI 可直接展示给用户。"""


def _stream_run(cmd: list[str], log: LogFunc, check: bool = True) -> int:
    """运行命令并把 stdout/stderr 逐行喂给 log 回调。"""
    log(f"$ {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_SUBPROCESS_FLAGS,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        log(line.rstrip())
    code = proc.wait()
    if check and code != 0:
        raise InstallError(f"命令失败 (exit={code}): {' '.join(cmd)}")
    return code


def _capture(cmd: list[str]) -> str:
    return subprocess.run(
        cmd,
        check=True,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_SUBPROCESS_FLAGS,
    ).stdout


def list_devices() -> list[str]:
    """返回所有处于 device 状态的设备序列号；adb 不可用时返回空列表。"""
    try:
        out = _capture([ADB_PATH, "devices"])
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []
    devices: list[str] = []
    for line in out.splitlines()[1:]:
        line = line.strip()
        if line.endswith("device"):
            devices.append(line.split()[0])
    return devices


def _resolve_serial(serial: str | None) -> str:
    devices = list_devices()
    if not devices:
        raise InstallError("没有检测到 adb 设备，请连接手机并开启 USB 调试。")
    if serial:
        if serial not in devices:
            raise InstallError(f"未找到指定设备 {serial}，可用设备: {devices}")
        return serial
    if len(devices) > 1:
        raise InstallError(f"检测到多台设备 {devices}，请在界面上选择目标设备。")
    return devices[0]


def _parse_manifest(extract_dir: Path) -> dict:
    p = extract_dir / "manifest.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _collect_apks(extract_dir: Path, manifest: dict, log: LogFunc) -> list[Path]:
    apks: list[Path] = []
    for entry in manifest.get("split_apks") or []:
        f = extract_dir / entry["file"]
        if f.exists():
            apks.append(f)
        else:
            log(f"警告: manifest 中声明的 {entry['file']} 不存在，跳过。")
    if not apks:
        apks = sorted(extract_dir.rglob("*.apk"))
    if not apks:
        raise InstallError("XAPK 中未找到任何 .apk 文件。")
    return apks


def _collect_obbs(extract_dir: Path, manifest: dict) -> list[tuple[Path, str]]:
    items: list[tuple[Path, str]] = []
    if manifest.get("expansions"):
        for exp in manifest["expansions"]:
            src = extract_dir / exp["file"]
            install_path = exp.get("install_path")
            if src.exists() and install_path:
                items.append((src, f"/sdcard/{install_path}"))
        return items

    package = manifest.get("package_name", "")
    if package:
        for obb in extract_dir.rglob("*.obb"):
            items.append((obb, f"/sdcard/Android/obb/{package}/{obb.name}"))
    return items


def install_xapk(
    xapk_path: Path,
    *,
    serial: str | None = None,
    keep_data: bool = False,
    downgrade: bool = False,
    log: LogFunc = print,
) -> None:
    """解压并安装一个 XAPK / APKS / APKM 包。"""
    xapk_path = Path(xapk_path).expanduser().resolve()
    if not xapk_path.exists():
        raise InstallError(f"文件不存在: {xapk_path}")
    if not zipfile.is_zipfile(xapk_path):
        raise InstallError(f"不是有效的 XAPK / ZIP 文件: {xapk_path}")

    target = _resolve_serial(serial)
    log(f"目标设备: {target}")
    log(f"XAPK 文件: {xapk_path} ({xapk_path.stat().st_size / 1024 / 1024:.1f} MB)")

    tmp = Path(tempfile.mkdtemp(prefix="xapk_"))
    log(f"解压到: {tmp}")
    try:
        with zipfile.ZipFile(xapk_path) as zf:
            zf.extractall(tmp)

        manifest = _parse_manifest(tmp)
        if manifest:
            log(
                f"包名: {manifest.get('package_name', '?')}  "
                f"版本: {manifest.get('version_name', '?')} "
                f"({manifest.get('version_code', '?')})"
            )

        apks = _collect_apks(tmp, manifest, log)
        obbs = _collect_obbs(tmp, manifest)
        log(f"将安装 {len(apks)} 个 APK，推送 {len(obbs)} 个 OBB 文件。")

        flags: list[str] = []
        if keep_data:
            flags.append("-r")
        if downgrade:
            flags.append("-d")

        if len(apks) == 1:
            cmd = [ADB_PATH, "-s", target, "install", *flags, str(apks[0])]
        else:
            cmd = [
                ADB_PATH, "-s", target, "install-multiple", *flags,
                *[str(p) for p in apks],
            ]
        _stream_run(cmd, log)

        if obbs:
            for d in {os.path.dirname(t) for _, t in obbs}:
                _stream_run(
                    [ADB_PATH, "-s", target, "shell", "mkdir", "-p", d],
                    log, check=False,
                )
            for src, tgt in obbs:
                _stream_run([ADB_PATH, "-s", target, "push", str(src), tgt], log)

        log("安装完成。")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def install_many(
    xapk_paths: Iterable[Path],
    *,
    serial: str | None = None,
    keep_data: bool = False,
    downgrade: bool = False,
    log: LogFunc = print,
) -> None:
    """批量安装多个 XAPK，遇到错误只打印不中断后续任务。"""
    paths = list(xapk_paths)
    for i, p in enumerate(paths, 1):
        log("")
        log(f"========== [{i}/{len(paths)}] {p.name} ==========")
        try:
            install_xapk(
                p,
                serial=serial,
                keep_data=keep_data,
                downgrade=downgrade,
                log=log,
            )
        except InstallError as e:
            log(f"错误: {e}")
