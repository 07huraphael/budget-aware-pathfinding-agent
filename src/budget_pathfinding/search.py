"""Incremental searchers with independent, resumable state and lazy heap updates."""
from collections import deque
import heapq
import math
import sys
import time
from .grid import Cell, Grid

FIXED_STRATEGIES = ("bfs", "dijkstra", "astar", "greedy", "weighted_1.5", "weighted_3")


class Search:
    def __init__(self, grid: Grid, strategy: str, min_cost: int | None = None, trace: bool = False):
        if strategy not in FIXED_STRATEGIES and strategy != "ara":
            raise ValueError(f"Unknown strategy: {strategy}")
        self.grid, self.strategy = grid, strategy
        self.min_cost = grid.min_cost if min_cost is None else min_cost
        self.g = {grid.start: 0}
        self.parent: dict[Cell, Cell] = {}
        self.closed: set[Cell] = set()
        self.open_nodes: set[Cell] = {grid.start}
        self.queue = deque([grid.start]) if strategy == "bfs" else deque()
        self.heap: list[tuple[float, int, int, Cell]] = []
        self.sequence = 0
        self.expansions = 0
        self.best_h = self.h(grid.start)
        self.done = False
        self.proven_no_path = False
        self.optimal = False
        self.path: list[Cell] | None = None
        self.path_cost: int | None = None
        self.reconstruction_seconds = 0.0
        self.trace_enabled = trace
        self.expanded_cells: list[Cell] = []
        self.weight = float(strategy.split("_")[1]) if strategy.startswith("weighted_") else 1.0
        if strategy != "bfs":
            self._push(grid.start)

    def h(self, node: Cell) -> int:
        return self.grid.distance(node) * self.min_cost

    def priority(self, node: Cell) -> float:
        if self.strategy == "dijkstra":
            return self.g[node]
        if self.strategy == "greedy":
            return self.h(node)
        return self.g[node] + self.weight * self.h(node)

    def _push(self, node: Cell) -> None:
        self.sequence += 1
        self.open_nodes.add(node)
        heapq.heappush(self.heap, (self.priority(node), self.sequence, self.g[node], node))

    def _clean_heap(self) -> None:
        while self.heap:
            _, _, cost, node = self.heap[0]
            if node in self.open_nodes and cost == self.g[node]:
                break
            heapq.heappop(self.heap)

    @property
    def frontier_size(self) -> int:
        return len(self.open_nodes)

    def reconstruct(self) -> list[Cell]:
        node, path = self.grid.goal, [self.grid.goal]
        while node != self.grid.start:
            node = self.parent[node]
            path.append(node)
        path.reverse()
        return path

    def _publish(self) -> None:
        began = time.perf_counter()
        path = self.reconstruct()
        cost = self.grid.path_cost(path)
        if self.path_cost is None or cost < self.path_cost:
            self.path, self.path_cost = path, cost
        self.reconstruction_seconds += time.perf_counter() - began

    def step(self) -> Cell | None:
        """Perform at most one expansion; popping the goal also counts as one."""
        if self.done:
            return None
        if self.strategy == "bfs":
            if not self.queue:
                self.done = self.proven_no_path = True
                return None
            node = self.queue.popleft()
        else:
            self._clean_heap()
            if not self.heap:
                self.done = self.proven_no_path = True
                return None
            _, _, _, node = heapq.heappop(self.heap)
        self.open_nodes.discard(node)
        self.closed.add(node)
        self.expansions += 1
        self.best_h = min(self.best_h, self.h(node))
        if self.trace_enabled:
            self.expanded_cells.append(node)
        if node == self.grid.goal:
            self._publish()
            self.done = True
            self.optimal = self.strategy in ("astar", "dijkstra") or (
                self.strategy == "bfs" and all(cost == 1 for row in self.grid.costs for cost in row))
            return node
        for nxt in self.grid.neighbors(node):
            cost = self.g[node] + self.grid.cost(nxt)
            if self.strategy == "bfs":
                if nxt in self.g:
                    continue
                self.g[nxt], self.parent[nxt] = cost, node
                self.queue.append(nxt)
                self.open_nodes.add(nxt)
            elif cost < self.g.get(nxt, math.inf):
                self.g[nxt], self.parent[nxt] = cost, node
                self.closed.discard(nxt)  # Reopen when a better g-value is found.
                self._push(nxt)
        if not self.open_nodes:
            self.done = self.proven_no_path = True
        return node

    def advance(self, expansions: int) -> int:
        count = self.expansions
        for _ in range(expansions):
            if self.done:
                break
            self.step()
        return self.expansions - count

    def memory_estimate(self) -> int:
        """Approximate retained state bytes, excluding the shared immutable grid."""
        containers = (self.g, self.parent, self.closed, self.open_nodes, self.heap,
                      self.queue, self.expanded_cells, self.path or [])
        base = sum(sys.getsizeof(container) for container in containers)
        # Per-entry storage is estimated; use tracemalloc for allocation peaks.
        return base + len(self.g) * 84 + len(self.parent) * 56 + len(self.heap) * 72


