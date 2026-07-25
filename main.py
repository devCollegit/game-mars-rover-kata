import random
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field


class InitRequest(BaseModel):
    width: int = Field(ge=3, le=20)
    height: int = Field(ge=3, le=20)
    difficulty: str = Field(default="normal")
    stage: int = Field(default=1, ge=1, le=99)
    seed: int | None = None
    theme: str = Field(default="space")


class CommandRequest(BaseModel):
    commands: list[str] = Field(min_length=1, max_length=100)
    theme: str = Field(default="space")


app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
SESSION_COOKIE_NAME = "mars-rover-session-id"

DIFFICULTY_SETTINGS = {
    "easy": {
        "obstacle_ratio": 0.2,
        "fuel_limit": 100,
        "sample_count": 1,
        "survival_turns": 8,
        "supply_count": 3,
        "hazard_count": 1,
        "boost_count": 2,
    },
    "normal": {
        "obstacle_ratio": 0.3,
        "fuel_limit": 90,
        "sample_count": 2,
        "survival_turns": 12,
        "supply_count": 2,
        "hazard_count": 2,
        "boost_count": 1,
    },
    "hard": {
        "obstacle_ratio": 0.38,
        "fuel_limit": 75,
        "sample_count": 3,
        "survival_turns": 16,
        "supply_count": 1,
        "hazard_count": 3,
        "boost_count": 1,
    },
}

THEME_EFFECTS = {
    "space": {
        "collision_cost": 10,
        "hazard_penalty": 3,
        "supply_gain": 12,
        "extra_move_drain": 0,
    },
    "dino": {
        "collision_cost": 8,
        "hazard_penalty": 2,
        "supply_gain": 10,
        "extra_move_drain": 0,
    },
    "shark": {
        "collision_cost": 10,
        "hazard_penalty": 3,
        "supply_gain": 12,
        "extra_move_drain": 1,
    },
    "croc": {
        "collision_cost": 10,
        "hazard_penalty": 1,
        "supply_gain": 10,
        "extra_move_drain": 0,
    },
    "bunny": {
        "collision_cost": 10,
        "hazard_penalty": 3,
        "supply_gain": 18,
        "extra_move_drain": 0,
    },
}

STAGE_REWARDS = {
    1: {"theme": "dino", "skin": "Volcano Scout", "title": "탐험 시작자"},
    2: {"theme": "shark", "skin": "Bubble Rider", "title": "지형 분석가"},
    3: {"theme": "croc", "skin": "Swamp Tracker", "title": "생존 전문가"},
    4: {"theme": "bunny", "skin": "Carrot Runner", "title": "마스터 탐험가"},
}

GameState = dict[str, object]
session_games: dict[str, GameState] = {}


def normalize_difficulty(difficulty: str) -> str:
    normalized = difficulty.strip().lower()
    return normalized if normalized in DIFFICULTY_SETTINGS else "normal"


def normalize_theme(theme: str) -> str:
    normalized = theme.strip().lower()
    return normalized if normalized in THEME_EFFECTS else "space"


def build_grid(height: int, width: int, obstacle_ratio: float, rng: random.Random) -> list[list[int]]:
    grid: list[list[int]] = []

    for row_index in range(height):
        row: list[int] = []
        for col_index in range(width):
            is_border = (
                row_index == 0
                or col_index == 0
                or row_index == height - 1
                or col_index == width - 1
            )
            if is_border:
                row.append(1)
            else:
                row.append(1 if rng.random() < obstacle_ratio else 0)
        grid.append(row)

    grid[1][1] = 0
    return grid


def build_visited(grid: list[list[int]], rover: dict[str, int]) -> list[list[bool]]:
    visited = [[False for _ in row] for row in grid]
    visited[rover["row"]][rover["col"]] = True
    return visited


