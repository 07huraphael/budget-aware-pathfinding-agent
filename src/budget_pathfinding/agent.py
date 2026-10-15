"""Shared expansion/deadline budget, independent search states, and reason logs."""
from dataclasses import asdict, dataclass, field
import math
import sys
import time
import tracemalloc
from .controller import Rules, select_initial
from .grid import Cell, Grid
from .search import ARAStar, FIXED_STRATEGIES, Search

METHODS = (*FIXED_STRATEGIES, "initial", "equal", "adaptive", "ara", "no_progress",
           "no_switch", "no_early_return", "unlimited_switches", "first_solution")


@dataclass(frozen=True)
class Budget:
    expansions: int | None = 1000
    seconds: float | None = None

    def __post_init__(self):
        if self.expansions is None and self.seconds is None:
            raise ValueError("At least one budget is required")
        if self.expansions is not None and (isinstance(self.expansions, bool) or self.expansions < 0):
            raise ValueError("Expansion budget must be nonnegative")
        if self.seconds is not None and (not math.isfinite(self.seconds) or self.seconds < 0):
            raise ValueError("Time budget must be finite and nonnegative")


@dataclass
class Result:
    method: str
    status: str
    path: list[Cell] | None
    cost: int | None
    expansions: int
    elapsed_seconds: float
    controller_seconds: float
    feature_seconds: float
    initialization_seconds: float
    reconstruction_seconds: float
    switches: int
    duplicate_expansions: int
    peak_retained_estimate_bytes: int
    peak_traced_bytes: int | None
    first_solution_expansions: int | None
    first_solution_seconds: float | None
    initial_strategy: str
    final_strategy: str
    stop_reason: str
    budget: dict
    features: dict
    improvements: list[dict] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)
    deadline_overrun_seconds: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def run_agent(grid: Grid, method: str = "adaptive", budget: Budget | None = None,
              rules: Rules | None = None, trace: bool = False,
              profile_memory: bool = False) -> Result:
    if method not in METHODS:
        raise ValueError(f"Unknown method: {method}")
    budget, rules = budget or Budget(), rules or Rules()
    if profile_memory and tracemalloc.is_tracing():
        raise ValueError("Memory profiling requires an isolated tracemalloc session")
    if profile_memory:
        tracemalloc.start()
    try:
        return _run(grid, method, budget, rules, trace, profile_memory)
    finally:
        if profile_memory:
            tracemalloc.stop()


