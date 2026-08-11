"""基金行情数据获取模块。

通过 akshare 获取国内公募开放式基金的历史单位净值数据，
统一整理成英文列名的 DataFrame，供后续指标计算使用。
"""

from __future__ import annotations

import datetime as _dt
import json as _json
import re as _re
from functools import lru_cache
from typing import Dict, List, Optional

import akshare as ak
import pandas as pd
import requests

from .validation import normalize_fund_code


class FundDataEmpty(ValueError):
    """基金返回空数据——通常意味着该基金已清盘/退市/代码无效。

    与普通网络异常区分开，便于上层判定是否将基金标记为"已失效"。
    """


class FundDataUnavailable(RuntimeError):
    """The remote provider could not return trustworthy fund data."""


_NAV_COLUMN_MAP = {
    "净值日期": "date",
    "单位净值": "nav",
    "累计净值": "acc_nav",
    "日增长率": "pct_change",
}


_PINGZHONG_URL = "https://fund.eastmoney.com/pingzhongdata/{code}.js"
_NAV_TREND_RE = _re.compile(r"var Data_netWorthTrend\s*=\s*(\[.*?\]);", _re.S)
_PINGZHONG_HEADERS = {
    "Referer": "https://fund.eastmoney.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
}


def fetch_fund_nav(fund_code: str) -> pd.DataFrame:
    """拉取指定基金的单位净值历史序列。

    数据源：天天基金 pingzhongdata（纯 JSON，无需 JS 引擎）。
    相比 akshare 的同类接口，本实现不依赖 py_mini_racer(V8)，
    因此**可安全地在多线程中并发调用**，且更快。

    返回包含 ``date``/``nav``/``pct_change`` 的 DataFrame，按日期升序。
    """
    code = normalize_fund_code(fund_code)
    try:
        r = requests.get(_PINGZHONG_URL.format(code=code), timeout=8,
                         headers=_PINGZHONG_HEADERS)
        r.raise_for_status()
    except requests.RequestException as exc:
        raise FundDataUnavailable(f"基金 {code} 净值服务暂时不可用。") from exc

    m = _NAV_TREND_RE.search(r.text or "")
    if not m:
        raise FundDataUnavailable(f"基金 {code} 净值服务返回了未知格式。")
    try:
        arr = _json.loads(m.group(1))
    except _json.JSONDecodeError as exc:
        raise FundDataUnavailable(f"基金 {code} 净值数据解析失败。") from exc

    if not isinstance(arr, list):
        raise FundDataUnavailable(f"基金 {code} 净值数据结构异常。")
    if not arr:
        raise FundDataEmpty(f"基金 {code} 无净值数据（可能已清盘或代码无效）。")

    df = pd.DataFrame(arr)
    # x: 毫秒时间戳; y: 单位净值; equityReturn: 日增长率(%)
    df["date"] = pd.to_datetime(df["x"], unit="ms")
    df["nav"] = pd.to_numeric(df["y"], errors="coerce")
    df["pct_change"] = pd.to_numeric(df.get("equityReturn"), errors="coerce")
    df = df[["date", "nav", "pct_change"]].sort_values("date").reset_index(drop=True)
    df = df.dropna(subset=["nav"]).reset_index(drop=True)
    if df.empty:
        raise FundDataUnavailable(f"基金 {code} 净值数据不包含有效数值。")
    return df


_NAME_TABLE_LOCK = __import__("threading").Lock()


@lru_cache(maxsize=1)
def _fund_name_table() -> pd.DataFrame:
    """缓存公募基金的代码-名称-类型映射表，避免重复请求。

    加锁以防多线程并发冷启动时同时调用底层 akshare 接口。
    """
    with _NAME_TABLE_LOCK:
        return _build_fund_name_table()


def _build_fund_name_table() -> pd.DataFrame:
    table = ak.fund_name_em()
    table = table.rename(
        columns={"基金代码": "code", "基金简称": "name", "基金类型": "type"}
    )
    cols = ["code", "name", "type"] if "type" in table.columns else ["code", "name"]
    if "type" not in table.columns:
        table["type"] = ""
    table["code"] = table["code"].astype(str).str.strip().str.zfill(6)
    return table[["code", "name", "type"]].drop_duplicates("code")


def fetch_fund_type(fund_code: str) -> str:
    """返回基金类型字符串（如 '混合型-偏股'），找不到返回空串。"""
    code = normalize_fund_code(fund_code)
    try:
        table = _fund_name_table()
        hit = table.loc[table["code"] == code, "type"]
        if not hit.empty:
            return str(hit.iloc[0])
    except Exception:
        pass
    return ""


# 权益类（与大盘相关性高）：股票/混合/指数/QDII；债券/货币/商品 不计大盘因子
_EQUITY_PREFIXES = ("股票", "混合", "指数", "QDII")