def collect_reachable_cells(grid: list[list[int]], rover: dict[str, int]) -> set[tuple[int, int]]:
    direction_map = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    start = (rover["row"], rover["col"])
    stack = [start]
    reachable: set[tuple[int, int]] = {start}

    while stack:
        current_row, current_col = stack.pop()
        for delta_row, delta_col in direction_map:
            next_row = current_row + delta_row
            next_col = current_col + delta_col

            is_out_of_bounds = (
                next_row < 0
                or next_col < 0
                or next_row >= len(grid)
                or next_col >= len(grid[0])
            )
            if is_out_of_bounds or grid[next_row][next_col] == 1:
                continue

            next_position = (next_row, next_col)
            if next_position in reachable:
                continue

            reachable.add(next_position)
            stack.append(next_position)

    return reachable


def choose_positions(
    candidates: set[tuple[int, int]],
    count: int,
    rng: random.Random,
) -> list[tuple[int, int]]:
    if count <= 0 or not candidates:
        return []
    pool = list(candidates)
    rng.shuffle(pool)
    return pool[: min(count, len(pool))]


def create_event_positions(
    candidates: set[tuple[int, int]],
    count: int,
    rng: random.Random,
    blocked: set[tuple[int, int]],
) -> set[tuple[int, int]]:
    available = [position for position in candidates if position not in blocked]
    rng.shuffle(available)
    return set(available[: min(count, len(available))])


def evaluate_mission_status(state: GameState) -> str:
    fuel = int(state["fuel"])
    fuel_limit = int(state["fuel_limit"])
    samples_collected = int(state["samples_collected"])
    samples_total = int(state["samples_total"])
    survival_moves = int(state["moves_made"])
    survival_target = int(state["survival_turns_required"])
    rover = state["rover"]
    goal = state["goal"]

    if fuel >= fuel_limit:
        return "FAILED"

    if not isinstance(rover, dict) or not isinstance(goal, dict):
        return "IN_PROGRESS"

    reached_goal = rover["row"] == goal["row"] and rover["col"] == goal["col"]
    completed_samples = samples_total == 0 or samples_collected >= samples_total
    completed_survival = survival_moves >= survival_target

    if reached_goal and completed_samples and completed_survival:
        return "SUCCESS"

    return "IN_PROGRESS"


def mark_visited(state: GameState, rover: dict[str, int]) -> None:
    visited = state["visited"]
    if not isinstance(visited, list):
        raise HTTPException(status_code=400, detail="game is not initialized")

    row = rover["row"]
    col = rover["col"]
    if not visited[row][col]:
        visited[row][col] = True
        state["explored_count"] = int(state["explored_count"]) + 1


def mark_traversed_path(state: GameState, path: list[dict[str, int]]) -> None:
    for position in path:
        mark_visited(state, position)


def _inside_grid(grid: list[list[int]], row: int, col: int) -> bool:
    return 0 <= row < len(grid) and 0 <= col < len(grid[0])


def _step_rover(
    grid: list[list[int]],
    rover: dict[str, int],
    command: str,
    collision_cost: int,
) -> tuple[dict[str, int], str, int]:
    direction_map = {
        "U": (-1, 0),
        "D": (1, 0),
        "L": (0, -1),
        "R": (0, 1),
    }

    if command not in direction_map:
        raise HTTPException(status_code=400, detail=f"invalid command: {command}")

    delta_row, delta_col = direction_map[command]
    next_row = rover["row"] + delta_row
    next_col = rover["col"] + delta_col

    if not _inside_grid(grid, next_row, next_col) or grid[next_row][next_col] == 1:
        return rover, "Warning", collision_cost

    return {"row": next_row, "col": next_col}, "Pass", 1


