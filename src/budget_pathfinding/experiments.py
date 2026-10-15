"""Map-level split protocol, paired experiments, validation selection, and provenance."""
import csv
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import platform
import random
import statistics
import time
from . import __version__
from .agent import Budget, METHODS, run_agent
from .controller import Rules
from .grid import generate_grid
from .search import FIXED_STRATEGIES, Search


def show_progress(message):
    print(message, flush=True)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: str | Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def map_cases(config: dict, split: str | None = None):
    split = split or config.get("split", "test")
    if split not in ("dev", "validation", "test", "pilot", "smoke"):
        raise ValueError("Unknown map split")
    for size in config.get("sizes", [20]):
        for structure in config.get("structures", ["random"]):
            densities = config.get("densities", [.2]) if structure == "random" else [config.get("densities", [.2])[0]]
            for density in densities:
                for cost_mode in config.get("cost_modes", ["uniform"]):
                    if cost_mode not in ("uniform", "weighted"):
                        raise ValueError("Unknown cost mode")
                    repetitions = config.get("structured_repeats", config.get("repeats", 3)) if structure != "random" else config.get("repeats", 3)
                    for index in range(repetitions):
                        token = f"{config.get('seed', 20261014)}:{split}:{size}:{structure}:{density}:{cost_mode}:{index}"
                        digest = hashlib.sha256(token.encode()).hexdigest()
                        seed = int(digest[:8], 16)
                        map_id = f"{split}-{digest[:16]}"
                        grid = generate_grid(size, density, seed, structure, cost_mode == "weighted")
                        yield {"map_id": map_id, "split": split, "size": size, "structure": structure,
                               "requested_density": density if structure == "random" else None,
                               "actual_density": grid.density, "cost_mode": cost_mode, "seed": seed}, grid


def optimal_cost(grid):
    oracle = Search(grid, "dijkstra")
    oracle.advance(grid.width * grid.height + 1)
    if not oracle.done:
        raise RuntimeError("Unbounded Dijkstra oracle did not finish")
    return oracle.path_cost


