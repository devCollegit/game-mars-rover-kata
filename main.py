import random
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field


class InitRequest(BaseModel):
    # 프론트에서 보내는 맵 크기 요청값이다.
    width: int = Field(ge=3, le=20)
    height: int = Field(ge=3, le=20)


class CommandRequest(BaseModel):
    commands: list[str] = Field(min_length=1, max_length=100)


app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
game_state: dict[str, object | None] = {
    "grid": None,
    "rover": None,
    "fuel": 0,
    "visited": None,
    "explored_count": 0,
    "target_count": 0,
}


def build_grid(height: int, width: int) -> list[list[int]]:
    # 테두리는 모두 1이고, 내부는 1이 30%, 0이 70%인 맵을 만든다.
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
                row.append(1 if random.random() < 0.3 else 0)
        grid.append(row)

    # 우주선 시작 지점 (1, 1)은 반드시 이동 가능한 칸이어야 한다.
    grid[1][1] = 0
    return grid


def build_visited(grid: list[list[int]], rover: dict[str, int]) -> list[list[bool]]:
    visited = [[False for _ in row] for row in grid]
    visited[rover["row"]][rover["col"]] = True
    return visited


def count_explorable_cells(grid: list[list[int]], rover: dict[str, int]) -> int:
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

    return len(reachable)


def evaluate_mission_status() -> str:
    fuel = int(game_state["fuel"])
    explored_count = int(game_state["explored_count"])
    target_count = int(game_state["target_count"])

    if fuel >= 100:
        return "FAILED"
    if target_count > 0 and explored_count >= target_count:
        return "SUCCESS"
    return "IN_PROGRESS"


def mark_visited(rover: dict[str, int]) -> None:
    visited = game_state["visited"]
    if visited is None:
        raise HTTPException(status_code=400, detail="game is not initialized")

    row = rover["row"]
    col = rover["col"]
    if not visited[row][col]:
        visited[row][col] = True
        game_state["explored_count"] = int(game_state["explored_count"]) + 1


def mark_traversed_path(path: list[dict[str, int]]) -> None:
    for position in path:
        mark_visited(position)


def move_rover(
    grid: list[list[int]],
    rover: dict[str, int],
    commands: list[str],
) -> tuple[dict[str, int], str, int, list[dict[str, int]]]:
    direction_map = {
        "U": (-1, 0),
        "D": (1, 0),
        "L": (0, -1),
        "R": (0, 1),
    }

    current_row = rover["row"]
    current_col = rover["col"]
    fuel_used = 0
    traversed_path: list[dict[str, int]] = []

    for command in commands:
        if command not in direction_map:
            raise HTTPException(status_code=400, detail=f"invalid command: {command}")

        delta_row, delta_col = direction_map[command]
        next_row = current_row + delta_row
        next_col = current_col + delta_col

        is_out_of_bounds = (
            next_row < 0
            or next_col < 0
            or next_row >= len(grid)
            or next_col >= len(grid[0])
        )
        if is_out_of_bounds or grid[next_row][next_col] == 1:
            fuel_used += 10
            return {"row": current_row, "col": current_col}, "Warning", fuel_used, traversed_path

        current_row = next_row
        current_col = next_col
        fuel_used += 1
        traversed_path.append({"row": current_row, "col": current_col})

    return {"row": current_row, "col": current_col}, "Pass", fuel_used, traversed_path


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


def build_game_state_response(status: str) -> dict[str, object]:
    grid = game_state["grid"]
    rover = game_state["rover"]
    fuel = game_state["fuel"]
    visited = game_state["visited"]

    if grid is None or rover is None or visited is None:
        raise HTTPException(status_code=400, detail="game is not initialized")

    return {
        "grid": grid,
        "rover": rover,
        "fuel": fuel,
        "visited": visited,
        "exploredCount": game_state["explored_count"],
        "targetCount": game_state["target_count"],
        "mission": evaluate_mission_status(),
        "status": status,
    }


@app.get("/")
def read_root() -> FileResponse:
    return FileResponse(BASE_DIR / "index.html")


@app.get("/api/health")
def read_health() -> dict[str, str]:
    return {"message": "Hello World"}


@app.get("/api/state")
def read_game_state() -> dict[str, object]:
    return build_game_state_response("READY")


@app.post("/api/init")
def initialize_game(payload: InitRequest) -> dict[str, object]:
    # 잘못된 크기 요청은 바로 막는다.
    if payload.width < 3 or payload.height < 3:
        raise HTTPException(status_code=400, detail="width and height must be at least 3")

    # 요청받은 크기로 맵을 만들고 우주선 시작 위치를 정한다.
    grid = build_grid(payload.height, payload.width)
    rover = {"row": 1, "col": 1}
    visited = build_visited(grid, rover)

    # 이후 이동 API에서도 쓸 수 있도록 현재 게임 상태를 메모리에 저장한다.
    game_state["grid"] = grid
    game_state["rover"] = rover
    game_state["fuel"] = 0
    game_state["visited"] = visited
    game_state["explored_count"] = 1
    game_state["target_count"] = count_explorable_cells(grid, rover)

    # 프론트가 바로 화면에 그릴 수 있게 초기 상태 전체를 응답으로 돌려준다.
    return build_game_state_response("READY")


@app.post("/api/command")
def move_rover_by_command(payload: CommandRequest) -> dict[str, object]:
    grid = game_state["grid"]
    rover = game_state["rover"]

    if grid is None or rover is None:
        raise HTTPException(status_code=400, detail="game is not initialized")

    if any(command.strip() == "" for command in payload.commands):
        raise HTTPException(status_code=400, detail="commands must not be empty")
    normalized_commands = normalize_commands(payload.commands)

    next_rover, result, fuel_delta, traversed_path = move_rover(grid, rover, normalized_commands)
    game_state["rover"] = next_rover
    game_state["fuel"] = min(int(game_state["fuel"]) + fuel_delta, 100)
    mark_traversed_path(traversed_path)

    return {
        "grid": grid,
        "rover": next_rover,
        "fuel": game_state["fuel"],
        "visited": game_state["visited"],
        "exploredCount": game_state["explored_count"],
        "targetCount": game_state["target_count"],
        "mission": evaluate_mission_status(),
        "result": result,
        "commands": normalized_commands,
    }
