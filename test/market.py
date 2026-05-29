"""大盘指数行情模块。

通过东方财富批量行情接口一次性获取多只指数的实时涨跌，
用于首页展示；并提供单只指数的扩展行情与历史日线，用于指数详情页。
"""

from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd
import requests

# 首页展示的主要指数： (东财 secid, 显示名, akshare 日线 symbol)
MAJOR_INDICES: List[Dict[str, str]] = [
    {"secid": "1.000001", "code": "000001", "name": "上证指数", "hist": "sh000001"},
    {"secid": "0.399001", "code": "399001", "name": "深证成指", "hist": "sz399001"},
    {"secid": "0.399006", "code": "399006", "name": "创业板指", "hist": "sz399006"},
    {"secid": "1.000300", "code": "000300", "name": "沪深300", "hist": "sh000300"},
    {"secid": "1.000905", "code": "000905", "name": "中证500", "hist": "sh000905"},
    {"secid": "1.000016", "code": "000016", "name": "上证50", "hist": "sh000016"},
    {"secid": "1.000688", "code": "000688", "name": "科创50", "hist": "sh000688"},
    {"secid": "0.399295", "code": "399295", "name": "创业板50", "hist": "sz399295"},
]

_QUOTE_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# f 字段含义：f2 最新价 f3 涨跌幅 f4 涨跌额 f12 代码 f14 名称
# f15 最高 f16 最低 f17 今开 f18 昨收 f5 成交量(手) f6 成交额(元)
_SPOT_FIELDS = "f2,f3,f4,f12,f14,f15,f16,f17,f18,f5,f6"


def _secid_map() -> Dict[str, dict]:
    return {i["code"]: i for i in MAJOR_INDICES}


def fetch_index_spot() -> List[dict]:
    """一次请求获取首页全部指数的实时行情。

    返回每只指数的 dict 列表：code/name/price/change_pct/change。
    失败时抛出异常由上层处理。
    """
    secids = ",".join(i["secid"] for i in MAJOR_INDICES)
    params = {"secids": secids, "fields": _SPOT_FIELDS, "fltt": "2", "np": "1"}
    r = requests.get(_QUOTE_URL, params=params, timeout=8, headers=_HEADERS)
    diff = (r.json() or {}).get("data", {}).get("diff", [])

    name_map = _secid_map()
    result = []
    for d in diff:
        code = str(d.get("f12"))
        meta = name_map.get(code, {})
        result.append({
            "code": code,
            "name": meta.get("name", d.get("f14", code)),
            "price": _num(d.get("f2")),
            "change_pct": _num(d.get("f3")),
            "change": _num(d.get("f4")),
        })
    # 保持与 MAJOR_INDICES 一致的顺序
    order = {i["code"]: idx for idx, i in enumerate(MAJOR_INDICES)}
    result.sort(key=lambda x: order.get(x["code"], 999))
    return result


def fetch_index_detail(code: str) -> dict:
    """获取单只指数的扩展实时行情（开高低、昨收、成交额等）。"""
    meta = _secid_map().get(str(code))
    if not meta:
        raise ValueError(f"未知指数代码: {code}")
    params = {"secids": meta["secid"], "fields": _SPOT_FIELDS, "fltt": "2", "np": "1"}
    r = requests.get(_QUOTE_URL, params=params, timeout=8, headers=_HEADERS)
    diff = (r.json() or {}).get("data", {}).get("diff", [])
    if not diff:
        raise ValueError(f"未获取到指数 {code} 行情。")
    d = diff[0]
    return {
        "code": code,
        "name": meta["name"],
        "price": _num(d.get("f2")),
        "change_pct": _num(d.get("f3")),
        "change": _num(d.get("f4")),
        "high": _num(d.get("f15")),
        "low": _num(d.get("f16")),
        "open": _num(d.get("f17")),
        "prev_close": _num(d.get("f18")),
        "amount": _num(d.get("f6")),
    }


_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"


def fetch_index_history(code: str, days: int = 30) -> pd.DataFrame:
    """获取指数近 N 个交易日的日线（date/open/close/high/low/pct）。

    使用东财 push2his K线接口（与实时行情同源，较稳定），失败自动重试。
    """
    meta = _secid_map().get(str(code))
    if not meta:
        raise ValueError(f"未知指数代码: {code}")

    params = {
        "secid": meta["secid"],
        "fields1": "f1,f2,f3,f4,f5",
        # f51 日期 f52 开 f53 收 f54 高 f55 低 f56 量 f57 额 f58 振幅 f59 涨跌幅
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59",
        "klt": "101",   # 日线
        "fqt": "0",
        "end": "20500101",
        "lmt": str(days),
    }
    klines = []
    last_exc = None
    for _ in range(3):
        try:
            r = requests.get(_KLINE_URL, params=params, timeout=8, headers=_HEADERS)
            klines = (r.json() or {}).get("data", {}).get("klines", []) or []
            if klines:
                break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
    if not klines:
        if last_exc:
            raise last_exc
        return pd.DataFrame()

    rows = []
    for line in klines:
        parts = line.split(",")
        rows.append({
            "date": parts[0],
            "open": _num(parts[1]),
            "close": _num(parts[2]),
            "high": _num(parts[3]),
            "low": _num(parts[4]),
            "pct": _num(parts[8]) if len(parts) > 8 else None,
        })
    return pd.DataFrame(rows)


def _num(v) -> Optional[float]:
    try:
        if v in (None, "", "-"):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None