def source_hash() -> str:
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.rglob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def run_experiments(config: dict, output: str | Path, rules: Rules | None = None,
                    methods: list[str] | None = None, progress=show_progress) -> list[dict]:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    rules = rules or Rules()
    methods = methods or config.get("methods", list(METHODS))
    if not methods or any(method not in METHODS for method in methods):
        raise ValueError("Experiment contains an unknown or empty method list")
    cases = list(map_cases(config))
    budgets = ([Budget(None, seconds) for seconds in config["time_budgets"]]
               if "time_budgets" in config else [Budget(cap) for cap in config.get("budgets", [100, 1000, 10000])])
    rows: list[dict] = []
    began = time.perf_counter()
    manifest = {"version": __version__, "source_sha256": source_hash(),
                "python": platform.python_version(), "platform": platform.platform(),
                "started_local": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "config": config, "rules": rules.to_dict(), "methods": methods,
                "map_count": len(cases), "case_count": len(cases) * len(budgets),
                "time_semantics": "cooperative deadline checked before/after each expansion; late solutions rejected",
                "memory_metric": "tracemalloc allocation peak (instrumented timing)" if config.get("profile_memory") else "retained state estimate; not process RSS"}
    write_json(output / "manifest.json", manifest)
    with (output / "maps.jsonl").open("w", encoding="utf-8") as map_file, (output / "runs.jsonl").open("w", encoding="utf-8") as run_file:
        for case_index, (case, grid) in enumerate(cases):
            optimum = optimal_cost(grid)  # Evaluation-only oracle; never passed to run_agent.
            map_file.write(json.dumps({**case, "optimal_cost": optimum, "grid": grid.to_dict()}, ensure_ascii=False) + "\n")
            for budget_index, budget in enumerate(budgets):
                ordered = list(methods)
                random.Random(case["seed"] + budget_index).shuffle(ordered)
                for method in ordered:
                    result = run_agent(grid, method, budget, rules, profile_memory=config.get("profile_memory", False))
                    if budget.expansions is not None and result.expansions > budget.expansions:
                        raise AssertionError("Expansion budget exceeded")
                    if result.path is not None and grid.path_cost(result.path) != result.cost:
                        raise AssertionError("Invalid returned path")
                    ratio = result.cost / optimum if result.cost is not None and optimum is not None else None
                    row = {**case, "method": method, "budget_kind": "time" if budget.seconds is not None else "expansions",
                           "budget": budget.seconds if budget.seconds is not None else budget.expansions,
                           "solvable": optimum is not None, "optimal_cost": optimum,
                           "status": result.status, "cost": result.cost, "quality_ratio": ratio,
                           "expansions": result.expansions, "elapsed_seconds": result.elapsed_seconds,
                           "controller_seconds": result.controller_seconds,
                           "seconds_without_controller": max(0, result.elapsed_seconds - result.controller_seconds),
                           "feature_seconds": result.feature_seconds, "initialization_seconds": result.initialization_seconds,
                           "reconstruction_seconds": result.reconstruction_seconds,
                           "controller_fraction": result.controller_seconds / max(result.elapsed_seconds, 1e-12),
                           "switches": result.switches, "duplicate_expansions": result.duplicate_expansions,
                           "peak_retained_estimate_bytes": result.peak_retained_estimate_bytes,
                           "peak_traced_bytes": result.peak_traced_bytes,
                           "first_solution_expansions": result.first_solution_expansions,
                           "first_solution_seconds": result.first_solution_seconds,
                           "initial_strategy": result.initial_strategy, "final_strategy": result.final_strategy,
                           "stop_reason": result.stop_reason, "deadline_overrun_seconds": result.deadline_overrun_seconds,
                           **{f"s_{rho:.2f}": int(ratio is not None and ratio <= rho + 1e-12) for rho in (1.05, 1.10, 1.25)}}
                    rows.append(row)
                    # Keep all consequential decisions; repetitive keep windows are counted.
                    run_file.write(json.dumps({**row, "improvements": result.improvements,
                                               "keep_decision_count": sum(d["action"] == "keep" for d in result.decisions),
                                               "decisions": [d for d in result.decisions if d["action"] != "keep"]}, ensure_ascii=False) + "\n")
            if (case_index + 1) % max(1, len(cases) // 10) == 0:
                progress(f"[{case_index + 1}/{len(cases)} maps] {len(rows)} runs, {time.perf_counter() - began:.1f}s")
    with (output / "results.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]) if rows else ["map_id"])
        writer.writeheader()
        writer.writerows(rows)
    manifest["run_count"] = len(rows)
    manifest["wall_seconds"] = time.perf_counter() - began
    write_json(output / "manifest.json", manifest)
    return rows


def tune_rules(config: dict, output: str | Path, progress=show_progress) -> dict:
    """Select among predeclared candidates on validation, then lock before test."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    candidates = [Rules(), replace(Rules(), chunk_size=16, low_budget_factor=2),
                  replace(Rules(), chunk_size=64, stagnation_windows=3),
                  replace(Rules(), dense_threshold=.35, low_budget_factor=6)]
    # Development is used as a separate sanity stage, not for final evaluation.
    dev_config = {**config, "split": "dev"}
    run_experiments(dev_config, output / "dev", candidates[0], ["adaptive", "astar", "weighted_3"], progress)
    cases = [(case, grid, optimal_cost(grid)) for case, grid in map_cases(config, "validation")]
    budgets = config.get("budgets", [100, 1000, 10000])
    scores = []
    for index, candidate in enumerate(candidates):
        eligible = success = quality = work = 0
        for _, grid, optimum in cases:
            for cap in budgets:
                result = run_agent(grid, "adaptive", Budget(cap), candidate)
                work += result.expansions
                if optimum is not None:
                    eligible += 1
                    success += result.cost is not None
                    quality += result.cost is not None and result.cost / optimum <= 1.10 + 1e-12
        scores.append({"candidate": index, "rules": candidate.to_dict(), "s_1.10": quality / max(1, eligible),
                       "reach_rate": success / max(1, eligible), "expansions": work})
        progress(f"validation candidate {index}: S1.10={scores[-1]['s_1.10']:.4f}")
    winner = max(scores, key=lambda row: (row["s_1.10"], row["reach_rate"], -row["expansions"], -row["candidate"]))
    validation_config = {**config, "split": "validation"}
    validation = run_experiments(validation_config, output / "validation", Rules(**winner["rules"]), list(FIXED_STRATEGIES), progress)
    fixed_scores = []
    for method in FIXED_STRATEGIES:
        eligible = [row for row in validation if row["method"] == method and row["solvable"]]
        fixed_scores.append({"method": method, "s_1.10": statistics.mean(row["s_1.10"] for row in eligible) if eligible else 0,
                             "reach_rate": statistics.mean(row["cost"] is not None for row in eligible) if eligible else 0,
                             "expansions": sum(row["expansions"] for row in eligible)})
    best_fixed = max(fixed_scores, key=lambda row: (row["s_1.10"], row["reach_rate"], -row["expansions"]))
    frozen = {"rules": winner["rules"], "best_fixed": best_fixed["method"], "candidate_scores": scores,
              "fixed_scores": fixed_scores, "selection_metric": "S1.10, reach rate, fewer expansions",
              "validation_map_ids": [case["map_id"] for case, _, _ in cases],
              "test_data_used": False, "source_sha256": source_hash()}
    write_json(output / "frozen_rules.json", frozen)
    return frozen


def calibrate_time(config: dict, output: str | Path) -> list[float]:
    samples = []
    cases = list(map_cases(config, "pilot"))
    indices = sorted({round(i * (len(cases) - 1) / max(1, min(12, len(cases)) - 1)) for i in range(min(12, len(cases)))})
    for index in indices:
        _, grid = cases[index]
        samples.append(run_agent(grid, "astar", Budget(grid.width * grid.height + 1)).elapsed_seconds)
    median = statistics.median(samples)
    limits = sorted(set(round(max(.0005, median * factor), 6) for factor in (.25, 1, 4)))
    write_json(Path(output), {"pilot_astar_seconds": samples, "median_seconds": median,
                             "time_budgets": limits, "test_data_used": False,
                             "note": "Machine-specific budgets fixed after separate pilot maps"})
    return limits
