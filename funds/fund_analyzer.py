"""命令行入口：拉取国内基金数据 -> 计算指标 -> 输出当日买卖建议。

用法示例:
    python -m funds.fund_analyzer 000001 110022 519066
    python -m funds.fund_analyzer            # 不传参时使用默认示例基金
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, List

# 同时兼容两种运行方式：
#   1) python -m funds.fund_analyzer  (作为包模块运行，使用相对导入)
#   2) python funds/fund_analyzer.py  (作为脚本运行，回退到绝对导入)
if __package__:
    from .data_fetcher import fetch_fund_nav, fetch_fund_name
    from .indicators import compute_indicators
    from .strategy import SignalReport, evaluate_signals
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from funds.data_fetcher import fetch_fund_nav, fetch_fund_name
    from funds.indicators import compute_indicators
    from funds.strategy import SignalReport, evaluate_signals


DEFAULT_FUNDS: List[str] = ["000001", "110022", "519066"]


def analyze_fund(fund_code: str) -> SignalReport:
    """对单只基金完成 数据 -> 指标 -> 信号 的完整流水线。"""
    fund_code = fund_code.strip().zfill(6)
    nav_df = fetch_fund_nav(fund_code)
    indicator_df = compute_indicators(nav_df)
    fund_name = fetch_fund_name(fund_code)
    return evaluate_signals(indicator_df, fund_code, fund_name)


def analyze_funds(fund_codes: Iterable[str]) -> List[SignalReport]:
    reports: List[SignalReport] = []
    for code in fund_codes:
        try:
            reports.append(analyze_fund(code))
        except Exception as exc:  # noqa: BLE001
            print(f"[!] 基金 {code} 分析失败: {exc}", file=sys.stderr)
    return reports


def _print_summary(reports: List[SignalReport]) -> None:
    if not reports:
        print("没有可输出的分析结果。")
        return

    for r in reports:
        print(r.to_text())
        print()

    print("=" * 60)
    print("汇总建议:")
    header = f"  {'代码':<8}{'名称':<22}{'净值':>8}{'涨跌%':>8}{'评分':>8}  操作"
    print(header)
    for r in reports:
        name = r.fund_name if len(r.fund_name) <= 18 else r.fund_name[:17] + "…"
        print(
            f"  {r.fund_code:<8}{name:<22}{r.nav:>8.4f}"
            f"{r.day_change_pct:>+8.2f}{r.composite_score:>+8.2f}  【{r.action}】"
        )
    print("=" * 60)
    print("注: 本工具仅基于历史净值的技术指标进行打分，不构成投资建议。")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fund_analyzer",
        description="国内公募基金技术指标分析与买卖信号生成工具",
    )
    parser.add_argument(
        "codes",
        nargs="*",
        help="一个或多个基金代码（6 位数字），不传则使用内置示例基金",
    )
    return parser


def main(argv: List[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    codes = args.codes or DEFAULT_FUNDS
    print(f"开始分析 {len(codes)} 只基金: {', '.join(codes)}\n")
    reports = analyze_funds(codes)
    _print_summary(reports)
    return 0 if reports else 1


if __name__ == "__main__":
    raise SystemExit(main())
