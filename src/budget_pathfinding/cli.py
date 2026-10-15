import argparse
import json
from pathlib import Path
from .agent import Budget, METHODS, run_agent
from .analysis import analyze
from .controller import Rules
from .experiments import calibrate_time, read_json, run_experiments, tune_rules, write_json
from .grid import generate_grid
from .server import serve


def load_rules(path):
    if not path:
        return Rules(), "astar"
    frozen = read_json(path)
    return Rules(**frozen.get("rules", frozen)), frozen.get("best_fixed", "astar")


def main():
    parser = argparse.ArgumentParser(description="Budget-Aware Pathfinding Agent")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="Open the local web simulator")
    demo.add_argument("--port", type=int, default=8765)
    demo.add_argument("--no-browser", action="store_true")
    solve = sub.add_parser("solve", help="Run one reproducible search")
    solve.add_argument("--size", type=int, default=20)
    solve.add_argument("--density", type=float, default=.2)
    solve.add_argument("--seed", type=int, default=42)
    solve.add_argument("--structure", choices=["random", "u", "wall", "maze"], default="random")
    solve.add_argument("--weighted", action="store_true")
    solve.add_argument("--method", choices=METHODS, default="adaptive")
    solve.add_argument("--budget", type=int, default=1000)
    solve.add_argument("--seconds", type=float)
    solve.add_argument("--rules")
    solve.add_argument("--output")
    exp = sub.add_parser("experiment", help="Run paired map/budget experiments")
    exp.add_argument("--config", default="configs/smoke.json")
    exp.add_argument("--output", default="results/smoke")
    exp.add_argument("--rules")
    exp.add_argument("--bootstrap", type=int, default=500)
    tune = sub.add_parser("tune", help="Select rules and fixed baseline on separate validation maps")
    tune.add_argument("--config", default="configs/validation.json")
    tune.add_argument("--output", default="results/tuning")
    report = sub.add_parser("analyze", help="Generate metrics, bootstrap intervals, charts, report")
    report.add_argument("directory")
    report.add_argument("--best-fixed", default="astar")
    report.add_argument("--bootstrap", type=int, default=500)
    study = sub.add_parser("study", help="Tune, freeze, evaluate, calibrate time, and generate reports")
    study.add_argument("--config", default="configs/extended.json")
    study.add_argument("--validation-config", default="configs/validation.json")
    study.add_argument("--time-config", default="configs/time.json")
    study.add_argument("--output", default="results/study")
    study.add_argument("--bootstrap", type=int, default=500)
    args = parser.parse_args()
    if args.command == "demo":
        serve(args.port, not args.no_browser)
    elif args.command == "solve":
        rules, _ = load_rules(args.rules)
        grid = generate_grid(args.size, args.density, args.seed, args.structure, args.weighted)
        budget = Budget(None if args.seconds is not None else args.budget, args.seconds)
        result = run_agent(grid, args.method, budget, rules, trace=True).to_dict()
        if args.output:
            write_json(Path(args.output), {"grid": grid.to_dict(), "result": result})
        print(json.dumps({k: result[k] for k in ("status", "cost", "expansions", "elapsed_seconds", "switches", "stop_reason")}, ensure_ascii=False, indent=2))
    elif args.command == "tune":
        frozen = tune_rules(read_json(args.config), args.output)
        print(f"Frozen rules: {Path(args.output) / 'frozen_rules.json'}; best fixed: {frozen['best_fixed']}")
    elif args.command == "experiment":
        rules, best_fixed = load_rules(args.rules)
        run_experiments(read_json(args.config), args.output, rules)
        analyze(args.output, best_fixed, args.bootstrap)
        print(f"Report: {Path(args.output) / 'report.html'}")
    elif args.command == "analyze":
        analyze(args.directory, args.best_fixed, args.bootstrap)
    elif args.command == "study":
        root = Path(args.output)
        frozen = tune_rules(read_json(args.validation_config), root / "tuning")
        rules = Rules(**frozen["rules"])
        run_experiments(read_json(args.config), root / "evaluation", rules)
        analyze(root / "evaluation", frozen["best_fixed"], args.bootstrap)
        time_config = read_json(args.time_config)
        limits = calibrate_time(time_config, root / "time_calibration.json")
        time_config["time_budgets"] = limits
        run_experiments(time_config, root / "time_evaluation", rules)
        analyze(root / "time_evaluation", frozen["best_fixed"], args.bootstrap)
        print(f"Study complete: {root.resolve()}")


if __name__ == "__main__":
    main()
