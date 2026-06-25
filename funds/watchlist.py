"""自选基金清单管理。

由于全市场公募基金数量过万、逐一联网分析不现实，本工具采用
"自选清单"的方式：用户把关注的基金加入清单，批量分析仅针对清单内基金。
"""

from __future__ import annotations

from typing import List

from . import storage

_FILE = "watchlist.json"
_DEFAULT = ["000001", "110022", "519066"]


def get_watchlist() -> List[str]:
    """返回当前自选基金代码列表（首次使用时给出几个示例基金）。"""
    data = storage.load_json(_FILE, None)
    if data is None:
        storage.save_json(_FILE, _DEFAULT)
        return list(_DEFAULT)
    return [str(c).zfill(6) for c in data]


def add_fund(code: str) -> List[str]:
    code = str(code).strip().zfill(6)
    codes = get_watchlist()
    if code not in codes:
        codes.append(code)
        storage.save_json(_FILE, codes)
    return codes


def remove_fund(code: str) -> List[str]:
    code = str(code).strip().zfill(6)
    codes = [c for c in get_watchlist() if c != code]
    storage.save_json(_FILE, codes)
    return codes
