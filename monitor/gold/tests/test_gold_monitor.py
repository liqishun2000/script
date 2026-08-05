import math
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from monitor.gold import gold_monitor as gm


class PricingTests(unittest.TestCase):
    def test_sell_target_covers_fee_and_profit(self):
        target = gm.sell_target(900.0)
        self.assertGreater(target, 900.0)
        self.assertAlmostEqual(
            gm.net_profit_per_gram(900.0, target),
            gm.buy_cost(900.0) * gm.MIN_PROFIT_RATE,
            places=8,
        )

    def test_price_validation_rejects_invalid_values(self):
        for value in (None, "", -1, math.inf, math.nan, 99, 5001):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    gm._valid_price(value, "test", "price")


class GridLogicTests(unittest.TestCase):
    def test_empty_anchor_only_moves_up(self):
        state = {"anchor": 900.0, "lots": []}
        self.assertEqual(gm.process_tick(905.0, state), [])
        self.assertEqual(state["anchor"], 905.0)

        self.assertEqual(gm.process_tick(904.0, state), [])
        self.assertEqual(state["anchor"], 905.0)

    def test_empty_position_rise_alert_repeats_from_last_alert_price(self):
        state = {"anchor": 900.0, "lots": []}
        first_trigger = 900.0 * (1 + gm.EMPTY_RISE_ALERT_PCT)

        self.assertEqual(gm.process_tick(first_trigger - 0.01, state), [])
        first_messages = gm.process_tick(first_trigger, state)

        self.assertEqual(len(first_messages), 1)
        self.assertIn("空仓上涨提醒", first_messages[0][0])
        self.assertEqual(state["empty_rise_base"], first_trigger)

        second_trigger = first_trigger * (1 + gm.EMPTY_RISE_ALERT_PCT)
        self.assertEqual(gm.process_tick(second_trigger - 0.01, state), [])
        self.assertEqual(len(gm.process_tick(second_trigger, state)), 1)
        self.assertEqual(state["empty_rise_base"], second_trigger)

    def test_empty_position_drop_does_not_send_opposite_rise_alert(self):
        state = {
            "anchor": 950.0,
            "empty_rise_base": 900.0,
            "lots": [],
        }

        messages = gm.process_tick(938.0, state)

        self.assertEqual(len(messages), 1)
        self.assertIn("买入提醒", messages[0][0])
        self.assertNotIn("empty_rise_base", state)

    def test_drop_across_multiple_grids_adds_multiple_lots(self):
        state = {"anchor": 1000.0, "lots": []}
        messages = gm.process_tick(960.0, state)
        self.assertEqual(len(messages), 1)
        self.assertEqual(len(state["lots"]), 3)
        self.assertTrue(all(lot["price"] == 960.0 for lot in state["lots"]))

    def test_buy_is_capped_by_max_lots(self):
        lots = [{"price": 1000.0, "time": "test"} for _ in range(gm.MAX_LOTS - 1)]
        state = {"anchor": 1000.0, "lots": lots}
        gm.process_tick(900.0, state)
        self.assertEqual(len(state["lots"]), gm.MAX_LOTS)

    def test_sell_only_removes_profitable_lot(self):
        low = {"price": 800.0, "time": "test"}
        high = {"price": 900.0, "time": "test"}
        state = {"anchor": 920.0, "lots": [low, high]}
        price = gm.sell_target(800.0) + 0.01

        messages = gm.process_tick(price, state)

        self.assertEqual(len(messages), 1)
        self.assertEqual(state["lots"], [high])


class StatePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)
        self.paths = mock.patch.multiple(
            gm,
            STATE_FILE=base / "state.json",
            STATE_BACKUP_FILE=base / "state.json.bak",
            STATE_LOCK_FILE=base / "state.json.lock",
        )
        self.paths.start()

    def tearDown(self):
        self.paths.stop()
        self.temp_dir.cleanup()

    def test_atomic_save_and_load(self):
        state = {"anchor": 900.0, "lots": [{"price": 880.0, "time": "test"}]}
        gm.save_state(state)
        self.assertEqual(gm.load_state(), state)
        self.assertEqual(list(gm.STATE_FILE.parent.glob("*.tmp")), [])

    def test_corrupt_primary_recovers_from_valid_backup(self):
        first = {"anchor": 900.0, "lots": []}
        second = {"anchor": 910.0, "lots": []}
        gm.save_state(first)
        gm.save_state(second)
        gm.STATE_FILE.write_text("{broken", encoding="utf-8")

        self.assertEqual(gm.load_state(), first)

    def test_lock_serializes_concurrent_updates(self):
        gm.save_state({"anchor": 900.0, "lots": []})
        errors = []

        def add_lot(index):
            try:
                with gm.state_lock():
                    state = gm._load_state_unlocked()
                    state["lots"].append({"price": 800.0 + index, "time": "test"})
                    gm._save_state_unlocked(state)
            except Exception as exc:  # pragma: no cover - collected for assertion
                errors.append(exc)

        threads = [threading.Thread(target=add_lot, args=(index,)) for index in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertEqual(len(gm.load_state()["lots"]), 5)

    def test_invalid_state_is_rejected(self):
        invalid_states = (
            [],
            {"anchor": 900.0},
            {"anchor": 900.0, "lots": "bad"},
            {"anchor": 900.0, "lots": [{"price": -1}]},
        )
        for state in invalid_states:
            with self.subTest(state=state):
                with self.assertRaises(ValueError):
                    gm._validate_state(state)


class FetchTests(unittest.TestCase):
    def test_jd_response_is_validated(self):
        response = mock.Mock()
        response.json.return_value = {
            "resultData": {"datas": {"price": "872.34", "yesterdayPrice": "870.01"}}
        }
        with mock.patch.object(gm.session, "get", return_value=response):
            self.assertEqual(gm.fetch_price_jd(), (872.34, 870.01))
        response.raise_for_status.assert_called_once_with()

    def test_fetch_falls_back_to_sina_and_marks_source(self):
        with (
            mock.patch.object(gm, "fetch_price_jd", side_effect=RuntimeError("down")),
            mock.patch.object(gm, "fetch_price_sina", return_value=(871.0, 869.0)),
        ):
            self.assertEqual(
                gm.fetch_price(datetime(2026, 8, 5, 12, 0)),
                (871.0, 869.0, "新浪"),
            )


class RequestScheduleTests(unittest.TestCase):
    def test_only_weekdays_between_9_and_22_are_allowed(self):
        self.assertFalse(gm.is_price_request_allowed(datetime(2026, 8, 7, 8, 59)))
        self.assertTrue(gm.is_price_request_allowed(datetime(2026, 8, 7, 9, 0)))
        self.assertTrue(gm.is_price_request_allowed(datetime(2026, 8, 7, 21, 59)))
        self.assertFalse(gm.is_price_request_allowed(datetime(2026, 8, 7, 22, 0)))
        self.assertFalse(gm.is_price_request_allowed(datetime(2026, 8, 8, 12, 0)))

    def test_next_request_time_skips_weekend(self):
        self.assertEqual(
            gm.next_price_request_time(datetime(2026, 8, 7, 22, 0)),
            datetime(2026, 8, 10, 9, 0),
        )
        self.assertEqual(
            gm.next_price_request_time(datetime(2026, 8, 10, 8, 0)),
            datetime(2026, 8, 10, 9, 0),
        )

    def test_fetch_does_not_call_either_source_while_closed(self):
        with (
            mock.patch.object(gm, "fetch_price_jd") as fetch_jd,
            mock.patch.object(gm, "fetch_price_sina") as fetch_sina,
        ):
            for closed_at in (
                datetime(2026, 8, 7, 22, 0),
                datetime(2026, 8, 8, 12, 0),
            ):
                with self.subTest(closed_at=closed_at):
                    with self.assertRaises(gm.MarketClosedError):
                        gm.fetch_price(closed_at)

        fetch_jd.assert_not_called()
        fetch_sina.assert_not_called()


if __name__ == "__main__":
    unittest.main()