class ARAStar(Search):
    """ARA* OPEN/CLOSED/INCONS repair, following Likhachev et al. (2003), Fig. 3."""
    def __init__(self, grid: Grid, min_cost: int | None = None, trace: bool = False,
                 initial_weight: float = 3.0, decrement: float = .5):
        if initial_weight < 1 or decrement <= 0:
            raise ValueError("ARA* weight >= 1 and decrement > 0 required")
        super().__init__(grid, "ara", min_cost, trace)
        self.weight, self.decrement = initial_weight, decrement
        self.incons: set[Cell] = set()
        self.certified_bound: float | None = None
        self.iterations = 0
        self.last_published_g = math.inf
        self.heap.clear()
        self._push(grid.start)

    def _repair(self) -> None:
        self.weight = max(1.0, self.weight - self.decrement)
        self.open_nodes.update(self.incons)
        self.incons.clear()
        self.closed.clear()
        self.heap.clear()
        for node in sorted(self.open_nodes):
            self._push(node)

    def step(self) -> Cell | None:
        if self.done:
            return None
        # Phase changes do not expand nodes, but their CPU time is still measured.
        while True:
            self._clean_heap()
            goal_g = self.g.get(self.grid.goal, math.inf)
            minimum = self.heap[0][0] if self.heap else math.inf
            if math.isfinite(goal_g) and goal_g <= minimum:
                self._publish()
                self.iterations += 1
                candidates = self.open_nodes | self.incons
                lower = min((self.g[n] + self.h(n) for n in candidates), default=goal_g)
                self.certified_bound = max(1.0, min(self.weight, goal_g / lower))
                if self.certified_bound <= 1.0:
                    self.done = self.optimal = True
                    return None
                self._repair()
                continue
            if not self.heap:
                self.done = True
                self.proven_no_path = self.path is None
                return None
            break
        _, _, _, node = heapq.heappop(self.heap)
        self.open_nodes.discard(node)
        self.closed.add(node)
        self.expansions += 1
        self.best_h = min(self.best_h, self.h(node))
        if self.trace_enabled:
            self.expanded_cells.append(node)
        for nxt in self.grid.neighbors(node):
            cost = self.g[node] + self.grid.cost(nxt)
            if cost < self.g.get(nxt, math.inf):
                self.g[nxt], self.parent[nxt] = cost, node
                if nxt not in self.closed:
                    self._push(nxt)
                else:
                    self.incons.add(nxt)
        # Publish a feasible incumbent immediately, even between certified phases.
        if self.g.get(self.grid.goal, math.inf) < self.last_published_g:
            self._publish()
            self.last_published_g = self.g[self.grid.goal]
        return node

    def memory_estimate(self) -> int:
        return super().memory_estimate() + sys.getsizeof(self.incons) + len(self.incons) * 56