def _run(grid: Grid, method: str, budget: Budget, rules: Rules, trace: bool,
         profile_memory: bool) -> Result:
    began = time.perf_counter()
    deadline = began + budget.seconds if budget.seconds is not None else math.inf
    feature_start = time.perf_counter()
    minimum = grid.min_cost
    features = {"width": grid.width, "height": grid.height, "area": grid.width * grid.height,
                "density": grid.density, "distance": grid.distance(grid.start),
                "h0": grid.distance(grid.start) * minimum,
                "weighted": any(c != 1 for row in grid.costs for c in row)}
    feature_seconds = time.perf_counter() - feature_start
    decision_start = time.perf_counter()
    if method in FIXED_STRATEGIES or method == "ara":
        active, reason = method, "고정 탐색 전략"
    elif method == "equal":
        active, reason = FIXED_STRATEGIES[0], "6개 고정 전략에 관찰 구간을 순환 배정"
    else:
        active, reason = select_initial(features, budget.expansions, rules)
    controller_seconds = time.perf_counter() - decision_start
    initial = active
    engines: dict[str, Search] = {}
    initialization_seconds = 0.0
    decisions: list[dict] = []
    improvements: list[dict] = []
    expansion_trace: list[dict] = []
    incumbent: list[Cell] | None = None
    best_cost: int | None = None
    expansions = switches = duplicates = peak_estimate = 0
    global_seen: set[Cell] = set()
    first_expansions = first_seconds = None
    stalls: dict[str, int] = {}
    no_improvement = 0
    last_frontier: dict[str, int] = {}
    last_best_h: dict[str, int] = {}
    stop_reason, status = "확장 예산 소진", "budget_exhausted"

    def engine(name: str) -> Search:
        nonlocal initialization_seconds
        if name not in engines:
            init_start = time.perf_counter()
            engines[name] = ARAStar(grid, minimum, trace) if name == "ara" else Search(grid, name, minimum, trace)
            initialization_seconds += time.perf_counter() - init_start
        return engines[name]

    def log(action: str, reason_text: str, **observations) -> None:
        decisions.append({"action": action, "strategy": active, "reason": reason_text,
                          "expansions": expansions, "seconds": time.perf_counter() - began,
                          "remaining_expansions": None if budget.expansions is None else budget.expansions - expansions,
                          "remaining_seconds": None if budget.seconds is None else max(0, deadline - time.perf_counter()),
                          **observations})

    log("select", reason)
    current = engine(active)
    while True:
        if time.perf_counter() >= deadline:
            status, stop_reason = "deadline", "실제 시간 예산 소진"
            break
        if budget.expansions is not None and expansions >= budget.expansions:
            break
        block_start_cost = best_cost
        before_h = last_best_h.get(active, current.best_h)
        before_frontier = last_frontier.get(active, current.frontier_size)
        remaining = rules.chunk_size if budget.expansions is None else budget.expansions - expansions
        for _ in range(min(rules.chunk_size, remaining)):
            if current.done or time.perf_counter() >= deadline:
                break
            node = current.step()
            now = time.perf_counter()
            if node is not None:
                expansions += 1
                duplicates += int(node in global_seen)
                global_seen.add(node)
                if trace:
                    expansion_trace.append({"cell": node, "strategy": active, "expansion": expansions,
                                            "seconds": now - began})
            # An incumbent completed after the deadline is not eligible.
            if now <= deadline and current.path_cost is not None and (best_cost is None or current.path_cost < best_cost):
                best_cost, incumbent = current.path_cost, list(current.path)
                if first_expansions is None:
                    first_expansions, first_seconds = expansions, now - began
                improvements.append({"expansions": expansions, "seconds": now - began,
                                     "cost": best_cost, "strategy": active,
                                     **({"path": incumbent} if trace else {})})
            if method == "first_solution" and incumbent is not None:
                break
            if node is None:
                break
        memory = sum(e.memory_estimate() for e in engines.values()) + sys.getsizeof(global_seen) + len(global_seen) * 56
        peak_estimate = max(peak_estimate, memory)
        decision_start = time.perf_counter()
        progress = before_h - current.best_h
        growth = current.frontier_size - before_frontier
        last_best_h[active], last_frontier[active] = current.best_h, current.frontier_size
        stalled = progress < rules.minimum_progress and (
            growth >= rules.frontier_growth_threshold or current.frontier_size > 0)
        stalls[active] = stalls.get(active, 0) + 1 if stalled else 0
        no_improvement = no_improvement + 1 if block_start_cost == best_cost else 0
        remaining_fraction = ((budget.expansions - expansions) / max(1, budget.expansions)
                              if budget.expansions is not None else
                              max(0.0, (deadline - time.perf_counter()) / max(budget.seconds, 1e-12)))
        observations = {"h_decrease": progress, "best_h": current.best_h,
                        "frontier": current.frontier_size, "frontier_growth": growth,
                        "stagnation_windows": stalls[active], "incumbent_cost": best_cost,
                        "remaining_fraction": round(remaining_fraction, 4)}
        target = None
        target_reason = ""
        should_stop = False
        if time.perf_counter() >= deadline:
            status, stop_reason, should_stop = "deadline", "실제 시간 예산 소진", True
        elif current.proven_no_path:
            status, stop_reason, should_stop = "no_path", "frontier 소진: 경로가 존재하지 않음 확인", True
        elif method == "first_solution" and incumbent is not None:
            stop_reason, should_stop = "첫 경로 확보 즉시 반환", True
        elif method in FIXED_STRATEGIES or method in ("initial", "no_switch", "ara"):
            if current.done:
                stop_reason, should_stop = "탐색기 종료", True
        elif method == "equal":
            candidates = [s for s in FIXED_STRATEGIES if s not in engines or not engines[s].done]
            if not candidates:
                stop_reason, should_stop = "모든 고정 탐색기 종료", True
            else:
                position = FIXED_STRATEGIES.index(active)
                target = min(candidates, key=lambda s: (FIXED_STRATEGIES.index(s) - position - 1) % len(FIXED_STRATEGIES))
                target_reason = "순환 균등 배정; 기존 탐색기 상태 재개"
        else:
            allow_early = method != "no_early_return"
            if allow_early and incumbent is not None and best_cost <= rules.quality_target * features["h0"]:
                stop_reason, should_stop = f"C={best_cost} ≤ ρh₀={rules.quality_target * features['h0']:.2f}: 품질 충분조건", True
            elif allow_early and incumbent is not None and current.optimal:
                stop_reason, should_stop = "최적 탐색기가 최적성 확인", True
            elif allow_early and incumbent is not None and no_improvement >= rules.improvement_patience and remaining_fraction <= rules.return_remaining_fraction:
                stop_reason, should_stop = f"최근 {no_improvement}구간 개선 없음, 남은 예산 비율 {remaining_fraction:.3f}", True
            else:
                can_switch = method == "unlimited_switches" or switches < rules.max_switches
                want_switch = current.done or (method != "no_progress" and stalls[active] >= rules.stagnation_windows)
                if method == "no_progress" and not current.done:
                    # Budget-only scheduling is independent of observed search progress.
                    want_switch = remaining_fraction <= (2 - min(switches, 1)) / 3
                if can_switch and want_switch:
                    if incumbent is not None:
                        preferences = ("astar", "dijkstra", "weighted_1.5", "weighted_3", "greedy")
                    elif active in ("greedy", "weighted_3", "weighted_1.5"):
                        preferences = ("astar", "weighted_1.5", "dijkstra", "weighted_3", "greedy")
                    else:
                        preferences = ("weighted_3", "weighted_1.5", "greedy", "dijkstra", "astar")
                    target = next((s for s in preferences if s != active and (s not in engines or not engines[s].done)), None)
                    if target:
                        if current.done:
                            target_reason = "현재 탐색기 종료; 독립 탐색기로 경로 개선"
                        elif method == "no_progress":
                            target_reason = f"진행 정보 제거: 남은 예산 비율 {remaining_fraction:.3f}에 따른 전환"
                        else:
                            target_reason = f"최근 {stalls[active]}구간 정체: h 감소 {progress}, frontier {current.frontier_size}, 증가 {growth}"
                if current.done and target is None:
                    stop_reason, should_stop = "사용 가능한 탐색기 또는 전환 횟수 소진", True
        if should_stop:
            controller_seconds += time.perf_counter() - decision_start
            break
        if target and target != active:
            old = active
            active = target
            switches += 1
            log("switch", target_reason, previous_strategy=old, resumed=active in engines, **observations)
            # Engine construction is tracked separately from rule evaluation.
            controller_seconds += time.perf_counter() - decision_start
            current = engine(active)
        else:
            log("keep", "현재 전략에 다음 탐색 구간 배정", **observations)
            controller_seconds += time.perf_counter() - decision_start
    log("return", stop_reason, incumbent_cost=best_cost)
    if incumbent is not None:
        status = "success"
    elapsed = time.perf_counter() - began
    peak_estimate = max(peak_estimate, sum(e.memory_estimate() for e in engines.values()) + sys.getsizeof(global_seen) + len(global_seen) * 56)
    peak_traced = tracemalloc.get_traced_memory()[1] if profile_memory else None
    return Result(method, status, incumbent, best_cost, expansions, elapsed, controller_seconds,
                  feature_seconds, initialization_seconds,
                  sum(e.reconstruction_seconds for e in engines.values()), switches, duplicates,
                  peak_estimate, peak_traced, first_expansions, first_seconds, initial, active,
                  stop_reason, asdict(budget), features, improvements, decisions, expansion_trace,
                  max(0.0, elapsed - budget.seconds) if budget.seconds is not None else 0.0)
