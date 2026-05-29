"""统一的本地数据持久化层。

所有用户数据（自选基金、持仓、交易记录、配置）都以 JSON 形式
保存在 ``test/data/`` 目录下，便于在不同会话之间保留状态。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

_DATA_DIR = Path(__file__).resolve().parent / "data"
_LOCK = threading.Lock()


def _path(name: str) -> Path:
    return _DATA_DIR / name


def load_json(name: str, default: Any) -> Any:
    """读取 JSON 文件，不存在或损坏时返回 default。"""
    p = _path(name)
    if not p.exists():
        return default
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def save_json(name: str, data: Any) -> None:
    """原子化写入 JSON 文件（先写临时文件再替换）。"""
    with _LOCK:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        p = _path(name)
        tmp = p.with_suffix(p.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.replace(p)
