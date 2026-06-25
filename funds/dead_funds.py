"""已失效（清盘/退市/代码无效）基金登记。

当某只基金返回空净值数据时，将其代码登记到本地文件，
后续在「全部基金」列表展示与批量评分时自动跳过，避免反复请求无效基金。
"""

from __future__ import annotations

import datetime as _dt
from typing import Dict, Set

from . import storage

_FILE = "dead_funds.json"


def _all() -> Dict[str, dict]:
    return storage.load_json(_FILE, {})


def mark_dead(code: str, reason: str = "无净值数据") -> None:
    code = str(code).strip().zfill(6)
    data = _all()
    if code not in data:
        data[code] = {
            "reason": reason,
            "date": _dt.date.today().strftime("%Y-%m-%d"),
        }
        storage.save_json(_FILE, data)


def is_dead(code: str) -> bool:
    return str(code).strip().zfill(6) in _all()


def dead_set() -> Set[str]:
    return set(_all().keys())


def count() -> int:
    return len(_all())


def clear() -> None:
    storage.save_json(_FILE, {})