def _apply_position_effects(
    state: GameState,
    rover: dict[str, int],
    command: str,
) -> tuple[int, list[str], bool]:
    row = rover["row"]
    col = rover["col"]
    position = (row, col)

    event_log: list[str] = []
    fuel_delta = 0
    grant_bonus_step = False

    theme = normalize_theme(str(state["theme"]))
    theme_effect = THEME_EFFECTS[theme]

    samples = state["samples"]
    if isinstance(samples, list):
        for index, sample in enumerate(samples):
            if sample["row"] == row and sample["col"] == col and not sample["collected"]:
                sample["collected"] = True
                state["samples_collected"] = int(state["samples_collected"]) + 1
                event_log.append("sample")
                break

    supplies = state["supplies"]
    if isinstance(supplies, set) and position in supplies:
        supplies.remove(position)
        fuel_delta -= int(theme_effect["supply_gain"])
        event_log.append("supply")

    hazards = state["hazards"]
    if isinstance(hazards, set) and position in hazards:
        fuel_delta += int(theme_effect["hazard_penalty"])
        event_log.append("hazard")

    boosts = state["boosts"]
    if isinstance(boosts, set) and position in boosts:
        boosts.remove(position)
        grant_bonus_step = True
        event_log.append("boost")

    fuel_delta += int(theme_effect["extra_move_drain"])

    return fuel_delta, event_log, grant_bonus_step


def move_rover(
    state: GameState,
    commands: list[str],
) -> tuple[dict[str, int], str, int, list[dict[str, int]], list[str]]:
    grid = state["grid"]
    rover = state["rover"]
    theme = normalize_theme(str(state["theme"]))
    theme_effect = THEME_EFFECTS[theme]

    if not isinstance(grid, list) or not isinstance(rover, dict):
        raise HTTPException(status_code=400, detail="game is not initialized")

    current = {"row": rover["row"], "col": rover["col"]}
    fuel_used = 0
    traversed_path: list[dict[str, int]] = []
    event_log: list[str] = []

    for command in commands:
        next_rover, result, step_fuel = _step_rover(
            grid,
            current,
            command,
            int(theme_effect["collision_cost"]),
        )
        fuel_used += step_fuel
        if result == "Warning":
            return current, "Warning", fuel_used, traversed_path, event_log

        current = next_rover
        traversed_path.append({"row": current["row"], "col": current["col"]})
        state["moves_made"] = int(state["moves_made"]) + 1

        effect_fuel, effects, grant_bonus_step = _apply_position_effects(state, current, command)
        fuel_used += effect_fuel
        event_log.extend(effects)

        if not grant_bonus_step:
            continue

        boosted_rover, boosted_result, boosted_cost = _step_rover(
            grid,
            current,
            command,
            int(theme_effect["collision_cost"]),
        )
        if boosted_result == "Warning":
            fuel_used += boosted_cost
            event_log.append("boost-collision")
            return current, "Warning", fuel_used, traversed_path, event_log

        current = boosted_rover
        traversed_path.append({"row": current["row"], "col": current["col"]})
        state["moves_made"] = int(state["moves_made"]) + 1

        bonus_effect_fuel, bonus_effects, _ = _apply_position_effects(state, current, command)
        fuel_used += bonus_effect_fuel
        event_log.extend(bonus_effects)
        event_log.append("boost-move")

    return current, "Pass", fuel_used, traversed_path, event_log


def normalize_commands(commands: list[str]) -> list[str]:
    direction_aliases = {
        "U": "U",
        "D": "D",
        "L": "L",
        "R": "R",
        "↑": "U",
        "↓": "D",
        "←": "L",
        "→": "R",
    }

    normalized_commands: list[str] = []
    for command in commands:
        normalized_command = direction_aliases.get(command.strip().upper())
        if normalized_command is None:
            raise HTTPException(status_code=400, detail=f"invalid command: {command}")
        normalized_commands.append(normalized_command)

    return normalized_commands


def _serialize_positions(positions: set[tuple[int, int]]) -> list[dict[str, int]]:
    return [{"row": row, "col": col} for row, col in sorted(positions)]


def _build_objectives(state: GameState) -> dict[str, object]:
    rover = state["rover"]
    goal = state["goal"]

    reached_goal = False
    if isinstance(rover, dict) and isinstance(goal, dict):
        reached_goal = rover["row"] == goal["row"] and rover["col"] == goal["col"]

    return {
        "samples": {
            "collected": state["samples_collected"],
            "total": state["samples_total"],
            "completed": int(state["samples_collected"]) >= int(state["samples_total"]),
        },
        "goal": {
            "target": state["goal"],
            "reached": reached_goal,
        },
        "survival": {
            "moves": state["moves_made"],
            "required": state["survival_turns_required"],
            "completed": int(state["moves_made"]) >= int(state["survival_turns_required"]),
        },
        "exploration": {
            "count": state["explored_count"],
            "target": state["target_count"],
        },
    }


