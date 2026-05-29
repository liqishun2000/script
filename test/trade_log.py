"""每日买卖操作记录。

记录用户对每只基金实际执行的买入/卖出操作，用于：
1. 复盘历史操作；
2. 在分析时回看"上次对该基金做了什么"，辅助后续决策；
3. 结合净值估算当前持仓份额与盈亏。
"""

from __future__ import annotations

import datetime as _dt
import uuid
from typing import Dict, List, Optional

from . import storage

_FILE = "trades.json"

BUY = "买入"
SELL = "卖出"


def _all() -> List[dict]:
    return storage.load_json(_FILE, [])


def add_trade(
    fund_code: str,
    action: str,
    amount: float,
    nav: float,
    note: str = "",
    date: Optional[str] = None,
) -> dict:
    """新增一条交易记录。

    amount: 本次操作金额（元）；nav: 成交时净值；
    份额按 amount/nav 估算（赎回时为卖出份额估算）。
    """
    fund_code = str(fund_code).strip().zfill(6)
    if action not in (BUY, SELL):
        raise ValueError("action 必须是 买入 或 卖出")
    if date is None:
        date = _dt.date.today().strftime("%Y-%m-%d")

    shares = amount / nav if nav else 0.0
    record = {
        "id": uuid.uuid4().hex[:12],
        "date": date,
        "fund_code": fund_code,
        "action": action,
        "amount": round(float(amount), 2),
        "nav": float(nav),
        "shares": round(shares, 4),
        "note": note,
    }
    trades = _all()
    trades.append(record)
    storage.save_json(_FILE, trades)
    return record


def delete_trade(trade_id: str) -> None:
    trades = [t for t in _all() if t.get("id") != trade_id]
    storage.save_json(_FILE, trades)


def list_trades(fund_code: Optional[str] = None) -> List[dict]:
    """返回交易记录，按日期升序；可按基金代码过滤。"""
    trades = _all()
    if fund_code:
        fund_code = str(fund_code).strip().zfill(6)
        trades = [t for t in trades if t.get("fund_code") == fund_code]
    return sorted(trades, key=lambda t: (t.get("date", ""), t.get("id", "")))


def last_trade(fund_code: str) -> Optional[dict]:
    """返回某只基金最近一次操作记录，没有则返回 None。"""
    records = list_trades(fund_code)
    return records[-1] if records else None


def holding_summary() -> Dict[str, dict]:
    """根据交易记录汇总每只基金的当前持仓（份额、累计投入成本）。

    返回 {fund_code: {shares, cost, buy_amount, sell_amount}}。
    shares 为净份额（买入份额 - 卖出份额），cost 为净投入成本。
    """
    summary: Dict[str, dict] = {}
    for t in list_trades():
        code = t["fund_code"]
        s = summary.setdefault(
            code,
            {"shares": 0.0, "cost": 0.0, "buy_amount": 0.0, "sell_amount": 0.0},
        )
        if t["action"] == BUY:
            s["shares"] += t["shares"]
            s["cost"] += t["amount"]
            s["buy_amount"] += t["amount"]
        else:
            s["shares"] -= t["shares"]
            s["cost"] -= t["amount"]
            s["sell_amount"] += t["amount"]

    # 清理浮点误差导致的极小负份额
    for s in summary.values():
        if abs(s["shares"]) < 1e-6:
            s["shares"] = 0.0
        if s["cost"] < 0:
            s["cost"] = 0.0
    return summary
