import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from budget_pathfinding.analysis import analyze, cluster_interval, paired
from budget_pathfinding.experiments import map_cases, run_experiments
from budget_pathfinding.server import simulate


class ProtocolTests(unittest.TestCase):
    def test_map_splits_and_budget_reuse(self):
        config = {"sizes": [8], "densities": [.2], "repeats": 4, "seed": 42}
        splits = [list(map_cases(config, split)) for split in ("dev", "validation", "test")]
        for left, right in ((0, 1), (0, 2), (1, 2)):
            self.assertFalse({c[0]["map_id"] for c in splits[left]} & {c[0]["map_id"] for c in splits[right]})
            self.assertFalse({c[0]["seed"] for c in splits[left]} & {c[0]["seed"] for c in splits[right]})
        self.assertEqual(splits[2], list(map_cases(config, "test")))

    def test_result_pipeline_and_pairing(self):
        config = {"sizes": [8], "densities": [.1], "repeats": 2,
                  "budgets": [10, 100], "methods": ["adaptive", "astar", "ara"], "seed": 17}
        with tempfile.TemporaryDirectory() as temp:
            rows = run_experiments(config, temp, progress=lambda _: None)
            self.assertEqual(len(rows), 12)
            self.assertEqual(len({r["map_id"] for r in rows}), 2)
            summary = analyze(temp, samples=30)
            self.assertEqual(summary["adaptive"]["runs"], 4)
            result = paired(rows, "astar", "astar", 30)
            self.assertEqual(result["delta_s_1.10"], 0)
            self.assertEqual(result["delta_s_1.10_ci95"], [0, 0])
            for name in ("report.html", "report.md", "summary.json", "paired_by_condition.csv", "quality_success.svg"):
                self.assertTrue((Path(temp) / name).is_file())

    def test_cluster_bootstrap_is_reproducible(self):
        values = [("a", 1), ("a", 1), ("b", 0), ("b", 0)]
        self.assertEqual(cluster_interval(values, 50), cluster_interval(values, 50))
        self.assertEqual(cluster_interval([], 50), [None, None])

    def test_simulator_outputs_real_trace_and_comparisons(self):
        data = simulate({"size": 20, "structure": "u", "seed": 42, "method": "adaptive", "budget": 1000})
        self.assertEqual(len(data["result"]["trace"]), data["result"]["expansions"])
        self.assertIn("ara", [c["method"] for c in data["comparisons"]])
        self.assertIsNotNone(data["optimal_cost_evaluation_only"])
        if data["result"]["improvements"]:
            self.assertIn("path", data["result"]["improvements"][0])

    def test_trace_free_runs_do_not_store_path_in_each_improvement(self):
        from budget_pathfinding.agent import Budget, run_agent
        from budget_pathfinding.grid import generate_grid
        result = run_agent(generate_grid(10, 0), budget=Budget(1000))
        self.assertTrue(result.improvements)
        self.assertNotIn("path", result.improvements[0])


if __name__ == "__main__":
    unittest.main()
