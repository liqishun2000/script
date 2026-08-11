"""已失效（清盘/退市/代码无效）基金登记。

当某只基金返回空净值数据时，将其代码登记到本地文件，
后续在「全部基金」列表展示与批量评分时自动跳过，避免反复请求无效基金。
"""

from __future__ import annotations

import datetime as _dt
from typing import Dict, Set

from . import storage
from .validation import normalize_fund_code

_FILE = "dead_funds.json"


def _all() -> Dict[str, dict]:
    data = storage.load_json(_FILE, {})
    return data if isinstance(data, dict) else {}


def mark_dead(code: str, reason: str = "已人工确认失效") -> None:
    """Record a manually confirmed invalid fund.

    Provider failures must never call this function. Legacy records without the
    ``confirmed`` flag are intentionally ignored by ``dead_set``.
    """
    code = normalize_fund_code(code)

    def update(data):
        data[code] = {
            "reason": reason,
            "date": _dt.date.today().strftime("%Y-%m-%d"),
            "confirmed": True,
        }
        return data

    storage.update_json(_FILE, {}, update)


def is_dead(code: str) -> bool:
    return normalize_fund_code(code) in dead_set()


def dead_set() -> Set[str]:
    return {
        code for code, record in _all().items()
        if isinstance(record, dict) and record.get("confirmed") is True
    }


def count() -> int:
    return len(dead_set())


def clear() -> None:
    storage.save_json(_FILE, {})
