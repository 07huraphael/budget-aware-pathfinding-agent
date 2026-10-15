"""Failure-aware metrics, paired comparisons, map-cluster bootstrap, SVG reports."""
from collections import defaultdict
import csv
import html
import json
from pathlib import Path
import random
import statistics
from .experiments import source_hash, write_json


def load_rows(directory: str | Path) -> list[dict]:
    with (Path(directory) / "runs.jsonl").open(encoding="utf-8") as file:
        rows = []
        for line in file:
            if line.strip():
                row = json.loads(line)
                row.pop("decisions", None)
                row.pop("improvements", None)
                rows.append(row)
        return rows


def mean(values):
    values = list(values)
    return statistics.mean(values) if values else None


def cluster_interval(values: list[tuple[str, float]], samples: int = 500, seed: int = 20261014):
    """Resample maps, retaining all their budget observations together."""
    groups = defaultdict(list)
    for map_id, value in values:
        groups[map_id].append(value)
    clusters = [(sum(group), len(group)) for group in groups.values()]
    if not clusters:
        return [None, None]
    rng = random.Random(seed)
    estimates = []
    for _ in range(samples):
        numerator = denominator = 0
        for _ in clusters:
            total, count = clusters[rng.randrange(len(clusters))]
            numerator += total
            denominator += count
        estimates.append(numerator / denominator)
    estimates.sort()
    return [estimates[int(.025 * (samples - 1))], estimates[int(.975 * (samples - 1))]]


def summarize(rows: list[dict], intervals=True, samples=500) -> dict:
    eligible = [row for row in rows if row["solvable"]]
    successful = [row for row in eligible if row["cost"] is not None]
    summary = {"runs": len(rows), "maps": len({r["map_id"] for r in rows}),
               "solvable_cases": len(eligible), "unsolvable_cases": len(rows) - len(eligible),
               "reach_rate": len(successful) / len(eligible) if eligible else None,
               "mean_quality_success_only": mean(r["quality_ratio"] for r in successful),
               "mean_expansions": mean(r["expansions"] for r in rows),
               "mean_seconds": mean(r["elapsed_seconds"] for r in rows),
               "mean_seconds_without_controller": mean(r["seconds_without_controller"] for r in rows),
               "mean_controller_fraction": mean(r["controller_fraction"] for r in rows),
               "mean_switches": mean(r["switches"] for r in rows),
               "mean_actual_density": mean(r["actual_density"] for r in rows),
               "mean_duplicate_expansions": mean(r["duplicate_expansions"] for r in rows),
               "max_retained_estimate_bytes": max((r["peak_retained_estimate_bytes"] for r in rows), default=0),
               "max_traced_bytes": max((r["peak_traced_bytes"] for r in rows if r["peak_traced_bytes"] is not None), default=None),
               "mean_first_solution_seconds": mean(r["first_solution_seconds"] for r in successful),
               "max_deadline_overrun_seconds": max((r["deadline_overrun_seconds"] for r in rows), default=0),
               "no_path_proven": sum(r["status"] == "no_path" for r in rows if not r["solvable"])}
    for rho in (1.05, 1.10, 1.25):
        key = f"s_{rho:.2f}"
        summary[key] = mean(r[key] for r in eligible)
        if intervals:
            summary[f"{key}_ci95"] = cluster_interval([(r["map_id"], r[key]) for r in eligible], samples)
    return summary


def paired(rows, left="adaptive", right="astar", samples=500):
    def key(row):
        return row["map_id"], row["budget_kind"], row["budget"]
    a = {key(r): r for r in rows if r["method"] == left and r["solvable"]}
    b = {key(r): r for r in rows if r["method"] == right and r["solvable"]}
    keys = sorted(a.keys() & b.keys())
    quality = [(k[0], a[k]["quality_ratio"] - b[k]["quality_ratio"]) for k in keys
               if a[k]["cost"] is not None and b[k]["cost"] is not None]
    quality_delta = [(k[0], a[k]["s_1.10"] - b[k]["s_1.10"]) for k in keys]
    reach_delta = [(k[0], int(a[k]["cost"] is not None) - int(b[k]["cost"] is not None)) for k in keys]
    return {"left": left, "right": right, "paired_solvable_cases": len(keys),
            "delta_s_1.10": mean(v for _, v in quality_delta),
            "delta_s_1.10_ci95": cluster_interval(quality_delta, samples),
            "delta_reach_rate": mean(v for _, v in reach_delta),
            "delta_reach_rate_ci95": cluster_interval(reach_delta, samples),
            "joint_success_cases": len(quality), "joint_success_quality_delta": mean(v for _, v in quality),
            "joint_success_quality_delta_ci95": cluster_interval(quality, samples)}


