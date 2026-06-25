"""仓位管理与资金分配建议。

在技术指标信号（SignalReport）的基础上，结合：
  - 用户设定的总仓位金额（total_capital）；
  - 由交易记录推算出的当前持仓市值；
给出"应买入/卖出多少金额"的具体操作建议。

核心思路——目标仓位法：
  每只基金根据其信号档位映射一个"目标占总资金比例"，
  再与当前实际占比对比，差额即为建议加仓/减仓金额。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from . import storage, trade_log
from .strategy import SignalReport

_CONFIG_FILE = "config.json"

# 各信号档位对应的"单只基金目标仓位占总资金比例"
_TARGET_RATIO = {
    "强烈买入": 0.25,
    "买入": 0.15,
    "观望": None,    # None 表示维持现状
    "卖出": 0.05,
    "强烈卖出": 0.0,
}

# 单只基金允许的最大仓位占比（风险控制上限）
_MAX_SINGLE_RATIO = 0.30
# 单次操作的最小金额门槛，低于该值视为"无需操作"
_MIN_TRADE_AMOUNT = 100.0


@dataclass
class PositionAdvice:
    fund_code: str
    fund_name: str
    action: str               # 信号操作建议
    current_value: float      # 当前持仓市值（估算）
    current_ratio: float      # 当前占总资金比例
    target_ratio: Optional[float]
    suggest_action: str       # 加仓/减仓/维持/清仓
    suggest_amount: float     # 建议操作金额（正数）
    reason: str


def get_total_capital() -> float:
    cfg = storage.load_json(_CONFIG_FILE, {})
    return float(cfg.get("total_capital", 0.0))


def set_total_capital(amount: float) -> None:
    cfg = storage.load_json(_CONFIG_FILE, {})
    cfg["total_capital"] = float(amount)
    storage.save_json(_CONFIG_FILE, cfg)


def current_value(fund_code: str, latest_nav: float) -> float:
    """根据交易记录推算的净份额 × 最新净值，得到当前持仓市值。"""
    summary = trade_log.holding_summary().get(fund_code)
    if not summary:
        return 0.0
    return max(0.0, summary["shares"] * latest_nav)


def advise(report: SignalReport, total_capital: Optional[float] = None) -> PositionAdvice:
    """针对单只基金，结合信号与资金状况给出仓位操作建议。"""
    if total_capital is None:
        total_capital = get_total_capital()

    cur_val = current_value(report.fund_code, report.nav)
    cur_ratio = (cur_val / total_capital) if total_capital > 0 else 0.0
    target_ratio = _TARGET_RATIO.get(report.action)

    # 总资金未设置时只能给方向，不能给金额
    if total_capital <= 0:
        return PositionAdvice(
            fund_code=report.fund_code,
            fund_name=report.fund_name,
            action=report.action,
            current_value=cur_val,
            current_ratio=cur_ratio,
            target_ratio=target_ratio,
            suggest_action="维持",
            suggest_amount=0.0,
            reason="未设置总仓位金额，无法计算具体操作金额。",
        )

    if target_ratio is None:
        return PositionAdvice(
            fund_code=report.fund_code,
            fund_name=report.fund_name,
            action=report.action,
            current_value=cur_val,
            current_ratio=cur_ratio,
            target_ratio=None,
            suggest_action="维持",
            suggest_amount=0.0,
            reason=f"信号为「{report.action}」，建议维持当前仓位({cur_ratio:.1%})。",
        )

    target_ratio = min(target_ratio, _MAX_SINGLE_RATIO)
    target_val = total_capital * target_ratio

    # —— 方向感知：买入信号只会加仓，卖出信号只会减/清仓，绝不反向 ——
    if report.action in ("买入", "强烈买入"):
        diff = target_val - cur_val
        if diff > _MIN_TRADE_AMOUNT:
            suggest_action = "加仓"
            amount = diff
            reason = (
                f"信号「{report.action}」，目标仓位{target_ratio:.1%}，"
                f"当前{cur_ratio:.1%}，建议加仓 {amount:,.0f} 元。"
            )
        else:
            suggest_action = "维持"
            amount = 0.0
            reason = (
                f"信号「{report.action}」，但当前仓位({cur_ratio:.1%})"
                f"已达目标({target_ratio:.1%})，建议维持。"
            )
    else:  # 卖出 / 强烈卖出：只考虑减仓或清仓，空仓时观望不买
        if cur_val <= _MIN_TRADE_AMOUNT:
            suggest_action = "维持"
            amount = 0.0
            reason = (
                f"信号「{report.action}」，且当前基本无持仓，"
                f"建议空仓观望，不宜买入。"
            )
        else:
            diff = cur_val - target_val
            if diff <= _MIN_TRADE_AMOUNT:
                suggest_action = "维持"
                amount = 0.0
                reason = (
                    f"信号「{report.action}」，当前仓位({cur_ratio:.1%})"
                    f"已不高于目标({target_ratio:.1%})，可维持观望。"
                )
            elif target_ratio == 0.0:
                suggest_action = "清仓"
                amount = cur_val
                reason = f"信号「{report.action}」，建议清仓，卖出约 {amount:,.0f} 元。"
            else:
                suggest_action = "减仓"
                amount = diff
                reason = (
                    f"信号「{report.action}」，目标仓位{target_ratio:.1%}，"
                    f"当前{cur_ratio:.1%}，建议减仓 {amount:,.0f} 元。"
                )

    return PositionAdvice(
        fund_code=report.fund_code,
        fund_name=report.fund_name,
        action=report.action,
        current_value=cur_val,
        current_ratio=cur_ratio,
        target_ratio=target_ratio,
        suggest_action=suggest_action,
        suggest_amount=amount,
        reason=reason,
    )


def portfolio_overview(reports_navs: Dict[str, float]) -> dict:
    """汇总整体仓位情况。

    reports_navs: {fund_code: latest_nav}
    返回 {total_capital, invested_value, cash, invested_ratio}。
    """
    total = get_total_capital()
    invested = 0.0
    for code, nav in reports_navs.items():
        invested += current_value(code, nav)
    invested = round(invested, 2)
    cash = round(total - invested, 2) if total > 0 else 0.0
    ratio = (invested / total) if total > 0 else 0.0
    return {
        "total_capital": total,
        "invested_value": invested,
        "cash": cash,
        "invested_ratio": ratio,
    }
