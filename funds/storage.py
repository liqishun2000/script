"""统一的本地数据持久化层。

所有用户数据（自选基金、持仓、交易记录、配置）都以 JSON 形式
保存在 ``funds/data/`` 目录下，便于在不同会话之间保留状态。
"""

from __future__ import annotations

import json
import copy
import threading
import uuid
from pathlib import Path
from typing import Any

_DATA_DIR = Path(__file__).resolve().parent / "data"
_LOCK = threading.RLock()


def _path(name: str) -> Path:
    if not name or Path(name).name != name:
        raise ValueError("数据文件名不能包含目录路径。")
    return _DATA_DIR / name


def _load_unlocked(name: str, default: Any) -> Any:
    p = _path(name)
    if not p.exists():
        return copy.deepcopy(default)
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return copy.deepcopy(default)


def _save_unlocked(name: str, data: Any) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    p = _path(name)
    tmp = p.with_name(f".{p.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
        tmp.replace(p)
    finally:
        if tmp.exists():
            tmp.unlink()


def load_json(name: str, default: Any) -> Any:
    """读取 JSON 文件，不存在或损坏时返回 default。"""
    with _LOCK:
        return _load_unlocked(name, default)


def save_json(name: str, data: Any) -> None:
    """原子化写入 JSON 文件（先写临时文件再替换）。"""
    with _LOCK:
        _save_unlocked(name, data)


def update_json(name: str, default: Any, updater) -> Any:
    """Atomically load, update and save one JSON document within this process."""
    with _LOCK:
        current = _load_unlocked(name, default)
        updated = updater(current)
        if updated is None:
            updated = current
        _save_unlocked(name, updated)
        return copy.deepcopy(updated)
