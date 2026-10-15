"""Extract the proposal's original 810 uniform/random cases from the extended study."""
import json
from pathlib import Path
import sys

project = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project / "src"))
from budget_pathfinding.analysis import analyze, write_csv
from budget_pathfinding.experiments import read_json, write_json

source = project / "results/study/evaluation"
output = project / "results/full"
output.mkdir(parents=True, exist_ok=True)
def selected(row):
    return row["structure"] == "random" and row["cost_mode"] == "uniform"

map_count = 0
with (source / "maps.jsonl").open(encoding="utf-8") as incoming, (output / "maps.jsonl").open("w", encoding="utf-8") as outgoing:
    for line in incoming:
        if selected(json.loads(line)):
            outgoing.write(line)
            map_count += 1
rows = []
with (source / "runs.jsonl").open(encoding="utf-8") as incoming, (output / "runs.jsonl").open("w", encoding="utf-8") as outgoing:
    for line in incoming:
        row = json.loads(line)
        if selected(row):
            outgoing.write(line)
            for key in ("decisions", "improvements", "keep_decision_count"):
                row.pop(key, None)
            rows.append(row)
write_csv(output / "results.csv", rows)
manifest = read_json(source / "manifest.json")
manifest.update({"config": read_json(project / "configs/full.json"), "map_count": map_count,
                 "case_count": 810, "run_count": len(rows),
                 "derived_from": "results/study/evaluation", "derived_subset": True})
manifest.pop("wall_seconds", None)
write_json(output / "manifest.json", manifest)
frozen = read_json(project / "results/study/tuning/frozen_rules.json")
assert map_count == 270 and len(rows) == 12150
analyze(output, frozen["best_fixed"], 500)
print(f"Extracted 270 maps, 810 cases, 12,150 recorded runs into {output}")