def is_equity_fund(fund_code: str) -> bool:
    """判断是否为权益类基金（用于决定是否叠加大盘/全球情绪因子）。"""
    t = fetch_fund_type(fund_code)
    return any(t.startswith(p) for p in _EQUITY_PREFIXES)


def fetch_fund_name(fund_code: str) -> str:
    """根据基金代码返回基金中文简称，找不到则回退为代码本身。"""
    code = normalize_fund_code(fund_code)
    try:
        table = _fund_name_table()
        hit = table.loc[table["code"].astype(str) == code, "name"]
        if not hit.empty:
            return str(hit.iloc[0])
    except Exception:
        # 名称表只是辅助信息，失败时不影响主流程
        pass
    return code


def list_all_funds() -> pd.DataFrame:
    """返回全市场公募基金的 code/name/type 列表（用于检索、筛选、批量分析）。"""
    return _fund_name_table().copy()


def list_fund_categories() -> List[str]:
    """返回基金大类（取「基金类型」横线前的主类，去重排序）。"""
    table = _fund_name_table()
    cats = (
        table["type"].dropna().astype(str).str.split("-").str[0].str.strip()
    )
    cats = sorted({c for c in cats if c})
    return cats


# 行业/主题板块关键词表：通过基金简称匹配（行业主题基金通常名字里带板块词）
INDUSTRY_KEYWORDS: Dict[str, List[str]] = {
    "半导体/芯片": ["半导体", "芯片", "集成电路", "存储"],
    "新能源车/电池": ["电池", "锂电", "新能源车", "新能源汽车", "动力电池"],
    "光伏/储能": ["光伏", "储能", "太阳能"],
    "新能源(综合)": ["新能源"],
    "医药医疗": ["医药", "医疗", "生物", "创新药", "疫苗", "CXO", "医械"],
    "白酒/食品饮料": ["白酒", "食品", "饮料", "酿酒"],
    "大消费": ["消费"],
    "军工/国防": ["军工", "国防", "航天", "航空"],
    "证券/券商": ["证券", "券商"],
    "银行": ["银行"],
    "保险/金融": ["保险", "金融"],
    "房地产": ["地产", "房地产"],
    "人工智能/AI": ["人工智能", "AI", "智能"],
    "计算机/软件": ["计算机", "软件", "云计算", "信息技术", "数字经济"],
    "通信/5G": ["通信", "5G"],
    "传媒/游戏": ["传媒", "游戏", "影视", "动漫", "文化"],
    "有色/金属": ["有色", "稀土", "稀有金属"],
    "煤炭/油气": ["煤炭", "石油", "油气", "能源"],
    "钢铁": ["钢铁"],
    "化工": ["化工", "化学"],
    "农业/养殖": ["农业", "养殖", "畜牧", "种业", "农牧"],
    "汽车": ["汽车", "整车", "智能驾驶", "汽车零部件"],
    "机器人/智能制造": ["机器人", "智能制造", "高端装备", "工业母机"],
    "环保": ["环保", "环境", "节能"],
    "黄金/贵金属": ["黄金", "贵金属", "有色金属"],
    "红利/价值": ["红利", "价值", "低波", "股息"],
    "科技成长": ["科技", "成长", "创新"],
    "中概/互联网": ["中概", "互联网", "恒生科技", "纳斯达克", "中国互联"],
}


def list_industries() -> List[str]:
    """返回支持筛选的行业/主题板块名称。"""
    return list(INDUSTRY_KEYWORDS.keys())


def filter_funds_by_industry(df: pd.DataFrame, industry: str) -> pd.DataFrame:
    """按行业/主题关键词过滤基金（匹配基金简称）。"""
    kws = INDUSTRY_KEYWORDS.get(industry)
    if not kws:
        return df
    import re as _r
    pattern = "|".join(_r.escape(k) for k in kws)
    return df[df["name"].astype(str).str.contains(pattern, regex=True)]


# --------------------------------------------------------------------------- #
# 基金官方实时估值（天天基金 fundgz 接口，速度极快，养基宝同源）
# --------------------------------------------------------------------------- #

_FUNDGZ_URL = "https://fundgz.1234567.com.cn/js/{code}.js"
_FUNDGZ_RE = _re.compile(r"jsonpgz\((.*)\)\s*;?")
_FUNDGZ_HEADERS = {
    "Referer": "https://fund.eastmoney.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
}


