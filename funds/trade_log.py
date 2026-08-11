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
from .validation import normalize_fund_code, positive_number

_FILE = "trades.json"

BUY = "买入"
SELL = "卖出"


def _all() -> List[dict]:
    data = storage.load_json(_FILE, [])
    return data if isinstance(data, list) else []


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
    fund_code = normalize_fund_code(fund_code)
    if action not in (BUY, SELL):
        raise ValueError("action 必须是 买入 或 卖出")
    amount = positive_number(amount, "交易金额")
    nav = positive_number(nav, "成交净值")
    if date is None:
        date = _dt.date.today().strftime("%Y-%m-%d")
    try:
        date = _dt.date.fromisoformat(str(date)).isoformat()
    except ValueError as exc:
        raise ValueError("交易日期必须使用 YYYY-MM-DD 格式。") from exc

    shares = amount / nav
    record = {
        "id": uuid.uuid4().hex[:12],
        "date": date,
        "fund_code": fund_code,
        "action": action,
        "amount": round(float(amount), 2),
        "nav": float(nav),
        "shares": round(shares, 8),
        "note": str(note),
    }

    def update(trades):
        if not isinstance(trades, list):
            trades = []
        if action == SELL:
            held = _shares_for_code(trades, fund_code)
            if shares > held + 1e-8:
                raise ValueError(
                    f"卖出份额 {shares:.4f} 超过当前持有份额 {held:.4f}。"
                )
        trades.append(record)
        return trades

    storage.update_json(_FILE, [], update)
    return record


def delete_trade(trade_id: str) -> None:
    def update(trades):
        removed = next((t for t in trades if t.get("id") == trade_id), None)
        remaining = [t for t in trades if t.get("id") != trade_id]
        if removed is not None:
            code = removed.get("fund_code")
            raw_balance = _raw_shares_for_code(remaining, code)
            if raw_balance < -1e-8:
                raise ValueError("不能删除该记录，否则卖出份额将超过持仓。")
        return remaining

    storage.update_json(_FILE, [], update)


def list_trades(fund_code: Optional[str] = None) -> List[dict]:
    """返回交易记录，按日期升序；可按基金代码过滤。"""
    trades = _all()
    if fund_code:
        fund_code = normalize_fund_code(fund_code)
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
            {"shares": 0.0, "cost": 0.0, "buy_amount": 0.0,
             "sell_amount": 0.0, "realized_pnl": 0.0},
        )
        if t["action"] == BUY:
            s["shares"] += t["shares"]
            s["cost"] += t["amount"]
            s["buy_amount"] += t["amount"]
        else:
            held = max(s["shares"], 0.0)
            sold = min(float(t["shares"]), held)
            removed_cost = (s["cost"] / held * sold) if held else 0.0
            s["shares"] -= float(t["shares"])
            s["cost"] = max(0.0, s["cost"] - removed_cost)
            s["sell_amount"] += t["amount"]
            s["realized_pnl"] += t["amount"] - removed_cost

    # 清理浮点误差导致的极小负份额
    for s in summary.values():
        if abs(s["shares"]) < 1e-6:
            s["shares"] = 0.0
        if s["cost"] < 0:
            s["cost"] = 0.0
    return summary


def _shares_for_code(trades: List[dict], fund_code: str) -> float:
    return max(0.0, _raw_shares_for_code(trades, fund_code))


def _raw_shares_for_code(trades: List[dict], fund_code: str) -> float:
    shares = 0.0
    for trade in trades:
        if trade.get("fund_code") != fund_code:
            continue
        value = float(trade.get("shares", 0.0))
        shares += value if trade.get("action") == BUY else -value
    return shares
