"""常用技术指标计算模块。

为基金净值序列计算 MA、MACD、RSI、布林带、KDJ 等指标。
所有函数都不修改入参，返回新的 DataFrame。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _add_ma(df: pd.DataFrame, windows=(5, 10, 20, 60)) -> None:
    for w in windows:
        df[f"ma{w}"] = df["nav"].rolling(w).mean()


def _add_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> None:
    ema_fast = _ema(df["nav"], fast)
    ema_slow = _ema(df["nav"], slow)
    dif = ema_fast - ema_slow
    dea = _ema(dif, signal)
    df["macd_dif"] = dif
    df["macd_dea"] = dea
    df["macd_hist"] = (dif - dea) * 2  # 与常见行情软件保持一致的柱状图量纲


def _add_rsi(df: pd.DataFrame, period: int = 14) -> None:
    delta = df["nav"].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - 100 / (1 + rs)
    df["rsi"] = df["rsi"].fillna(50)


def _add_bollinger(df: pd.DataFrame, period: int = 20, k: float = 2.0) -> None:
    mid = df["nav"].rolling(period).mean()
    std = df["nav"].rolling(period).std(ddof=0)
    df["boll_mid"] = mid
    df["boll_up"] = mid + k * std
    df["boll_down"] = mid - k * std
    width = (df["boll_up"] - df["boll_down"]).replace(0, np.nan)
    df["boll_pct"] = (df["nav"] - df["boll_down"]) / width


def _add_kdj(df: pd.DataFrame, n: int = 9) -> None:
    """以净值序列近似计算 KDJ。

    基金没有日内最高/最低价，这里使用 N 日窗口内的最高/最低净值作为替代。
    """
    high = df["nav"].rolling(n).max()
    low = df["nav"].rolling(n).min()
    rsv = (df["nav"] - low) / (high - low).replace(0, np.nan) * 100
    rsv = rsv.fillna(50)

    k = np.full(len(df), np.nan)
    d = np.full(len(df), np.nan)
    prev_k = 50.0
    prev_d = 50.0
    for i, value in enumerate(rsv):
        if np.isnan(value):
            continue
        cur_k = (2 / 3) * prev_k + (1 / 3) * value
        cur_d = (2 / 3) * prev_d + (1 / 3) * cur_k
        k[i] = cur_k
        d[i] = cur_d
        prev_k, prev_d = cur_k, cur_d

    df["kdj_k"] = k
    df["kdj_d"] = d
    df["kdj_j"] = 3 * df["kdj_k"] - 2 * df["kdj_d"]


def compute_indicators(nav_df: pd.DataFrame) -> pd.DataFrame:
    """根据净值序列一次性计算全部指标，返回带指标列的新 DataFrame。"""
    if "nav" not in nav_df.columns:
        raise ValueError("输入 DataFrame 必须包含 'nav' 列。")

    df = nav_df.copy()
    _add_ma(df)
    _add_macd(df)
    _add_rsi(df)
    _add_bollinger(df)
    _add_kdj(df)
    return df