def _build_points_payload(state: GameState) -> dict[str, object]:
    samples_payload: list[dict[str, int]] = []
    samples = state["samples"]
    if isinstance(samples, list):
        samples_payload = [
            {"row": sample["row"], "col": sample["col"], "collected": sample["collected"]}
            for sample in samples
        ]

    return {
        "goal": state["goal"],
        "samples": samples_payload,
        "supplies": _serialize_positions(state["supplies"]) if isinstance(state["supplies"], set) else [],
        "hazards": _serialize_positions(state["hazards"]) if isinstance(state["hazards"], set) else [],
        "boosts": _serialize_positions(state["boosts"]) if isinstance(state["boosts"], set) else [],
    }


def _grant_reward_if_needed(state: GameState, mission: str) -> dict[str, object] | None:
    if mission != "SUCCESS":
        return None

    stage = int(state["stage"])
    reward = STAGE_REWARDS.get(stage)
    if reward is None:
        return None

    unlock_key = f"stage-{stage}"
    unlocked = state["unlocked_rewards"]
    if not isinstance(unlocked, set):
        return None

    if unlock_key in unlocked:
        return {
            "new": False,
            "stage": stage,
            "reward": reward,
        }

    unlocked.add(unlock_key)
    return {
        "new": True,
        "stage": stage,
        "reward": reward,
    }


def build_game_state_response(state: GameState, status: str) -> dict[str, object]:
    grid = state["grid"]
    rover = state["rover"]
    visited = state["visited"]

    if not isinstance(grid, list) or not isinstance(rover, dict) or not isinstance(visited, list):
        raise HTTPException(status_code=400, detail="game is not initialized")

    mission = evaluate_mission_status(state)
    reward = _grant_reward_if_needed(state, mission)

    return {
        "grid": grid,
        "rover": rover,
        "fuel": state["fuel"],
        "fuelLimit": state["fuel_limit"],
        "visited": visited,
        "exploredCount": state["explored_count"],
        "targetCount": state["target_count"],
        "mission": mission,
        "status": status,
        "difficulty": state["difficulty"],
        "stage": state["stage"],
        "seed": state["seed"],
        "theme": state["theme"],
        "objectives": _build_objectives(state),
        "points": _build_points_payload(state),
        "history": {
            "commands": state["command_history"],
            "events": state["event_history"],
        },
        "reward": reward,
        "unlockedRewards": sorted(state["unlocked_rewards"]) if isinstance(state["unlocked_rewards"], set) else [],
    }


def _new_game_state(payload: InitRequest, session_id: str) -> GameState:
    difficulty = normalize_difficulty(payload.difficulty)
    settings = DIFFICULTY_SETTINGS[difficulty]

    seed = payload.seed if payload.seed is not None else random.randint(1, 10**9)
    rng = random.Random(seed)

    grid = build_grid(
        payload.height,
        payload.width,
        float(settings["obstacle_ratio"]),
        rng,
    )
    rover = {"row": 1, "col": 1}
    visited = build_visited(grid, rover)

    reachable = collect_reachable_cells(grid, rover)
    target_count = len(reachable)

    candidates = set(reachable)
    candidates.discard((1, 1))

    samples_raw = choose_positions(candidates, int(settings["sample_count"]), rng)
    for sample in samples_raw:
        candidates.discard(sample)

    goal_raw = choose_positions(candidates, 1, rng)
    goal_position = goal_raw[0] if goal_raw else (1, 1)

    protected = set(samples_raw)
    protected.add(goal_position)
    protected.add((1, 1))

    supplies = create_event_positions(
        candidates,
        int(settings["supply_count"]),
        rng,
        protected,
    )
    hazards = create_event_positions(
        candidates,
        int(settings["hazard_count"]),
        rng,
        protected | supplies,
    )
    boosts = create_event_positions(
        candidates,
        int(settings["boost_count"]),
        rng,
        protected | supplies | hazards,
    )

    previous_state = session_games.get(session_id)
    previous_unlocks = (
        set(previous_state["unlocked_rewards"])
        if isinstance(previous_state, dict) and isinstance(previous_state.get("unlocked_rewards"), set)
        else set()
    )

    return {
        "grid": grid,
        "rover": rover,
        "fuel": 0,
        "fuel_limit": int(settings["fuel_limit"]),
        "visited": visited,
        "explored_count": 1,
        "target_count": target_count,
        "difficulty": difficulty,
        "stage": payload.stage,
        "seed": seed,
        "theme": normalize_theme(payload.theme),
        "goal": {"row": goal_position[0], "col": goal_position[1]},
        "samples": [
            {"row": row, "col": col, "collected": False}
            for row, col in samples_raw
        ],
        "samples_total": len(samples_raw),
        "samples_collected": 0,
        "survival_turns_required": int(settings["survival_turns"]),
        "moves_made": 0,
        "supplies": supplies,
        "hazards": hazards,
        "boosts": boosts,
        "command_history": [],
        "event_history": [],
        "unlocked_rewards": previous_unlocks,
    }