def write_csv(path: Path, rows: list[dict]):
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        if rows:
            writer = csv.DictWriter(file, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def bars_svg(path: Path, title: str, series: list[tuple[str, float | None]], percent=False):
    width, height, left = 1000, 100 + 34 * len(series), 200
    maximum = 1.0 if percent else max((value or 0 for _, value in series), default=1) or 1
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
           '<rect width="100%" height="100%" fill="#101827"/>',
           f'<text x="30" y="40" fill="#f3f6fc" font-size="22" font-family="sans-serif">{html.escape(title)}</text>']
    for index, (label, value) in enumerate(series):
        y = 72 + index * 34
        amount = 0 if value is None else value
        color = "#4edbb0" if label == "adaptive" else "#709cf5"
        svg.extend([f'<text x="20" y="{y+17}" fill="#d7dfed" font-size="14" font-family="sans-serif">{html.escape(label)}</text>',
                    f'<rect x="{left}" y="{y}" width="{650 * amount / maximum:.2f}" height="23" rx="4" fill="{color}"/>',
                    f'<text x="880" y="{y+17}" fill="#eef3fc" font-size="14" font-family="sans-serif">{amount:.1%}</text>' if percent else
                    f'<text x="880" y="{y+17}" fill="#eef3fc" font-size="14" font-family="sans-serif">{amount:.4f}</text>'])
    svg.append('</svg>')
    path.write_text("\n".join(svg), encoding="utf-8")


