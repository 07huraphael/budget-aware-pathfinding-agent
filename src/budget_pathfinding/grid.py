"""Static, four-connected grids. Edge cost is the destination cell's cost."""
from dataclasses import dataclass
import random
from typing import Iterator

Cell = tuple[int, int]


@dataclass(frozen=True)
class Grid:
    width: int
    height: int
    walls: frozenset[Cell]
    costs: tuple[tuple[int, ...], ...]
    start: Cell
    goal: Cell
    seed: int = 0
    structure: str = "custom"

    def __post_init__(self) -> None:
        if self.width < 2 or self.height < 2:
            raise ValueError("Grid dimensions must be at least two")
        if len(self.costs) != self.height or any(len(row) != self.width for row in self.costs):
            raise ValueError("Cost matrix dimensions do not match grid")
        if any(cost not in (1, 3, 5) for row in self.costs for cost in row):
            raise ValueError("Terrain costs must be 1, 3, or 5")
        if any(not self.contains(cell) for cell in self.walls):
            raise ValueError("Wall outside grid")
        if self.start == self.goal or not all(self.passable(c) for c in (self.start, self.goal)):
            raise ValueError("Start and goal must be distinct, passable cells")

    def contains(self, cell: Cell) -> bool:
        x, y = cell
        return 0 <= x < self.width and 0 <= y < self.height

    def passable(self, cell: Cell) -> bool:
        return self.contains(cell) and cell not in self.walls

    def neighbors(self, cell: Cell) -> Iterator[Cell]:
        x, y = cell
        for candidate in ((x + 1, y), (x, y + 1), (x - 1, y), (x, y - 1)):
            if self.passable(candidate):
                yield candidate

    def cost(self, cell: Cell) -> int:
        return self.costs[cell[1]][cell[0]]

    def distance(self, cell: Cell) -> int:
        return abs(cell[0] - self.goal[0]) + abs(cell[1] - self.goal[1])

    @property
    def min_cost(self) -> int:
        return min(self.cost((x, y)) for y in range(self.height) for x in range(self.width)
                   if (x, y) not in self.walls)

    @property
    def density(self) -> float:
        return len(self.walls) / (self.width * self.height)

    def path_cost(self, path: list[Cell]) -> int:
        if not path or path[0] != self.start or path[-1] != self.goal:
            raise ValueError("Path must join start to goal")
        for previous, current in zip(path, path[1:]):
            if not self.passable(current) or abs(previous[0] - current[0]) + abs(previous[1] - current[1]) != 1:
                raise ValueError("Path contains an invalid move")
        return sum(self.cost(cell) for cell in path[1:])

    def to_dict(self) -> dict:
        return {"width": self.width, "height": self.height, "walls": sorted(self.walls),
                "costs": self.costs, "start": self.start, "goal": self.goal,
                "seed": self.seed, "structure": self.structure}

    @classmethod
    def from_dict(cls, data: dict) -> "Grid":
        return cls(int(data["width"]), int(data["height"]),
                   frozenset(tuple(cell) for cell in data["walls"]),
                   tuple(tuple(row) for row in data["costs"]),
                   tuple(data["start"]), tuple(data["goal"]),
                   int(data.get("seed", 0)), data.get("structure", "custom"))


def generate_grid(size: int = 20, density: float = .2, seed: int = 42,
                  structure: str = "random", weighted: bool = False) -> Grid:
    if not 5 <= size <= 150 or not 0 <= density <= .6:
        raise ValueError("Size must be 5..150 and density 0..0.6")
    rng = random.Random(seed)
    start, goal = (0, 0), (size - 1, size - 1)
    walls: set[Cell] = set()
    if structure == "random":
        candidates = [(x, y) for y in range(size) for x in range(size) if (x, y) not in (start, goal)]
        walls.update(rng.sample(candidates, min(len(candidates), round(size * size * density))))
    elif structure == "u":
        # Opening faces away from the start, luring goal-directed search inside.
        left = rng.randint(max(1, size // 4), max(1, size // 2 - 1))
        right = rng.randint(max(left + 2, 3 * size // 4), size - 2)
        top = rng.randint(1, max(1, size // 4))
        bottom = rng.randint(max(top + 2, 3 * size // 4), size - 2)
        walls.update((x, top) for x in range(left, right + 1))
        walls.update((x, bottom) for x in range(left, right + 1))
        walls.update((right, y) for y in range(top, bottom + 1))
        middle = rng.randint(top + 1, bottom - 1)
        start, goal = (right - 1, middle), (right + 1, middle)
    elif structure == "wall":
        first_wall = rng.randint(max(1, size // 5), max(1, size // 3))
        for index, x in enumerate(range(first_wall, size - 1, max(2, size // 4))):
            gap = rng.randint(3 * size // 4, size - 1) if index % 2 == 0 else rng.randint(0, max(1, size // 4))
            walls.update((x, y) for y in range(size) if y != gap)
    elif structure == "maze":
        walls = {(x, y) for y in range(size) for x in range(size)}
        start = (1, 1)
        stack, visited = [start], {start}
        walls.remove(start)
        while stack:
            x, y = stack[-1]
            options = [(x + dx, y + dy) for dx, dy in ((2, 0), (-2, 0), (0, 2), (0, -2))
                       if 1 <= x + dx < size - 1 and 1 <= y + dy < size - 1
                       and (x + dx, y + dy) not in visited]
            if not options:
                stack.pop()
                continue
            nxt = rng.choice(options)
            walls.discard(((x + nxt[0]) // 2, (y + nxt[1]) // 2))
            walls.discard(nxt)
            visited.add(nxt)
            stack.append(nxt)
        goal = max(visited, key=lambda cell: (sum(cell), cell))
    else:
        raise ValueError(f"Unknown structure: {structure}")
    walls.difference_update((start, goal))
    costs = tuple(tuple(rng.choices((1, 3, 5), weights=(.65, .25, .1))[0] if weighted else 1
                        for _ in range(size)) for _ in range(size))
    return Grid(size, size, frozenset(walls), costs, start, goal, seed, structure)
