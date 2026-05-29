"""信号回测：按"每日推荐操作"从 N 天前模拟到今天，评估收益与胜率。

无未来函数说明：
    MA/MACD/RSI/BOLL/KDJ/动量 全部是因果指标（只用截至当日的数据），
    因此可在完整净值序列上一次性算好指标，再逐日用"截至当日"的切片
    生成信号。第 t 日收盘后产生信号 → 用该仓位赚取第 t+1 日的收益，
    决策与收益严格错开，不会偷看未来。

两类核心指标：
    1. 策略收益 vs 买入持有：跟随信号调仓的累计收益，对比一直满仓。
    2. 信号胜率：每个方向性信号(买/卖)，在其后 forward 个交易日内
       方向是否判断正确（看多则上涨为对，看空则下跌为对）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from . import data_fetcher
from .indicators import compute_indicators
from .strategy import evaluate_signals

# 信号 → 目标仓位比例（用于收益模拟）
_TARGET_POSITION = {
    "强烈买入": 1.0,
    "买入": 0.6,
    "观望": None,    # 维持现有仓位
    "卖出": 0.3,
    "强烈卖出": 0.0,
}


@dataclass
class BacktestResult:
    code: str
    name: str
    start_date: str
    end_date: str
    trading_days: int
    strategy_return: float       # 策略累计收益率
    benchmark_return: float      # 买入持有累计收益率
    excess_return: float         # 超额收益
    max_drawdown: float          # 策略最大回撤
    n_signals: int               # 方向性信号数
    n_correct: int               # 方向判断正确数
    win_rate: Optional[float]    # 信号胜率
    beat_benchmark: bool         # 是否跑赢买入持有
    error: Optional[str] = None


def backtest_fund(
    code: str,
    lookback_days: int = 180,
    forward: int = 5,
) -> BacktestResult:
    """对单只基金做信号回测。

    lookback_days: 从多少（自然）天前开始模拟（上限建议 180=半年）。
    forward: 判定信号是否正确的前瞻交易日数。
    """
    code = str(code).strip().zfill(6)
    name = data_fetcher.fetch_fund_name(code)
    nav = data_fetcher.fetch_fund_nav(code)
    if len(nav) < 80:
        return _empty(code, name, "历史数据不足，无法回测")

    ind = compute_indicators(nav)
    navs = ind["nav"].to_numpy()
    dates = ind["date"]
    n = len(ind)

    # 确定起始下标：日期不早于 lookback_days 天前，且至少留 60 天指标预热
    start_date = dates.iloc[-1] - pd.Timedelta(days=lookback_days)
    mask = dates >= start_date
    start = int(mask.idxmax()) if mask.any() else 60
    start = max(start, 60)
    if start >= n - forward - 1:
        return _empty(code, name, "可回测区间过短")

    pos = 0.0                # 当前仓位比例(0~1)
    equity = 1.0             # 策略净值(归一)
    peak = 1.0
    max_dd = 0.0
    n_signals = 0
    n_correct = 0

    for t in range(start, n):
        rep = evaluate_signals(ind.iloc[: t + 1], code, name)
        action = rep.action

        # 信号胜率：方向性信号在 forward 日后的方向是否正确
        if action != "观望" and t + forward < n:
            fwd = navs[t + forward] / navs[t] - 1
            bullish = action in ("买入", "强烈买入")
            n_signals += 1
            if (bullish and fwd > 0) or (not bullish and fwd < 0):
                n_correct += 1

        # 按信号调整目标仓位
        target = _TARGET_POSITION.get(action)
        if target is not None:
            pos = target

        # 用当前仓位赚取「下一交易日」收益（决策与收益错开，无未来函数）
        if t + 1 < n:
            ret = navs[t + 1] / navs[t] - 1
            equity *= (1 + pos * ret)
            peak = max(peak, equity)
            max_dd = min(max_dd, equity / peak - 1)

    strat_ret = equity - 1
    bench_ret = navs[n - 1] / navs[start] - 1
    win_rate = (n_correct / n_signals) if n_signals else None

    return BacktestResult(
        code=code,
        name=name,
        start_date=str(dates.iloc[start])[:10],
        end_date=str(dates.iloc[-1])[:10],
        trading_days=n - start,
        strategy_return=strat_ret,
        benchmark_return=bench_ret,
        excess_return=strat_ret - bench_ret,
        max_drawdown=max_dd,
        n_signals=n_signals,
        n_correct=n_correct,
        win_rate=win_rate,
        beat_benchmark=strat_ret >= bench_ret,
    )


def backtest_many(
    codes: List[str],
    lookback_days: int = 180,
    forward: int = 5,
) -> Dict[str, object]:
    """批量回测多只基金，并汇总总体胜率与跑赢基准比例。"""
    results: List[BacktestResult] = []
    for c in codes:
        try:
            results.append(backtest_fund(c, lookback_days, forward))
        except Exception as exc:  # noqa: BLE001
            results.append(_empty(str(c).zfill(6), str(c), str(exc)))

    valid = [r for r in results if r.error is None and r.win_rate is not None]
    total_sig = sum(r.n_signals for r in valid)
    total_cor = sum(r.n_correct for r in valid)
    overall_win = (total_cor / total_sig) if total_sig else None
    beat_ratio = (sum(1 for r in valid if r.beat_benchmark) / len(valid)) if valid else None

    return {
        "results": results,
        "overall_win_rate": overall_win,
        "total_signals": total_sig,
        "total_correct": total_cor,
        "beat_benchmark_ratio": beat_ratio,
        "n_funds": len(valid),
    }


def _empty(code: str, name: str, err: str) -> BacktestResult:
    return BacktestResult(
        code=code, name=name, start_date="", end_date="", trading_days=0,
        strategy_return=0.0, benchmark_return=0.0, excess_return=0.0,
        max_drawdown=0.0, n_signals=0, n_correct=0, win_rate=None,
        beat_benchmark=False, error=err,
    )
