from __future__ import annotations

import copy
import sys
import threading
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pandas as pd


sys.modules.setdefault("akshare", types.ModuleType("akshare"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from funds import backtest, data_fetcher, dead_funds, storage, trade_log  # noqa: E402
from funds.indicators import compute_indicators  # noqa: E402
from funds.portfolio import advise_many  # noqa: E402
from funds.strategy import SignalReport, _score_to_action  # noqa: E402
from funds.validation import normalize_fund_code  # noqa: E402


class CoreTests(unittest.TestCase):
    def test_rsi_handles_one_sided_and_flat_series(self):
        dates = pd.date_range("2026-01-01", periods=80)
        rising = pd.DataFrame({"date": dates, "nav": range(1, 81)})
        flat = pd.DataFrame({"date": dates, "nav": [1.0] * 80})
        self.assertEqual(compute_indicators(rising)["rsi"].iloc[-1], 100.0)
        self.assertEqual(compute_indicators(flat)["rsi"].iloc[-1], 50.0)

    def test_fund_code_validation(self):
        self.assertEqual(normalize_fund_code("42"), "000042")
        for value in ("", "abc", "1234567", "12/34"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_fund_code(value)

    def test_atomic_update_keeps_all_thread_changes(self):
        memory = {}

        def load_unlocked(name, default):
            return copy.deepcopy(memory.get(name, default))

        def save_unlocked(name, data):
            memory[name] = copy.deepcopy(data)

        def add_key(index):
            def update(data):
                data[str(index)] = index
                return data
            storage.update_json("state.json", {}, update)

        with patch.object(storage, "_load_unlocked", load_unlocked), patch.object(
            storage, "_save_unlocked", save_unlocked
        ):
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(add_key, range(8)))
        self.assertEqual(len(memory["state.json"]), 8)

    def test_legacy_dead_fund_records_are_not_confirmed(self):
        records = {
            "000001": {"reason": "无净值数据", "date": "2026-05-29"},
            "000002": {"reason": "人工确认", "confirmed": True},
        }
        with patch.object(dead_funds, "_all", return_value=records):
            self.assertEqual(dead_funds.dead_set(), {"000002"})

    def test_unknown_provider_response_is_not_classified_as_empty_fund(self):
        response = types.SimpleNamespace(
            text="temporary provider page",
            raise_for_status=lambda: None,
        )
        with patch.object(data_fetcher.requests, "get", return_value=response):
            with self.assertRaises(data_fetcher.FundDataUnavailable):
                data_fetcher.fetch_fund_nav("1")

        response.text = "var Data_netWorthTrend = [];"
        with patch.object(data_fetcher.requests, "get", return_value=response):
            with self.assertRaises(data_fetcher.FundDataEmpty):
                data_fetcher.fetch_fund_nav("1")

    def test_trade_validation_and_oversell(self):
        memory = {}

        def load(name, default):
            return copy.deepcopy(memory.get(name, default))

        def update(name, default, updater):
            current = load(name, default)
            result = updater(current)
            memory[name] = copy.deepcopy(current if result is None else result)
            return copy.deepcopy(memory[name])

        with patch.object(storage, "load_json", load), patch.object(
            storage, "update_json", update
        ):
            with self.assertRaises(ValueError):
                trade_log.add_trade("1", trade_log.BUY, -100, 1)
            trade_log.add_trade("1", trade_log.BUY, 100, 1)
            with self.assertRaises(ValueError):
                trade_log.add_trade("1", trade_log.SELL, 101, 1)
            trade_log.add_trade("1", trade_log.SELL, 50, 1)
            buy_id = memory["trades.json"][0]["id"]
            with self.assertRaises(ValueError):
                trade_log.delete_trade(buy_id)

    def test_batch_advice_does_not_exceed_total_capital(self):
        reports = [
            SignalReport(
                str(i).zfill(6), "x", pd.Timestamp("2026-01-01"), 1.0,
                0.0, 6.0, _score_to_action(6.0),
            )
            for i in range(5)
        ]
        with patch.object(trade_log, "holding_summary", return_value={}):
            advice = advise_many(reports, 10_000, reserved_value=5_000)
        purchases = sum(a.suggest_amount for a in advice.values())
        self.assertLessEqual(purchases, 5_000)

    def test_backtest_does_not_earn_pre_execution_jump(self):
        dates = pd.date_range("2025-01-01", periods=100)
        navs = [1.0] * 61 + [2.0] * 39
        frame = pd.DataFrame({"date": dates, "nav": navs, "pct_change": 0.0})
        report = types.SimpleNamespace(action=_score_to_action(6.0))
        with patch.object(
            backtest.data_fetcher, "fetch_fund_nav", return_value=frame
        ), patch.object(
            backtest.data_fetcher, "fetch_fund_name", return_value="test"
        ), patch.object(backtest, "evaluate_signals", return_value=report):
            result = backtest.backtest_fund("1", lookback_days=1000, forward=5)
        self.assertAlmostEqual(result.strategy_return, -0.001, places=8)
        self.assertAlmostEqual(result.benchmark_return, 0.0, places=8)


if __name__ == "__main__":
    unittest.main()
