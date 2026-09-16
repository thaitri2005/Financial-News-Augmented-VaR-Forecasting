"""Finite, outcome-blind M4 search-plan construction and identity validation."""

from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass

from newsvar.provenance import canonical_json, sha256


class SearchPlanError(ValueError):
    """The declared development-search budget is incomplete or asymmetric."""


@dataclass(frozen=True)
class DevelopmentFold:
    name: str
    target_start: str
    target_end: str


@dataclass(frozen=True)
class LinearRunSpec:
    fold: str
    feature_group: str
    tail_alpha: float
    penalty: float


@dataclass(frozen=True)
class LinearSearchPlan:
    """A data-unbound protocol that fixes fair Q0/Q1/Q2 development candidates."""

    design: str
    folds: tuple[DevelopmentFold, ...]
    feature_groups: tuple[str, ...] = ("Q0", "Q1", "Q2")
    tails: tuple[float, ...] = (0.05, 0.01)
    penalties: tuple[float, ...] = (0.001, 0.01, 0.1)

    def __post_init__(self) -> None:
        if self.design not in {"preferred", "gdelt_alternative"}:
            raise SearchPlanError("Unknown development design.")
        if self.feature_groups != ("Q0", "Q1", "Q2"):
            raise SearchPlanError("Linear search requires identical Q0/Q1/Q2 feature groups.")
        if not self.folds or len({fold.name for fold in self.folds}) != len(self.folds):
            raise SearchPlanError("Development folds must be nonempty and uniquely named.")
        if not all(0.0 < tail < 1.0 for tail in self.tails) or not all(
            penalty >= 0.0 for penalty in self.penalties
        ):
            raise SearchPlanError("Tail levels or L1 penalties are invalid.")

    @property
    def runs(self) -> tuple[LinearRunSpec, ...]:
        return tuple(
            LinearRunSpec(fold.name, group, tail, penalty)
            for fold, group, tail, penalty in itertools.product(
                self.folds, self.feature_groups, self.tails, self.penalties
            )
        )

    @property
    def identity(self) -> str:
        payload = {"plan": asdict(self), "runs": [asdict(run) for run in self.runs]}
        return sha256(canonical_json(payload))


def preferred_linear_plan() -> LinearSearchPlan:
    return LinearSearchPlan(
        "preferred",
        (
            DevelopmentFold("development_2021", "2021-01-01", "2021-12-31"),
            DevelopmentFold("development_2022", "2022-01-01", "2022-12-31"),
        ),
    )


def gdelt_alternative_linear_plan() -> LinearSearchPlan:
    return LinearSearchPlan(
        "gdelt_alternative",
        (DevelopmentFold("development_2022", "2022-01-01", "2022-12-31"),),
    )
