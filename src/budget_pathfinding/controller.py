"""Inspectable rules. No optimal-cost oracle is available to this controller."""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Rules:
    chunk_size: int = 32
    low_budget_factor: float = 4.0
    dense_threshold: float = .25
    stagnation_windows: int = 2
    minimum_progress: float = 1.0
    frontier_growth_threshold: int = 4
    max_switches: int = 2
    quality_target: float = 1.10
    improvement_patience: int = 3
    return_remaining_fraction: float = .10

    def __post_init__(self):
        if self.chunk_size < 1 or self.stagnation_windows < 1 or self.improvement_patience < 1:
            raise ValueError("Rule window sizes must be positive")
        if self.quality_target < 1 or self.low_budget_factor <= 0 or self.max_switches < 0:
            raise ValueError("Invalid rule threshold")
        if not 0 <= self.dense_threshold <= 1 or not 0 <= self.return_remaining_fraction <= 1:
            raise ValueError("Rule fractions must be between zero and one")

    def to_dict(self) -> dict:
        return asdict(self)


def select_initial(features: dict, expansion_limit: int | None, rules: Rules) -> tuple[str, str]:
    h0 = features["h0"]
    if expansion_limit is not None and expansion_limit < rules.low_budget_factor * h0:
        return "weighted_3", f"확장 예산 {expansion_limit} < {rules.low_budget_factor:g} × 초기 하한 {h0}: 빠른 경로 우선"
    if features["density"] >= rules.dense_threshold:
        return "astar", f"실제 장애물 밀도 {features['density']:.3f} ≥ {rules.dense_threshold:g}: A* 선택"
    if features["area"] <= 400 and not features["weighted"]:
        return "astar", f"지도 {features['width']}×{features['height']}, 균일 비용: A* 선택"
    return "weighted_1.5", f"지도 {features['width']}×{features['height']}, 밀도 {features['density']:.3f}: 속도·품질 절충"
