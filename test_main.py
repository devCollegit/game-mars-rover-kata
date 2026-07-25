import unittest

from fastapi.testclient import TestClient

import main


class MarsRoverUpgradeTests(unittest.TestCase):
    def setUp(self) -> None:
        main.session_games.clear()

    def test_normalize_defaults(self) -> None:
        self.assertEqual(main.normalize_difficulty("unknown"), "normal")
        self.assertEqual(main.normalize_theme("invalid"), "space")

    def test_seed_reproducibility(self) -> None:
        payload = main.InitRequest(width=8, height=8, difficulty="hard", stage=2, seed=42, theme="space")
        first = main._new_game_state(payload, "a")
        second = main._new_game_state(payload, "b")

        self.assertEqual(first["grid"], second["grid"])
        self.assertEqual(first["goal"], second["goal"])
        self.assertEqual(first["samples"], second["samples"])

    def test_theme_collision_rule_for_dino(self) -> None:
        state = {
            "grid": [
                [1, 1, 1, 1, 1],
                [1, 0, 0, 0, 1],
                [1, 0, 0, 0, 1],
                [1, 0, 0, 0, 1],
                [1, 1, 1, 1, 1],
            ],
            "rover": {"row": 1, "col": 1},
            "theme": "dino",
            "samples": [],
            "samples_collected": 0,
            "supplies": set(),
            "hazards": set(),
            "boosts": set(),
            "moves_made": 0,
        }

        rover, result, fuel_delta, path, events = main.move_rover(state, ["U"])
        self.assertEqual(result, "Warning")
        self.assertEqual(fuel_delta, 8)
        self.assertEqual(rover, {"row": 1, "col": 1})
        self.assertEqual(path, [])
        self.assertEqual(events, [])

    def test_mission_success_requires_multiple_objectives(self) -> None:
        state = {
            "fuel": 10,
            "fuel_limit": 90,
            "samples_collected": 2,
            "samples_total": 2,
            "moves_made": 12,
            "survival_turns_required": 12,
            "rover": {"row": 2, "col": 2},
            "goal": {"row": 2, "col": 2},
        }
        self.assertEqual(main.evaluate_mission_status(state), "SUCCESS")

    def test_session_isolation_and_replay_endpoint(self) -> None:
        client_a = TestClient(main.app)
        init_response = client_a.post(
            "/api/init",
            json={"width": 6, "height": 6, "difficulty": "easy", "stage": 1, "seed": 55, "theme": "space"},
        )
        self.assertEqual(init_response.status_code, 200)

        replay_response = client_a.get("/api/replay")
        self.assertEqual(replay_response.status_code, 200)
        replay_payload = replay_response.json()
        self.assertEqual(replay_payload["seed"], 55)

        client_b = TestClient(main.app)
        state_response = client_b.get("/api/state")
        self.assertEqual(state_response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
