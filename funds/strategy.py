"""综合多指标打分，输出当日基金买卖建议。

设计思路：每个指标独立给出 -2 ~ +2 的子分数（负分看空、正分看多），
再按权重加权求和得到 -10 ~ +10 的综合分，最终映射为
``强烈买入 / 买入 / 观望 / 卖出 / 强烈卖出`` 五档操作建议。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd


@dataclass
class IndicatorVerdict:
    name: str
    score: float        # -2 ~ +2
    weight: float       # 该指标权重
    detail: str         # 触发原因


@dataclass
class SignalReport:
    fund_code: str
    fund_name: str
    as_of: pd.Timestamp
    nav: float
    day_change_pct: float
    composite_score: float           # -10 ~ +10
    action: str                      # 强烈买入/买入/观望/卖出/强烈卖出
    verdicts: List[IndicatorVerdict] = field(default_factory=list)
    # 分组拆解（便于解释最终评分如何得来）
    trend_score: float = 0.0         # 趋势分量 (-2~2)
    momentum_score: float = 0.0      # 动量分量 (-2~2)
    osc_score: float = 0.0           # 超买超卖原始分量 (-2~2，正=超卖看多)
    osc_adjusted: float = 0.0        # 经趋势调节后的超买超卖分量
    regime: str = ""                 # 趋势状态描述
    market_score: Optional[float] = None   # 大盘/全球情绪修正分量 (-2~2)
    market_detail: str = ""          # 大盘情绪说明

    def to_text(self) -> str:
        sep = "-" * 60
        lines = [
            sep,
            f"基金代码 : {self.fund_code}    名称: {self.fund_name}",
            f"截止日期 : {self.as_of.strftime('%Y-%m-%d')}",
            f"最新净值 : {self.nav:.4f}    当日涨跌: {self.day_change_pct:+.2f}%",
            f"综合评分 : {self.composite_score:+.2f}  /  ±10",
            f"操作建议 : 【{self.action}】",
            sep,
            "指标明细:",
        ]
        for v in self.verdicts:
            lines.append(
                f"  · {v.name:<6} 分值={v.score:+.1f} 权重={v.weight:.2f}  {v.detail}"
            )
        lines.append(sep)
        lines.append("分组拆解 (趋势优先, 超买超卖按趋势调节):")
        lines.append(f"  趋势分量   : {self.trend_score:+.2f}  ({self.regime})")
        lines.append(f"  动量分量   : {self.momentum_score:+.2f}")
        lines.append(
            f"  超买超卖   : 原始 {self.osc_score:+.2f} → 调节后 {self.osc_adjusted:+.2f}"
        )
        if self.market_score is not None:
            lines.append(
                f"  大盘/全球  : {self.market_score:+.2f}  ({self.market_detail})"
            )
        lines.append(sep)
        return "\n".join(lines)


# 各指标在新分组模型中的近似权重（仅用于展示；最终评分由分组+趋势调节得出）
#   趋势组 0.40 → MA/MACD 各 0.20；动量 0.25；超买超卖组 0.35 → RSI/KDJ/BOLL 各约 0.117
_WEIGHTS = {
    "MA":    0.20,
    "MACD":  0.20,
    "RSI":   0.117,
    "BOLL":  0.117,
    "KDJ":   0.117,
}


def _judge_ma(latest: pd.Series, prev: pd.Series) -> IndicatorVerdict:
    nav = latest["nav"]
    ma5, ma10, ma20, ma60 = latest["ma5"], latest["ma10"], latest["ma20"], latest["ma60"]
    score = 0.0
    reasons = []

    if np.isnan(ma60):
        return IndicatorVerdict("MA", 0, _WEIGHTS["MA"], "数据不足，暂无判断")

    if ma5 > ma10 > ma20 > ma60:
        score += 2
        reasons.append("均线多头排列")
    elif ma5 < ma10 < ma20 < ma60:
        score -= 2
        reasons.append("均线空头排列")
    else:
        if nav > ma20:
            score += 0.5
            reasons.append("价格站上 MA20")
        else:
            score -= 0.5
            reasons.append("价格跌破 MA20")

    # 金叉/死叉（MA5 vs MA20）
    if not np.isnan(prev["ma5"]) and not np.isnan(prev["ma20"]):
        if prev["ma5"] <= prev["ma20"] and ma5 > ma20:
            score += 1
            reasons.append("MA5 上穿 MA20 金叉")
        elif prev["ma5"] >= prev["ma20"] and ma5 < ma20:
            score -= 1
            reasons.append("MA5 下穿 MA20 死叉")

    score = float(np.clip(score, -2, 2))
    return IndicatorVerdict("MA", score, _WEIGHTS["MA"], "; ".join(reasons) or "中性")


def _judge_macd(latest: pd.Series, prev: pd.Series) -> IndicatorVerdict:
    dif, dea, hist = latest["macd_dif"], latest["macd_dea"], latest["macd_hist"]
    pdif, pdea, phist = prev["macd_dif"], prev["macd_dea"], prev["macd_hist"]

    if np.isnan(dif) or np.isnan(pdif):
        return IndicatorVerdict("MACD", 0, _WEIGHTS["MACD"], "数据不足，暂无判断")

    score = 0.0
    reasons = []

    if pdif <= pdea and dif > dea:
        score += 2
        reasons.append("DIF 上穿 DEA 金叉")
    elif pdif >= pdea and dif < dea:
        score -= 2
        reasons.append("DIF 下穿 DEA 死叉")
    else:
        if dif > dea:
            score += 0.8
            reasons.append("DIF 在 DEA 上方")
        else:
            score -= 0.8
            reasons.append("DIF 在 DEA 下方")

    if hist > phist:
        score += 0.4
        reasons.append("红柱放大/绿柱缩短")
    else:
        score -= 0.4
        reasons.append("红柱缩短/绿柱放大")

    if dif > 0 and dea > 0:
        score += 0.3
        reasons.append("零轴上方多头区")
    elif dif < 0 and dea < 0:
        score -= 0.3
        reasons.append("零轴下方空头区")

    score = float(np.clip(score, -2, 2))
    return IndicatorVerdict("MACD", score, _WEIGHTS["MACD"], "; ".join(reasons))


def _judge_rsi(latest: pd.Series) -> IndicatorVerdict:
    rsi = latest["rsi"]
    if np.isnan(rsi):
        return IndicatorVerdict("RSI", 0, _WEIGHTS["RSI"], "数据不足，暂无判断")

    if rsi >= 80:
        return IndicatorVerdict("RSI", -2, _WEIGHTS["RSI"], f"RSI={rsi:.1f} 严重超买")
    if rsi >= 70:
        return IndicatorVerdict("RSI", -1, _WEIGHTS["RSI"], f"RSI={rsi:.1f} 偏超买")
    if rsi <= 20:
        return IndicatorVerdict("RSI", 2, _WEIGHTS["RSI"], f"RSI={rsi:.1f} 严重超卖")
    if rsi <= 30:
        return IndicatorVerdict("RSI", 1, _WEIGHTS["RSI"], f"RSI={rsi:.1f} 偏超卖")
    if rsi >= 55:
        return IndicatorVerdict("RSI", 0.5, _WEIGHTS["RSI"], f"RSI={rsi:.1f} 偏强")
    if rsi <= 45:
        return IndicatorVerdict("RSI", -0.5, _WEIGHTS["RSI"], f"RSI={rsi:.1f} 偏弱")
    return IndicatorVerdict("RSI", 0, _WEIGHTS["RSI"], f"RSI={rsi:.1f} 中性区间")


def _judge_boll(latest: pd.Series) -> IndicatorVerdict:
    nav = latest["nav"]
    up, down, mid, pct = latest["boll_up"], latest["boll_down"], latest["boll_mid"], latest["boll_pct"]
    if np.isnan(up) or np.isnan(pct):
        return IndicatorVerdict("BOLL", 0, _WEIGHTS["BOLL"], "数据不足，暂无判断")

    if nav >= up:
        return IndicatorVerdict("BOLL", -2, _WEIGHTS["BOLL"], f"突破上轨({up:.4f})，回归概率高")
    if nav <= down:
        return IndicatorVerdict("BOLL", 2, _WEIGHTS["BOLL"], f"跌破下轨({down:.4f})，超跌反弹概率高")
    if pct >= 0.8:
        return IndicatorVerdict("BOLL", -1, _WEIGHTS["BOLL"], f"位于上轨附近(%B={pct:.2f})")
    if pct <= 0.2:
        return IndicatorVerdict("BOLL", 1, _WEIGHTS["BOLL"], f"位于下轨附近(%B={pct:.2f})")
    if nav > mid:
        return IndicatorVerdict("BOLL", 0.3, _WEIGHTS["BOLL"], f"位于中轨上方(%B={pct:.2f})")
    return IndicatorVerdict("BOLL", -0.3, _WEIGHTS["BOLL"], f"位于中轨下方(%B={pct:.2f})")


def _judge_kdj(latest: pd.Series, prev: pd.Series) -> IndicatorVerdict:
    k, d, j = latest["kdj_k"], latest["kdj_d"], latest["kdj_j"]
    pk, pd_ = prev["kdj_k"], prev["kdj_d"]
    if np.isnan(k) or np.isnan(pk):
        return IndicatorVerdict("KDJ", 0, _WEIGHTS["KDJ"], "数据不足，暂无判断")

    score = 0.0
    reasons = [f"K={k:.1f} D={d:.1f} J={j:.1f}"]

    if pk <= pd_ and k > d:
        score += 1.5
        reasons.append("K 上穿 D 金叉")
    elif pk >= pd_ and k < d:
        score -= 1.5
        reasons.append("K 下穿 D 死叉")

    if j <= 0:
        score += 1
        reasons.append("J 值超卖(<=0)")
    elif j >= 100:
        score -= 1
        reasons.append("J 值超买(>=100)")

    if k <= 20 and d <= 20:
        score += 0.5
        reasons.append("KD 双双低位")
    elif k >= 80 and d >= 80:
        score -= 0.5
        reasons.append("KD 双双高位")

    score = float(np.clip(score, -2, 2))
    return IndicatorVerdict("KDJ", score, _WEIGHTS["KDJ"], "; ".join(reasons))


def _judge_momentum(df: pd.DataFrame) -> IndicatorVerdict:
    """中期动量：综合 20/60 日收益率与距 60 日高点的回撤。

    技术指标多为短期摆动，单看它们对趋势型基金容易过早离场；
    引入中期动量分量，确认资金是否处于上升通道。
    """
    nav = df["nav"].to_numpy()
    n = len(nav)
    if n < 25:
        return IndicatorVerdict("动量", 0, 0.25, "数据不足，暂无判断")

    cur = nav[-1]
    r20 = cur / nav[-21] - 1 if n >= 21 else 0.0
    r60 = cur / nav[-61] - 1 if n >= 61 else r20

    score = 0.0
    reasons = [f"20日{r20:+.1%}"]
    if n >= 61:
        reasons.append(f"60日{r60:+.1%}")

    if r20 > 0 and r60 > 0:
        score += 1.5
        reasons.append("中期上升通道")
    elif r20 < 0 and r60 < 0:
        score -= 1.5
        reasons.append("中期下降通道")
    elif r20 > 0:
        score += 0.5
    else:
        score -= 0.5

    # 距 60 日高点的回撤：贴近高点动量强，深度回撤则走弱
    window = nav[-60:] if n >= 60 else nav
    high = float(window.max())
    drawdown = cur / high - 1 if high else 0.0
    if drawdown >= -0.03:
        score += 0.5
        reasons.append("贴近阶段高点")
    elif drawdown <= -0.15:
        score -= 0.5
        reasons.append(f"深度回撤{drawdown:.0%}")

    score = float(np.clip(score, -2, 2))
    return IndicatorVerdict("动量", score, 0.25, "; ".join(reasons))


# 分组权重（趋势优先；超买超卖会按趋势状态动态调节，而非简单对冲）
_GROUP_W = {"trend": 0.40, "momentum": 0.25, "osc": 0.35}
_OSC_DAMP = 0.6     # 与趋势冲突时，超买超卖信号被削弱（不逆势）
_OSC_BOOST = 1.15   # 与趋势同向时，超买超卖信号被增强（顺势加分）


def _score_to_action(score: float) -> str:
    if score >= 5:
        return "强烈买入"
    if score >= 2:
        return "买入"
    if score <= -5:
        return "强烈卖出"
    if score <= -2:
        return "卖出"
    return "观望"


# 大盘/全球情绪在最终评分中的权重（个基技术面占主导，大盘作为环境修正）
_MARKET_WEIGHT = 0.15


def evaluate_signals(
    indicator_df: pd.DataFrame,
    fund_code: str,
    fund_name: str,
    market_score: Optional[float] = None,
    market_detail: str = "",
) -> SignalReport:
    """根据带指标的 DataFrame 输出当日的买卖信号报告。

    market_score: 可选的大盘/全球情绪分 (-2~2)。传入后会以 _MARKET_WEIGHT
    的权重与个基技术评分融合（仅建议对权益类基金传入）。
    """
    if len(indicator_df) < 2:
        raise ValueError("数据点不足，无法生成信号。")

    latest = indicator_df.iloc[-1]
    prev = indicator_df.iloc[-2]

    ma_v = _judge_ma(latest, prev)
    macd_v = _judge_macd(latest, prev)
    mom_v = _judge_momentum(indicator_df)
    rsi_v = _judge_rsi(latest)
    boll_v = _judge_boll(latest)
    kdj_v = _judge_kdj(latest, prev)
    verdicts = [ma_v, macd_v, mom_v, rsi_v, boll_v, kdj_v]

    # —— 分组聚合 ——
    # 趋势：MA 与 MACD（同为趋势跟随类，合成一个分量）
    trend = (ma_v.score + macd_v.score) / 2
    # 动量：中期收益
    momentum = mom_v.score
    # 超买超卖：RSI / KDJ / BOLL（正=超卖看多，负=超买看空）
    osc = (rsi_v.score + kdj_v.score + boll_v.score) / 3

    # —— 趋势状态判定 ——（趋势与动量共同决定）
    regime_val = 0.7 * trend + 0.3 * momentum
    if regime_val >= 1.0:
        regime = "强势上升"
    elif regime_val >= 0.3:
        regime = "偏多"
    elif regime_val <= -1.0:
        regime = "强势下行"
    elif regime_val <= -0.3:
        regime = "偏空"
    else:
        regime = "震荡"

    # —— 超买超卖按趋势调节：顺势增强、逆势削弱 ——
    if regime_val > 0 and osc < 0:        # 上升趋势中的超买：仅作温和提示，不逆势做空
        osc_adj = osc * _OSC_DAMP
    elif regime_val < 0 and osc > 0:      # 下降趋势中的超卖：谨慎，不抄底
        osc_adj = osc * _OSC_DAMP
    elif regime_val > 0 and osc > 0:      # 上升趋势中的回调/超卖：顺势买点，增强
        osc_adj = min(osc * _OSC_BOOST, 2.0)
    elif regime_val < 0 and osc < 0:      # 下降趋势中的超买：顺势卖点，增强
        osc_adj = max(osc * _OSC_BOOST, -2.0)
    else:
        osc_adj = osc

    final = (_GROUP_W["trend"] * trend
             + _GROUP_W["momentum"] * momentum
             + _GROUP_W["osc"] * osc_adj)

    # 融入大盘/全球情绪（系统性环境修正）
    if market_score is not None:
        final = (1 - _MARKET_WEIGHT) * final + _MARKET_WEIGHT * float(market_score)

    composite = float(np.clip(final, -2, 2) * 5)

    day_change = latest.get("pct_change")
    if pd.isna(day_change):
        day_change = (latest["nav"] / prev["nav"] - 1) * 100

    return SignalReport(
        fund_code=fund_code,
        fund_name=fund_name,
        as_of=latest["date"],
        nav=float(latest["nav"]),
        day_change_pct=float(day_change),
        composite_score=composite,
        action=_score_to_action(composite),
        verdicts=verdicts,
        trend_score=round(trend, 3),
        momentum_score=round(momentum, 3),
        osc_score=round(osc, 3),
        osc_adjusted=round(osc_adj, 3),
        regime=regime,
        market_score=round(market_score, 3) if market_score is not None else None,
        market_detail=market_detail,
    )