def _get_session_id(request: Request) -> str | None:
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id is None or session_id.strip() == "":
        return None
    return session_id


def _get_session_state(request: Request) -> tuple[str, GameState]:
    session_id = _get_session_id(request)
    if session_id is None or session_id not in session_games:
        raise HTTPException(status_code=400, detail="game is not initialized")
    return session_id, session_games[session_id]


@app.get("/")
def read_root() -> FileResponse:
    return FileResponse(BASE_DIR / "index.html")


@app.get("/api/health")
def read_health() -> dict[str, str]:
    return {"message": "Hello World"}


@app.get("/api/state")
def read_game_state(request: Request) -> dict[str, object]:
    _, state = _get_session_state(request)
    return build_game_state_response(state, "READY")


@app.get("/api/replay")
def read_replay_data(request: Request) -> dict[str, object]:
    session_id, state = _get_session_state(request)
    return {
        "sessionId": session_id,
        "seed": state["seed"],
        "difficulty": state["difficulty"],
        "stage": state["stage"],
        "commands": state["command_history"],
        "events": state["event_history"],
    }


@app.post("/api/init")
def initialize_game(payload: InitRequest, request: Request) -> JSONResponse:
    if payload.width < 3 or payload.height < 3:
        raise HTTPException(status_code=400, detail="width and height must be at least 3")

    incoming_session_id = _get_session_id(request)
    session_id = incoming_session_id if incoming_session_id else str(uuid4())

    state = _new_game_state(payload, session_id)
    session_games[session_id] = state
    response_payload = build_game_state_response(state, "READY")

    response = JSONResponse(content=response_payload)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24,
    )
    return response


@app.post("/api/command")
def move_rover_by_command(payload: CommandRequest, request: Request) -> dict[str, object]:
    _, state = _get_session_state(request)

    if any(command.strip() == "" for command in payload.commands):
        raise HTTPException(status_code=400, detail="commands must not be empty")

    if evaluate_mission_status(state) != "IN_PROGRESS":
        raise HTTPException(status_code=400, detail="mission has already ended")

    normalized_commands = normalize_commands(payload.commands)
    state["theme"] = normalize_theme(payload.theme)

    next_rover, result, fuel_delta, traversed_path, event_log = move_rover(state, normalized_commands)
    state["rover"] = next_rover
    fuel_limit = int(state["fuel_limit"])
    state["fuel"] = max(0, min(int(state["fuel"]) + fuel_delta, fuel_limit))
    mark_traversed_path(state, traversed_path)

    command_history = state["command_history"]
    if isinstance(command_history, list):
        command_history.extend(normalized_commands)

    event_history = state["event_history"]
    if isinstance(event_history, list) and event_log:
        event_history.extend(event_log)

    response_payload = build_game_state_response(state, "UPDATED")
    response_payload["result"] = result
    response_payload["commands"] = normalized_commands
    response_payload["events"] = event_log
    return response_payload
