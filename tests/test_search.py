import itertools
import math
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from budget_pathfinding.agent import Budget, run_agent
from budget_pathfinding.controller import Rules
from budget_pathfinding.grid import Grid, generate_grid
from budget_pathfinding.search import ARAStar, FIXED_STRATEGIES, Search


def reference_cost(grid):
    # Independent Bellman-Ford oracle on tiny grids (no searcher's heap/reopen logic).
    cells = [(x, y) for y in range(grid.height) for x in range(grid.width) if grid.passable((x, y))]
    distances = dict.fromkeys(cells, math.inf)
    distances[grid.start] = 0
    for _ in range(len(cells) - 1):
        changed = False
        for cell in cells:
            for nxt in grid.neighbors(cell):
                candidate = distances[cell] + grid.cost(nxt)
                if candidate < distances[nxt]:
                    distances[nxt] = candidate
                    changed = True
        if not changed:
            break
    return None if math.isinf(distances[grid.goal]) else distances[grid.goal]


class SearchTests(unittest.TestCase):
    def test_exhaustive_tiny_obstacles_and_weights(self):
        candidates = [(1, 0), (0, 1), (1, 1), (0, 2)]
        for mask in range(16):
            walls = frozenset(cell for index, cell in enumerate(candidates) if mask & (1 << index))
            for weights in ((1, 1, 1, 1, 1, 1), (1, 5, 3, 1, 5, 3)):
                grid = Grid(2, 3, walls, tuple(tuple(weights[y * 2:y * 2 + 2]) for y in range(3)), (0, 0), (1, 2))
                expected = reference_cost(grid)
                for strategy in (*FIXED_STRATEGIES, "ara"):
                    search = ARAStar(grid) if strategy == "ara" else Search(grid, strategy)
                    search.advance(500)
                    self.assertTrue(search.done, (mask, strategy))
                    if expected is None:
                        self.assertTrue(search.proven_no_path)
                        self.assertIsNone(search.path)
                    else:
                        self.assertEqual(grid.path_cost(search.path), search.path_cost)
                        if strategy in ("astar", "dijkstra", "ara") or (strategy == "bfs" and max(weights) == 1):
                            self.assertEqual(search.path_cost, expected, (mask, strategy))

    def test_random_weighted_oracle(self):
        for seed in range(30):
            grid = generate_grid(8, .25, seed, weighted=True)
            expected = reference_cost(grid)
            for strategy in ("astar", "dijkstra", "ara"):
                search = ARAStar(grid) if strategy == "ara" else Search(grid, strategy)
                search.advance(10000)
                self.assertEqual(search.path_cost, expected, (seed, strategy))

    def test_pause_and_resume_equals_continuous_search(self):
        grid = generate_grid(20, .2, 9, weighted=True)
        for strategy in (*FIXED_STRATEGIES, "ara"):
            continuous = ARAStar(grid) if strategy == "ara" else Search(grid, strategy)
            resumed = ARAStar(grid) if strategy == "ara" else Search(grid, strategy)
            continuous.advance(10000)
            while not resumed.done:
                self.assertLess(resumed.expansions, 10000)
                resumed.advance(7)
            self.assertEqual(continuous.path, resumed.path, strategy)
            self.assertEqual(continuous.expansions, resumed.expansions, strategy)

    def test_weighted_bfs_does_not_claim_cost_optimality(self):
        grid = Grid(3, 2, frozenset(), ((1, 5, 1), (1, 1, 1)), (0, 0), (2, 0))
        bfs, astar = Search(grid, "bfs"), Search(grid, "astar")
        bfs.advance(100)
        astar.advance(100)
        self.assertEqual(bfs.path_cost, 6)
        self.assertEqual(astar.path_cost, 4)
        self.assertFalse(bfs.optimal)

    def test_ara_incumbent_monotone_and_certified_bound(self):
        for seed in range(20):
            grid = generate_grid(12, .15, seed, weighted=True)
            optimum = reference_cost(grid)
            search = ARAStar(grid)
            previous = math.inf
            for _ in range(3000):
                if search.done:
                    break
                search.step()
                if search.path_cost is not None:
                    self.assertLessEqual(search.path_cost, previous)
                    previous = search.path_cost
            self.assertEqual(search.path_cost, optimum)
            if optimum is not None:
                self.assertTrue(search.optimal)
                self.assertEqual(search.certified_bound, 1.0)


