"""Audit persisted results and map-level separation after a study."""
import json
from pathlib import Path
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else "results/study")
splits = {}
total = 0
for directory in (root / "tuning/dev", root / "tuning/validation", root / "evaluation", root / "time_evaluation"):
    if not directory.exists():
        raise SystemExit(f"Missing study stage: {directory}")
    maps = [json.loads(line) for line in (directory / "maps.jsonl").read_text(encoding="utf-8").splitlines()]
    ids = {entry["map_id"] for entry in maps}
    split = maps[0]["split"]
    splits.setdefault(split, set()).update(ids)
    count = 0
    for line in (directory / "runs.jsonl").open(encoding="utf-8"):
        row = json.loads(line)
        assert row["map_id"] in ids
        assert (row["cost"] is not None) == (row["status"] == "success")
        if row["budget_kind"] == "expansions":
            assert row["expansions"] <= row["budget"]
        if row["quality_ratio"] is not None:
            assert row["quality_ratio"] >= 1 - 1e-12
        if row["first_solution_seconds"] is not None and row["budget_kind"] == "time":
            assert row["first_solution_seconds"] <= row["budget"]
        if row["method"] == "adaptive":
            assert row["switches"] <= 2
        costs = [item["cost"] for item in row["improvements"]]
        assert all(left > right for left, right in zip(costs, costs[1:]))
        count += 1
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert count == manifest["run_count"]
    total += count
    print(f"OK: {directory}: {len(maps)} maps, {count} runs")
for left in splits:
    for right in splits:
        if left != right:
            assert not splits[left] & splits[right], (left, right)
print(f"Verified {total} persisted runs; dev/validation/test map IDs are disjoint.")
