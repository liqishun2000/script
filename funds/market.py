"""大盘指数行情模块。

通过东方财富批量行情接口一次性获取多只指数的实时涨跌，
用于首页展示；并提供单只指数的扩展行情与历史日线，用于指数详情页。
"""

from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd
import requests

# 首页展示的主要指数： (东财 secid, 代码, 显示名, 新浪代码)
MAJOR_INDICES: List[Dict[str, str]] = [
    {"secid": "1.000001", "code": "000001", "name": "上证指数", "sina": "sh000001"},
    {"secid": "0.399001", "code": "399001", "name": "深证成指", "sina": "sz399001"},
    {"secid": "0.399006", "code": "399006", "name": "创业板指", "sina": "sz399006"},
    {"secid": "1.000300", "code": "000300", "name": "沪深300", "sina": "sh000300"},
    {"secid": "1.000905", "code": "000905", "name": "中证500", "sina": "sh000905"},
    {"secid": "1.000688", "code": "000688", "name": "科创50", "sina": "sh000688"},
    # —— 全球（美股隔夜，反映外围情绪） ——
    {"secid": "100.NDX", "code": "NDX", "name": "纳斯达克", "sina": "gb_ixic"},
    {"secid": "100.SPX", "code": "SPX", "name": "标普500", "sina": "gb_inx"},
    {"secid": "100.DJIA", "code": "DJIA", "name": "道琼斯", "sina": "gb_dji"},
]

_QUOTE_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "*/*",
}


def _get_json(url: str, params: dict, retries: int = 4) -> dict:
    """带重试+退避的 GET JSON（东财 push2 接口偶发断连/限流）。"""
    import time as _t
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, params=params, timeout=8, headers=_HEADERS)
            return r.json() or {}
        except Exception as exc:  # noqa: BLE001
            last = exc
            _t.sleep(0.5 * (i + 1))  # 递增退避
    if last:
        raise last
    return {}

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
    # 优先东财 push2；失败/被限流则回退新浪行情（不同服务器，更稳）
    try:
        result = _fetch_spot_push2()
        if result:
            return result
    except Exception:
        pass
    return _fetch_spot_sina()


def _fetch_spot_push2() -> List[dict]:
    secids = ",".join(i["secid"] for i in MAJOR_INDICES)
    params = {"secids": secids, "fields": _SPOT_FIELDS, "fltt": "2", "np": "1"}
    diff = _get_json(_QUOTE_URL, params, retries=2).get("data", {}).get("diff", []) or []

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
    order = {i["code"]: idx for idx, i in enumerate(MAJOR_INDICES)}
    result.sort(key=lambda x: order.get(x["code"], 999))
    return result


_SINA_URL = "https://hq.sinajs.cn/list={symbols}"
_SINA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://finance.sina.com.cn",
}


def _fetch_spot_sina() -> List[dict]:
    """新浪行情备用源。A 股与美股字段格式不同，分别解析。"""
    symbols = ",".join(i["sina"] for i in MAJOR_INDICES)
    r = requests.get(_SINA_URL.format(symbols=symbols), timeout=8, headers=_SINA_HEADERS)
    r.encoding = "gbk"
    text = r.text
    result = []
    for meta in MAJOR_INDICES:
        sym = meta["sina"]
        m = _re_sina(sym, text)
        if not m:
            continue
        fields = m.split(",")
        try:
            if sym.startswith("gb_"):  # 美股: 名称,现价,涨跌幅,时间,涨跌额,昨收,...
                price = _num(fields[1])
                pct = _num(fields[2])
                change = _num(fields[4])
            else:                      # A股: 名称,今开,昨收,现价,最高,最低,...
                prev = _num(fields[2])
                price = _num(fields[3])
                change = (price - prev) if (price is not None and prev) else None
                pct = ((price / prev - 1) * 100) if (price is not None and prev) else None
        except (IndexError, TypeError):
            continue
        result.append({
            "code": meta["code"], "name": meta["name"],
            "price": price, "change_pct": pct, "change": change,
        })
    return result


def _re_sina(symbol: str, text: str) -> Optional[str]:
    import re
    m = re.search(rf'var hq_str_{symbol}="([^"]*)"', text)
    return m.group(1) if (m and m.group(1)) else None


def fetch_index_detail(code: str) -> dict:
    """获取单只指数的扩展实时行情（开高低、昨收、成交额等）。"""
    meta = _secid_map().get(str(code))
    if not meta:
        raise ValueError(f"未知指数代码: {code}")
    params = {"secids": meta["secid"], "fields": _SPOT_FIELDS, "fltt": "2", "np": "1"}
    diff = _get_json(_QUOTE_URL, params).get("data", {}).get("diff", []) or []
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
    klines = _get_json(_KLINE_URL, params).get("data", {}).get("klines", []) or []
    if not klines:
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


def market_sentiment() -> dict:
    """综合 A 股大盘趋势 + 当日涨跌 + 美股隔夜，得出大盘情绪分。

    返回 {score: -2~2, detail: 文字说明}。score 越高代表外围/大盘越偏多。
    用作个基技术评分之外的"系统性环境"修正项。
    """
    score = 0.0
    details: List[str] = []
    spot = {}
    try:
        spot = {r["code"]: r for r in fetch_index_spot()}
    except Exception:
        pass

    # 1) 沪深300 中期趋势（20/60 日）
    try:
        h = fetch_index_history("000300", days=65)
        c = h["close"].to_numpy()
        if len(c) >= 21:
            r20 = c[-1] / c[-21] - 1
            r60 = c[-1] / c[0] - 1
            if r20 > 0 and r60 > 0:
                score += 1.0
                details.append("沪深300中期上行")
            elif r20 < 0 and r60 < 0:
                score -= 1.0
                details.append("沪深300中期下行")
    except Exception:
        pass

    # 2) 沪深300 当日涨跌
    hs = spot.get("000300", {}).get("change_pct")
    if hs is not None:
        if hs >= 1.0:
            score += 0.7
        elif hs >= 0.2:
            score += 0.3
        elif hs <= -1.0:
            score -= 0.7
        elif hs <= -0.2:
            score -= 0.3
        details.append(f"沪深300今日{hs:+.2f}%")

    # 3) 美股隔夜（纳斯达克）
    nd = spot.get("NDX", {}).get("change_pct")
    if nd is not None:
        if nd >= 1.0:
            score += 0.5
        elif nd >= 0.2:
            score += 0.2
        elif nd <= -1.0:
            score -= 0.5
        elif nd <= -0.2:
            score -= 0.2
        details.append(f"纳指隔夜{nd:+.2f}%")

    score = max(-2.0, min(2.0, score))
    return {"score": score, "detail": "; ".join(details) or "无数据"}


def _num(v) -> Optional[float]:
    try:
        if v in (None, "", "-"):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None