def analyze(directory: str | Path, best_fixed: str = "astar", samples: int = 500) -> dict:
    if samples < 20:
        raise ValueError("At least 20 bootstrap samples are required")
    directory = Path(directory)
    rows = load_rows(directory)
    methods = sorted({r["method"] for r in rows})
    summary = {method: summarize([r for r in rows if r["method"] == method], samples=samples) for method in methods}
    groups = defaultdict(list)
    for row in rows:
        groups[(row["method"], row["budget_kind"], row["budget"], row["size"], row["structure"], row["cost_mode"], row["requested_density"])].append(row)
    conditions = [{"method": key[0], "budget_kind": key[1], "budget": key[2], "size": key[3],
                   "structure": key[4], "cost_mode": key[5], "requested_density": key[6], **summarize(group, samples=min(samples, 300))}
                  for key, group in sorted(groups.items())]
    comparisons = [paired(rows, "adaptive", method, samples) for method in methods if method != "adaptive"]
    paired_conditions = []
    condition_groups = defaultdict(list)
    for row in rows:
        condition_groups[(row["budget_kind"], row["budget"], row["size"], row["structure"], row["cost_mode"], row["requested_density"])].append(row)
    for key, group in sorted(condition_groups.items()):
        for baseline in dict.fromkeys((best_fixed, "initial", "ara")):
            paired_conditions.append({"budget_kind": key[0], "budget": key[1], "size": key[2],
                                      "structure": key[3], "cost_mode": key[4], "requested_density": key[5],
                                      **paired(group, "adaptive", baseline, min(samples, 300))})
    write_json(directory / "summary.json", {"overall": summary, "paired": comparisons, "best_fixed_validation": best_fixed,
                                            "bootstrap_samples": samples, "analysis_source_sha256": source_hash()})
    write_csv(directory / "summary_by_condition.csv", conditions)
    write_csv(directory / "paired_by_condition.csv", paired_conditions)
    bars_svg(directory / "quality_success.svg", "Quality-qualified reach rate (S1.10, failures included)",
             [(m, summary[m]["s_1.10"]) for m in methods], True)
    bars_svg(directory / "controller_overhead.svg", "Mean controller time / total measured time",
             [(m, summary[m]["mean_controller_fraction"]) for m in methods], True)
    budget_series = []
    for cap in sorted({r["budget"] for r in rows}):
        for method in dict.fromkeys(("adaptive", best_fixed, "ara", "initial")):
            eligible = [r for r in rows if r["method"] == method and r["budget"] == cap and r["solvable"]]
            budget_series.append((f"{method} / {cap:g}", mean(r["s_1.10"] for r in eligible)))
    bars_svg(directory / "budget_quality.svg", "S1.10 by budget (all map structures and cost modes)", budget_series, True)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    lines = ["# 실험 결과 보고서", "", f"지도 {manifest['map_count']}개, 지도–예산 조합 {manifest['case_count']}개, 실행 {len(rows)}개.", "",
             f"검증 지도에서 선정하고 최종 평가 전에 고정한 단일 기준선: **{best_fixed}**.", "",
             "Sρ의 분모는 경로가 존재하는 지도–예산 조합 전체입니다. 예산 내 미발견도 실패로 포함하며, 경로 없는 지도는 별도 집계합니다.", "",
             "| 방법 | 도달률 | S1.05 | S1.10 | S1.25 | 성공 시 평균 C/C* | 평균 확장 | 평균 시간(ms) |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    def fmt(value, percent=False):
        return "—" if value is None else (f"{value:.2%}" if percent else f"{value:.3f}")
    for method in methods:
        s = summary[method]
        lines.append(f"| {method} | {fmt(s['reach_rate'], True)} | {fmt(s['s_1.05'], True)} | {fmt(s['s_1.10'], True)} | {fmt(s['s_1.25'], True)} | {fmt(s['mean_quality_success_only'])} | {fmt(s['mean_expansions'])} | {fmt(s['mean_seconds'] * 1000)} |")
    lines.extend(["", "## 짝지은 비교", "", "차이는 adaptive − 기준선입니다. S1.10 차이가 양수이면 적응형이 유리합니다. 신뢰구간은 지도 단위 95% bootstrap이며 같은 지도의 모든 예산 실행을 함께 재표집합니다.", "",
                  "| 기준선 | ΔS1.10 | 95% CI | 공동 성공 수 | 공동 성공 품질 차이 |", "|---|---:|---|---:|---:|"])
    for comparison in comparisons:
        low, high = comparison["delta_s_1.10_ci95"]
        lines.append(f"| {comparison['right']} | {fmt(comparison['delta_s_1.10'], True)} | [{fmt(low, True)}, {fmt(high, True)}] | {comparison['joint_success_cases']} | {fmt(comparison['joint_success_quality_delta'])} |")
    selected = next((c for c in comparisons if c["right"] == best_fixed), None)
    if selected and selected["delta_s_1.10"] is not None:
        delta = selected["delta_s_1.10"]
        lines.extend(["", f"이 실행에서 적응형의 S1.10은 검증 선정 기준선보다 **{abs(delta)*100:.2f}%p {'높았습니다' if delta > 0 else '낮았습니다' if delta < 0 else '동일했습니다'}**. 이 결과만으로 일반적 우수성을 주장하지 않습니다."])
    lines.extend(["", "## 측정 범위와 해석", "",
                  "- 최적 비용은 별도의 무제한 Dijkstra로 계산하며 실행 중 제어기에 전달하지 않았습니다.",
                  "- 시간은 특징 계산, 전략 선택, 초기화, 전환, 복원 및 계측 비용을 포함합니다. 지도 생성·평가용 최적 비용 계산·화면 재생은 제외합니다.",
                  f"- 메모리 지표: {manifest['memory_metric']}. 추정치와 traced allocation peak는 RSS가 아닙니다.",
                  "- 시간 제한은 협력적 검사입니다. 한 확장·초기화의 완료와 결과 정리에 따른 초과 시간을 기록하며, 마감 후 완료된 새 경로는 채택하지 않습니다.",
                  "- seconds_without_controller는 측정된 제어 시간을 차감한 보조값입니다. 제어기 없이 재실행한 반사실적 성능을 뜻하지 않습니다.",
                  "- 무전환 변형은 초기 선택만 유지합니다. no_progress는 지도 특징과 남은 예산만 사용하여 전환합니다.",
                  "- no_early_return은 품질·정체 기반 조기 반환을 제거합니다. 모든 유용한 탐색기가 끝나거나 전환 한도에 도달하면 종료할 수 있습니다.",
                  "- 전체 평균은 구성한 지도 분포에 의존합니다. 구조별 실제 밀도도 함께 기록했으며 밀도를 통제한 인과 효과를 주장하지 않습니다.",
                  "- 세부 조건별 비교와 불리한 조건은 summary_by_condition.csv 및 paired_by_condition.csv에서 확인할 수 있습니다.", "",
                  "![품질 기준 도달률](quality_success.svg)", "", "![예산별 비교](budget_quality.svg)", "", "![제어 비용](controller_overhead.svg)", ""])
    (directory / "report.md").write_text("\n".join(lines), encoding="utf-8")
    cards = "".join(f'<figure><img src="{name}.svg" alt="{name}"/></figure>' for name in ("quality_success", "budget_quality", "controller_overhead"))
    (directory / "report.html").write_text('<!doctype html><html lang="ko"><meta charset="utf-8"><title>Pathfinding experiment results</title><style>body{background:#101827;color:#edf3ff;font:16px system-ui;max-width:1100px;margin:40px auto;padding:20px}img{width:100%}pre{white-space:pre-wrap;line-height:1.6}figure{margin:25px 0}</style><h1>Budget-Aware Pathfinding · 결과</h1>' + cards + '<pre>' + html.escape("\n".join(lines)) + '</pre></html>', encoding="utf-8")
    return summary
