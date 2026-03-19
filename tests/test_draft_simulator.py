from __future__ import annotations

import json
import unittest
from pathlib import Path

from apps.api.app.main import (
    TradeEvaluateRequest,
    _build_default_original_team_order,
    _build_draft_order_from_original_order,
    _evaluate_trade_request,
)


ROOT = Path(__file__).resolve().parents[3]
DRAFT_DATA_PATH = ROOT / "data" / "draft" / "draft_data.json"


class DraftDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(DRAFT_DATA_PATH.read_text(encoding="utf-8"))

    def test_imported_workbook_has_expected_counts(self) -> None:
        self.assertEqual(len(self.payload["players"]), 64)
        self.assertEqual(len(self.payload["teams"]), 30)
        self.assertEqual(len(self.payload["draft_order"]), 60)

    def test_ranked_prospects_sort_before_unranked(self) -> None:
        projected = [player.get("projected_pick") for player in self.payload["players"]]
        first_missing = projected.index(None)
        self.assertTrue(all(value is not None for value in projected[:first_missing]))
        self.assertTrue(all(value is None for value in projected[first_missing:]))

    def test_numeric_stats_are_parsed(self) -> None:
        first = self.payload["players"][0]
        self.assertIsInstance(first["height_cm"], int)
        self.assertIsInstance(first["weight_kg"], int)
        self.assertIsInstance(first["summary_stats"]["points"], float)
        self.assertIsInstance(first["advanced_stats"]["per"], float)

    def test_build_draft_order_from_original_order_resorts_rounds(self) -> None:
        default_original = _build_default_original_team_order(self.payload["draft_order"])
        flipped = list(reversed(default_original))
        rebuilt = _build_draft_order_from_original_order(self.payload, flipped)
        first_round = rebuilt[:30]
        self.assertEqual(first_round[0]["original_team"], flipped[0])
        self.assertEqual(first_round[-1]["original_team"], flipped[-1])
        self.assertEqual(first_round[0]["pick"], 1)
        self.assertEqual(rebuilt[-1]["pick"], 60)


class TradeEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(DRAFT_DATA_PATH.read_text(encoding="utf-8"))

    def evaluate(self, **kwargs):
        payload = TradeEvaluateRequest(**kwargs)
        return _evaluate_trade_request(self.payload, payload)

    def test_delta_99_trade_is_accepted(self) -> None:
        result = self.evaluate(
            participants=[
                {
                    "team_id": "ATL",
                    "assets": [{"id": "pick-24", "asset_type": "pick", "pick_no": 24, "recipient_team_id": "BOS"}],
                },
                {
                    "team_id": "BOS",
                    "assets": [{"id": "pick-53", "asset_type": "pick", "pick_no": 53, "recipient_team_id": "ATL"}],
                },
            ]
        )
        self.assertEqual(result["delta"], 99)
        self.assertEqual(result["status"], "accepted")

    def test_delta_100_trade_is_accepted(self) -> None:
        result = self.evaluate(
            participants=[
                {
                    "team_id": "ATL",
                    "assets": [{"id": "pick-21", "asset_type": "pick", "pick_no": 21, "recipient_team_id": "BOS"}],
                },
                {
                    "team_id": "BOS",
                    "assets": [{"id": "pick-59", "asset_type": "pick", "pick_no": 59, "recipient_team_id": "ATL"}],
                },
            ]
        )
        self.assertEqual(result["delta"], 100)
        self.assertEqual(result["status"], "accepted")

    def test_delta_101_trade_is_rejected(self) -> None:
        result = self.evaluate(
            participants=[
                {
                    "team_id": "ATL",
                    "assets": [{"id": "pick-27", "asset_type": "pick", "pick_no": 27, "recipient_team_id": "BOS"}],
                },
                {
                    "team_id": "BOS",
                    "assets": [{"id": "pick-36", "asset_type": "pick", "pick_no": 36, "recipient_team_id": "ATL"}],
                },
            ]
        )
        self.assertEqual(result["delta"], 101)
        self.assertEqual(result["status"], "rejected")

    def test_three_team_trade_can_route_assets_independently(self) -> None:
        result = self.evaluate(
            participants=[
                {
                    "team_id": "ATL",
                    "assets": [
                        {"id": "pick-24", "asset_type": "pick", "pick_no": 24, "recipient_team_id": "BOS"},
                        {"id": "pick-55", "asset_type": "pick", "pick_no": 55, "recipient_team_id": "CHA"},
                    ],
                },
                {
                    "team_id": "BOS",
                    "assets": [{"id": "pick-53", "asset_type": "pick", "pick_no": 53, "recipient_team_id": "ATL"}],
                },
                {
                    "team_id": "CHA",
                    "assets": [{"id": "pick-58", "asset_type": "pick", "pick_no": 58, "recipient_team_id": "ATL"}],
                },
            ]
        )
        self.assertEqual(result["delta"], 99)
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(len(result["team_summaries"]), 3)

    def test_more_than_five_teams_is_rejected(self) -> None:
        result = self.evaluate(
            participants=[
                {"team_id": "ATL", "assets": [{"id": "pick-24", "asset_type": "pick", "pick_no": 24, "recipient_team_id": "BOS"}]},
                {"team_id": "BOS", "assets": [{"id": "pick-53", "asset_type": "pick", "pick_no": 53, "recipient_team_id": "CHA"}]},
                {"team_id": "CHA", "assets": [{"id": "pick-55", "asset_type": "pick", "pick_no": 55, "recipient_team_id": "CHI"}]},
                {"team_id": "CHI", "assets": [{"id": "pick-58", "asset_type": "pick", "pick_no": 58, "recipient_team_id": "CLE"}]},
                {"team_id": "CLE", "assets": [{"id": "pick-59", "asset_type": "pick", "pick_no": 59, "recipient_team_id": "DET"}]},
                {"team_id": "DET", "assets": [{"id": "pick-60", "asset_type": "pick", "pick_no": 60, "recipient_team_id": "ATL"}]},
            ]
        )
        self.assertEqual(result["status"], "rejected")

    def test_invalid_routes_and_empty_side_are_rejected(self) -> None:
        self_route = self.evaluate(
            participants=[
                {"team_id": "ATL", "assets": [{"id": "pick-24", "asset_type": "pick", "pick_no": 24, "recipient_team_id": "ATL"}]},
                {"team_id": "BOS", "assets": [{"id": "pick-53", "asset_type": "pick", "pick_no": 53, "recipient_team_id": "ATL"}]},
            ]
        )
        empty_side = self.evaluate(
            participants=[
                {"team_id": "ATL", "assets": []},
                {"team_id": "BOS", "assets": [{"id": "pick-53", "asset_type": "pick", "pick_no": 53, "recipient_team_id": "ATL"}]},
            ]
        )
        self.assertEqual(self_route["status"], "rejected")
        self.assertEqual(empty_side["status"], "rejected")

    def test_player_assets_trigger_manual_review(self) -> None:
        result = self.evaluate(
            participants=[
                {
                    "team_id": "ATL",
                    "assets": [
                        {"id": "pick-24", "asset_type": "pick", "pick_no": 24, "recipient_team_id": "BOS"},
                        {
                            "id": "nba-1",
                            "name": "Test Veteran",
                            "asset_type": "roster_player",
                            "recipient_team_id": "BOS",
                        },
                    ],
                },
                {
                    "team_id": "BOS",
                    "assets": [{"id": "pick-53", "asset_type": "pick", "pick_no": 53, "recipient_team_id": "ATL"}],
                },
            ]
        )
        self.assertEqual(result["delta"], 99)
        self.assertEqual(result["status"], "manual_review_required")
        self.assertEqual(len(result["ignored_assets"]), 1)

    def test_asset_recipient_must_be_in_participant_list(self) -> None:
        result = self.evaluate(
            participants=[
                {
                    "team_id": "ATL",
                    "assets": [{"id": "pick-24", "asset_type": "pick", "pick_no": 24, "recipient_team_id": "DET"}],
                },
                {
                    "team_id": "BOS",
                    "assets": [{"id": "pick-53", "asset_type": "pick", "pick_no": 53, "recipient_team_id": "ATL"}],
                },
            ]
        )
        self.assertEqual(result["status"], "rejected")


if __name__ == "__main__":
    unittest.main()