def fetch_fund_estimate(fund_code: str, timeout: float = 5.0) -> Optional[Dict[str, object]]:
    """获取基金当日官方实时估值。

    返回 dict: {name, dwjz(昨日净值), gsz(估算净值), gszzl(估算涨跌%), gztime(估值时间)}；
    货币基金或暂无估值时返回 None。
    """
    code = normalize_fund_code(fund_code)
    try:
        r = requests.get(_FUNDGZ_URL.format(code=code), timeout=timeout,
                         headers=_FUNDGZ_HEADERS)
        r.raise_for_status()
        m = _FUNDGZ_RE.search(r.text)
        if not m:
            return None
        data = _json.loads(m.group(1))
    except (requests.RequestException, _json.JSONDecodeError):
        return None

    if not isinstance(data, dict):
        return None

    gszzl = data.get("gszzl")
    if gszzl in (None, "", "--"):
        return None
    try:
        return {
            "name": data.get("name", code),
            "dwjz": float(data.get("dwjz")) if data.get("dwjz") else None,
            "gsz": float(data.get("gsz")) if data.get("gsz") else None,
            "gszzl": float(gszzl),
            "gztime": data.get("gztime", ""),
        }
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# 基金持仓 + 股票实时行情（用于估算基金当日涨跌）
# --------------------------------------------------------------------------- #

_HOLDING_COLUMN_MAP = {
    "股票代码": "stock_code",
    "股票名称": "stock_name",
    "占净值比例": "weight",
    "持股数": "shares",
    "持仓市值": "market_value",
    "季度": "quarter",
}


def fetch_fund_holdings(fund_code: str, year: Optional[str] = None) -> pd.DataFrame:
    """获取基金最新一期的股票持仓明细。

    返回包含 ``stock_code``/``stock_name``/``weight``(占净值比例%) 的 DataFrame，
    只保留最新季度的数据，按占比降序。
    """
    fund_code = normalize_fund_code(fund_code)
    if year is None:
        year = str(_dt.date.today().year)

    raw = ak.fund_portfolio_hold_em(symbol=fund_code, date=year)
    if (raw is None or raw.empty) and year != str(_dt.date.today().year - 1):
        # 年初时当年季报可能还没出，回退到上一年
        raw = ak.fund_portfolio_hold_em(symbol=fund_code, date=str(int(year) - 1))

    if raw is None or raw.empty:
        return pd.DataFrame(columns=["stock_code", "stock_name", "weight"])

    df = raw.rename(columns=_HOLDING_COLUMN_MAP).copy()
    df["weight"] = pd.to_numeric(df["weight"], errors="coerce")
    # 只取最新季度
    if "quarter" in df.columns and df["quarter"].notna().any():
        quarters = df["quarter"].astype(str)
        latest_quarter = max(
            quarters[df["quarter"].notna()],
            key=_quarter_sort_key,
        )
        df = df[quarters == latest_quarter]
    df = df.dropna(subset=["weight"]).sort_values("weight", ascending=False)
    return df.reset_index(drop=True)


def _quarter_sort_key(value: str) -> tuple[int, int]:
    match = _re.search(r"(\d{4}).*?([1-4])", value)
    return (int(match.group(1)), int(match.group(2))) if match else (0, 0)


def _stock_em_symbol(stock_code: str) -> str:
    """东财单股接口只接受 6 位数字代码，过滤掉港股/海外等无法查询的代码。"""
    return stock_code.strip()


def fetch_stock_change(stock_code: str) -> Optional[float]:
    """获取单只 A 股的当日涨跌幅（百分比）。失败或非 A 股返回 None。"""
    code = _stock_em_symbol(stock_code)
    if not (code.isdigit() and len(code) == 6):
        return None
    try:
        df = ak.stock_bid_ask_em(symbol=code)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    row = df.loc[df["item"] == "涨幅", "value"]
    if row.empty:
        return None
    try:
        return float(row.iloc[0])
    except (TypeError, ValueError):
        return None


def estimate_fund_intraday_change(
    fund_code: str,
    top_n: int = 10,
) -> Dict[str, object]:
    """根据基金前 N 大重仓股的实时涨跌，加权估算基金当日涨跌幅。

    返回 dict:
        - estimate_pct: 加权估算涨跌幅(%)，覆盖不到则为 None
        - covered_weight: 参与估算的持仓占净值比例之和(%)
        - details: 每只重仓股的 [代码, 名称, 占比, 当日涨跌] 明细
    """
    fund_code = normalize_fund_code(fund_code)
    if not isinstance(top_n, int) or not 1 <= top_n <= 100:
        raise ValueError("重仓股数量必须是 1 到 100 的整数。")
    holdings = fetch_fund_holdings(fund_code)
    result: Dict[str, object] = {
        "estimate_pct": None,
        "covered_weight": 0.0,
        "details": [],
    }
    if holdings.empty:
        return result

    top = holdings.head(top_n)
    weighted_sum = 0.0
    covered = 0.0
    details: List[dict] = []

    for _, r in top.iterrows():
        change = fetch_stock_change(str(r["stock_code"]))
        weight = float(r["weight"])
        details.append(
            {
                "code": str(r["stock_code"]),
                "name": str(r["stock_name"]),
                "weight": weight,
                "change": change,
            }
        )
        if change is not None:
            weighted_sum += weight * change
            covered += weight

    result["details"] = details
    result["covered_weight"] = covered
    if covered > 0:
        # 用已覆盖权重归一化，得到这部分持仓的加权平均涨跌
        result["estimate_pct"] = weighted_sum / covered
    return result