class AgentTests(unittest.TestCase):
    def test_all_methods_respect_exact_expansion_budget(self):
        from budget_pathfinding.agent import METHODS
        grid = generate_grid(20, .2, 11, weighted=True)
        for method, cap in itertools.product(METHODS, (0, 1, 7, 32, 99)):
            result = run_agent(grid, method, Budget(cap))
            self.assertLessEqual(result.expansions, cap, (method, cap))
            if result.path:
                self.assertEqual(grid.path_cost(result.path), result.cost)

    def test_duplicate_expansions_are_charged(self):
        grid = generate_grid(30, .2, 1, "u")
        result = run_agent(grid, "equal", Budget(70), Rules(chunk_size=10), trace=True)
        self.assertEqual(result.expansions, 70)
        self.assertGreater(result.duplicate_expansions, 0)
        self.assertEqual(len(result.trace), result.expansions)

    def test_no_path_is_distinct_from_budget_failure(self):
        grid = Grid(3, 3, frozenset(((1, 0), (0, 1))), ((1, 1, 1),) * 3, (0, 0), (2, 2))
        self.assertEqual(run_agent(grid, "adaptive", Budget(100)).status, "no_path")
        self.assertEqual(run_agent(grid, "adaptive", Budget(0)).status, "budget_exhausted")

    def test_switch_limit_and_incumbent_preservation(self):
        grid = generate_grid(30, .2, 4, "u", True)
        result = run_agent(grid, "adaptive", Budget(1000), Rules(chunk_size=8, stagnation_windows=1,
                                                                    quality_target=1.0), trace=True)
        self.assertLessEqual(result.switches, 2)
        for previous, current in zip(result.improvements, result.improvements[1:]):
            self.assertLess(current["cost"], previous["cost"])
        if result.improvements:
            self.assertEqual(result.cost, result.improvements[-1]["cost"])

    def test_zero_deadline_includes_initialization(self):
        result = run_agent(generate_grid(), "adaptive", Budget(None, 0))
        self.assertEqual(result.expansions, 0)
        self.assertEqual(result.status, "deadline")
        self.assertIsNone(result.path)
        self.assertGreater(result.elapsed_seconds, 0)

    def test_memory_profile(self):
        result = run_agent(generate_grid(10), "adaptive", Budget(50), profile_memory=True)
        self.assertGreater(result.peak_traced_bytes, 0)

    def test_sufficient_quality_condition_is_valid(self):
        for seed in range(10):
            grid = generate_grid(10, .1, seed)
            result = run_agent(grid, "adaptive", Budget(1000))
            if "품질 충분조건" in result.stop_reason:
                self.assertLessEqual(result.cost / reference_cost(grid), 1.1)

    def test_grid_roundtrip_and_generators(self):
        for structure in ("random", "u", "wall", "maze"):
            grid = generate_grid(20, .2, 42, structure, True)
            self.assertEqual(Grid.from_dict(grid.to_dict()), grid)
            self.assertEqual(generate_grid(20, .2, 42, structure, True), grid)
            if structure != "random":
                self.assertIsNotNone(reference_cost(grid))

    def test_structured_maps_vary_with_seed(self):
        for structure in ("u", "wall", "maze"):
            maps = [generate_grid(20, .2, seed, structure) for seed in range(10)]
            self.assertGreater(len({(grid.walls, grid.start, grid.goal) for grid in maps}), 1)

    def test_invalid_inputs(self):
        for kwargs in ({"expansions": -1}, {"expansions": None}, {"seconds": float("nan")}):
            with self.assertRaises(ValueError):
                Budget(**kwargs)
        with self.assertRaises(ValueError):
            generate_grid(20, .9)


if __name__ == "__main__":
    unittest.main()
