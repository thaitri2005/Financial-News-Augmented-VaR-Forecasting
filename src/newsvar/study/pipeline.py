"""Study orchestration: admission audit, development search, preregistration, final evaluation.

Stages are separated on purpose. ``admission`` reads no return. ``develop`` reads
outcomes only inside the development range. ``evaluate`` refuses to run without
a preregistration whose hash covers the development record and chosen settings.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq

from newsvar.data.calendar import CalendarSnapshot, load_snapshot
from newsvar.data.datasets import load_market_dataset
from newsvar.data.news import WINDOW_COMPLETENESS_MIN, load_corpus, ok_batch_times, window_coverage
from newsvar.evaluation import experiments as ex
from newsvar.evaluation.metrics import QuantileObservation
from newsvar.evaluation.walkforward import AvailableLabel, ForecastAttempt
from newsvar.features import table as ft
from newsvar.hashing import canonical_json, sha256
from newsvar.nlp.scoring import ScoreFingerprint, load_scores

TAILS = (0.05, 0.01)
PRIMARY_TAIL = 0.05
GROUPS = ("Q0", "Q1", "Q2")
TEST_ROWS = 500
DEVELOPMENT_ROWS = 250
MIN_TRAINING_ROWS_FOR_ADMISSION = 500
MIN_USABLE_ROWS = 1_250
PRACTICAL_GAIN = 0.02


class StudyError(ValueError):
    """A study stage was asked to run outside its declared gate."""


@dataclass(frozen=True)
class StudyInputs:
    market_dataset: Path
    calendar_path: Path
    corpus: Path
    corpus_start: date
    scores_root: Path
    fingerprint: ScoreFingerprint
    sampling_rate: float
    feature_root: Path

    def identity(self) -> dict[str, object]:
        return {
            "market_dataset_id": load_market_dataset(self.market_dataset)["dataset_id"],
            "calendar_id": load_snapshot(self.calendar_path).calendar_id,
            "corpus_id": load_corpus(self.corpus)["corpus_id"],
            "corpus_start": self.corpus_start.isoformat(),
            "score_fingerprint_id": self.fingerprint.identity,
            "score_fingerprint": asdict(self.fingerprint),
            "sampling_rate": self.sampling_rate,
        }


def feature_rows(inputs: StudyInputs, config: ft.FeatureConfig) -> tuple[Path, list[ex.StudyRow]]:
    """Materialize (or reuse) one feature table and join it to labels."""
    calendar = load_snapshot(inputs.calendar_path)
    identity = {
        "schema_version": "feature_table_v1",
        **inputs.identity(),
        "config": ft.config_identity(config),
        "min_scoring_coverage": ft.MIN_SCORING_COVERAGE,
        "window_completeness_min": WINDOW_COMPLETENESS_MIN,
    }
    table_id = sha256(canonical_json(identity))
    destination = inputs.feature_root / table_id
    if not destination.exists():
        rows = ft.build_rows(
            market_dataset=inputs.market_dataset,
            calendar=calendar,
            corpus=inputs.corpus,
            corpus_start=inputs.corpus_start,
            scores=load_scores(inputs.scores_root, inputs.fingerprint),
            config=config,
        )
        ft.materialize(inputs.feature_root, rows, identity=identity)
    ft.load(destination)
    return destination, ex.load_study_rows(destination, ex.load_labels(inputs.market_dataset))


def usable(rows: Sequence[ex.StudyRow], study_end: date) -> list[ex.StudyRow]:
    return [
        row
        for row in rows
        if row.eligible and row.label_return is not None and row.target_end_session <= study_end
    ]


def decide_split(rows: Sequence[ex.StudyRow], study_end: date) -> dict[str, Any]:
    """Apply the predeclared split rules to outcome-blind eligibility counts only."""
    rows_usable = usable(rows, study_end)
    count = len(rows_usable)
    early = sum(row.target_end_session <= date(2021, 12, 31) for row in rows_usable)
    if early >= MIN_TRAINING_ROWS_FOR_ADMISSION:
        return {
            "design": "gdelt_alternative",
            "usable_rows": count,
            "training_rows": early,
            "development": ["2022-01-01", "2022-12-31"],
            "test": ["2023-01-01", study_end.isoformat()],
        }
    if count < MIN_USABLE_ROWS:
        return {"design": "prototype_only", "usable_rows": count, "training_rows": early}
    test, development = (
        rows_usable[-TEST_ROWS:],
        rows_usable[-TEST_ROWS - DEVELOPMENT_ROWS : -TEST_ROWS],
    )
    training = count - TEST_ROWS - DEVELOPMENT_ROWS
    if training < MIN_TRAINING_ROWS_FOR_ADMISSION:
        return {"design": "prototype_only", "usable_rows": count, "training_rows": training}
    return {
        "design": "reduced_study",
        "usable_rows": count,
        "training_rows": training,
        "gdelt_alternative_training_rows": early,
        "development": [
            development[0].target_end_session.isoformat(),
            development[-1].target_end_session.isoformat(),
        ],
        "test": [test[0].target_end_session.isoformat(), test[-1].target_end_session.isoformat()],
        "development_rows": len(development),
        "test_rows": len(test),
    }


def admission(inputs: StudyInputs, *, study_end: date, buffer_minutes: int = 15) -> dict[str, Any]:
    """Outcome-blind source continuity, sample-size and split record."""
    calendar = load_snapshot(inputs.calendar_path)
    origins = calendar.origins
    coverage = window_coverage(
        ok_batch_times(inputs.corpus), origins, buffer_minutes=buffer_minutes
    )
    first = ft.first_covered_origin(origins, inputs.corpus_start)
    yearly: dict[int, list[int]] = {}
    runs: list[dict[str, object]] = []
    run_start: date | None = None
    run_length = 0
    for position, origin in enumerate(origins):
        if position < first or origin.next_session > study_end:
            continue
        complete = coverage[position].feed_complete
        bucket = yearly.setdefault(origin.session.year, [0, 0])
        bucket[0] += 1
        bucket[1] += int(complete)
        if not complete:
            run_start = run_start or origin.session
            run_length += 1
        elif run_length:
            runs.append({"first": str(run_start), "sessions": run_length})
            run_start, run_length = None, 0
    if run_length:
        runs.append({"first": str(run_start), "sessions": run_length})
    windows = sum(value[0] for value in yearly.values())
    complete_windows = sum(value[1] for value in yearly.values())
    _, rows = feature_rows(inputs, ft.FeatureConfig(sampling_rate=inputs.sampling_rate))
    considered = [row for row in rows if row.target_end_session <= study_end]
    reasons: dict[str, int] = {}
    table = pq.read_table(
        feature_rows(inputs, ft.FeatureConfig(sampling_rate=inputs.sampling_rate))[0]
        / "features.parquet",
        columns=["target_end_session", "ineligible_reasons", "scoring_coverage", "feed_complete"],
    ).to_pylist()
    coverage_values = []
    for record in table:
        if record["target_end_session"] > study_end:
            continue
        for reason in filter(None, record["ineligible_reasons"].split(";")):
            reasons[reason] = reasons.get(reason, 0) + 1
        if record["feed_complete"]:
            coverage_values.append(record["scoring_coverage"])
    by_year: dict[str, int] = {}
    for row in usable(rows, study_end):
        key = str(row.target_end_session.year)
        by_year[key] = by_year.get(key, 0) + 1
    split = decide_split(rows, study_end)
    per_year = {
        str(year): {
            "windows": value[0],
            "complete": value[1],
            "complete_share": value[1] / value[0],
        }
        for year, value in sorted(yearly.items())
    }
    criteria = {
        "overall_windows_complete_ge_95pct": complete_windows / windows >= 0.95,
        "every_year_complete_ge_90pct": all(v["complete_share"] >= 0.90 for v in per_year.values()),
        "no_incomplete_run_over_5_sessions": all(int(run["sessions"]) <= 5 for run in runs),  # type: ignore[call-overload]
        "usable_rows_ge_1250": split["usable_rows"] >= MIN_USABLE_ROWS,
        "final_test_ge_500": split.get("test_rows", 0) >= 500
        or split["design"] == "gdelt_alternative",
        "scoring_coverage_ge_98pct_every_complete_window": bool(coverage_values)
        and min(coverage_values) >= ft.MIN_SCORING_COVERAGE,
    }
    return {
        "schema_version": "news_admission_v1",
        "scope": "Outcome-blind. Counts, continuity and split only; no return was read.",
        "inputs": inputs.identity(),
        "study_end_target_session": study_end.isoformat(),
        "availability": {"class": "B", "buffer_minutes": buffer_minutes},
        "windows": {
            "first_covered_origin": origins[first].session.isoformat(),
            "considered": windows,
            "complete": complete_windows,
            "complete_share": complete_windows / windows,
            "per_origin_year": per_year,
            "incomplete_runs": runs,
        },
        "rows": {
            "considered": len(considered),
            "usable": split["usable_rows"],
            "usable_by_target_year": by_year,
            "ineligible_reason_counts": dict(sorted(reasons.items())),
            "min_scoring_coverage_on_complete_windows": min(coverage_values)
            if coverage_values
            else None,
        },
        "criteria": criteria,
        "split": split,
    }


def _range(split: Mapping[str, Any], name: str) -> tuple[date, date]:
    start, end = split[name]
    return date.fromisoformat(start), date.fromisoformat(end)


def _model_id(group: str, tail: float, *, kind: str = "Q") -> str:
    return f"{kind}{group[1]}_a{tail:g}"


def _eligible_grid(rows: Sequence[ex.StudyRow], start: date, end: date) -> list[date]:
    return [
        row.target_end_session
        for row in rows
        if row.eligible and row.label_return is not None and start <= row.target_end_session <= end
    ]


def _run_linear(
    rows: Sequence[ex.StudyRow],
    labels: Sequence[AvailableLabel],
    group: str,
    tail: float,
    penalty: float,
    span: tuple[date, date],
    *,
    without_vix: bool = False,
) -> tuple[tuple[ForecastAttempt, ...], dict[date, QuantileObservation]]:
    names = ex.feature_names(group, without_vix=without_vix)
    model_id = _model_id(group, tail)
    attempts = ex.walk_forward(
        rows,
        model_id=model_id,
        feature_names=names,
        fitter=ex.linear_fitter(names, alpha=tail, penalty=penalty),
        target_start=span[0],
        target_end=span[1],
    )
    return attempts, ex.observations(attempts, labels, model_id=model_id)


def _run_tree(
    rows: Sequence[ex.StudyRow],
    labels: Sequence[AvailableLabel],
    group: str,
    tail: float,
    setting: tuple[int, int],
    span: tuple[date, date],
) -> tuple[tuple[ForecastAttempt, ...], dict[date, QuantileObservation]]:
    names = ex.feature_names(group)
    model_id = _model_id(group, tail, kind="T")
    attempts = ex.walk_forward(
        rows,
        model_id=model_id,
        feature_names=names,
        fitter=ex.tree_fitter(names, alpha=tail, depth=setting[0], trees=setting[1]),
        target_start=span[0],
        target_end=span[1],
    )
    return attempts, ex.observations(attempts, labels, model_id=model_id)


def _status_counts(attempts: Sequence[ForecastAttempt]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for attempt in attempts:
        counts[attempt.status] = counts.get(attempt.status, 0) + 1
    return dict(sorted(counts.items()))


def _baselines(
    calendar: CalendarSnapshot,
    labels: Sequence[AvailableLabel],
    span: tuple[date, date],
    grid: Sequence[date],
) -> dict[str, dict[str, dict[date, QuantileObservation]]]:
    result: dict[str, dict[str, dict[date, QuantileObservation]]] = {}
    keep = set(grid)
    for tail in TAILS:
        attempts = ex.baseline_attempts(
            calendar, labels, alpha=tail, target_start=span[0], target_end=span[1]
        )
        result[f"{tail:g}"] = {
            model_id: {
                session: row
                for session, row in ex.observations(attempts, labels, model_id=model_id).items()
                if session in keep
            }
            for model_id in ex.BASELINE_IDS
        }
    return result


def _regime_thresholds(rows: Sequence[ex.StudyRow], before: date) -> tuple[float, float]:
    """Tercile cut points of lagged 21-session volatility on rows before the evaluated span."""
    values = [
        float(row.features["vol_21"] or 0.0)
        for row in rows
        if row.eligible and row.target_end_session < before and row.features["vol_21"] is not None
    ]
    low, high = np.quantile(values, [1 / 3, 2 / 3])
    return float(low), float(high)


def _regime_table(
    rows: Sequence[ex.StudyRow],
    baseline: Mapping[date, QuantileObservation],
    challenger: Mapping[date, QuantileObservation],
    thresholds: tuple[float, float],
    tail: float,
) -> dict[str, object]:
    from newsvar.evaluation.metrics import pinball_loss

    buckets: dict[str, list[float]] = {"low": [], "middle": [], "high": []}
    volatility = {row.target_end_session: row.features["vol_21"] for row in rows}
    for session in sorted(set(baseline).intersection(challenger)):
        value = volatility.get(session)
        if value is None:
            continue
        name = "low" if value <= thresholds[0] else "middle" if value <= thresholds[1] else "high"
        base, candidate = baseline[session], challenger[session]
        buckets[name].append(
            pinball_loss(base.return_simple, base.q_return, tail)
            - pinball_loss(candidate.return_simple, candidate.q_return, tail)
        )
    return {
        "thresholds_vol_21": list(thresholds),
        "regimes": {
            name: {
                "pairs": len(values),
                "mean_improvement": float(np.mean(values)) if values else None,
            }
            for name, values in buckets.items()
        },
    }


def sensitivity_configs(
    base: ft.FeatureConfig, dominant_source: str | None
) -> dict[str, ft.FeatureConfig]:
    """The declared rebuild-and-refit sensitivities; each is a separate feature table."""
    configs = {
        "availability_buffer_60min": replace(base, buffer_minutes=60),
        "availability_buffer_240min": replace(base, buffer_minutes=240),
        "news_delayed_one_session": replace(base, session_delay=1),
        "sentiment_lagged_5_origins": replace(base, sentiment_lag=5),
        "sentiment_lagged_20_origins": replace(base, sentiment_lag=20),
        "recap_headlines_excluded": replace(base, exclude_recaps=True),
        "counts_include_duplicates": replace(base, counts_include_duplicates=True),
    }
    if dominant_source is not None:
        configs["dominant_source_excluded"] = replace(base, exclude_source=dominant_source)
    return configs


def dominant_source(corpus: Path, before: date) -> str | None:
    """Most frequent retained publisher strictly before the development range."""
    import pandas as pd

    events = pq.read_table(
        corpus / "events.parquet", columns=["batch_time_utc", "status", "source_common_name"]
    ).to_pandas(types_mapper=pd.ArrowDtype)
    cutoff = pd.Timestamp(before, tz="UTC")
    early = events[(events["status"] == "retained") & (events["batch_time_utc"] < cutoff)]
    counts = early["source_common_name"].value_counts()
    return None if counts.empty else str(counts.index[0])


def _sensitivities(
    inputs: StudyInputs,
    labels: Sequence[AvailableLabel],
    configs: Mapping[str, ft.FeatureConfig],
    selected: Mapping[str, Mapping[str, float]],
    span: tuple[date, date],
) -> dict[str, object]:
    results: dict[str, object] = {}
    tail_key = f"{PRIMARY_TAIL:g}"
    for name, config in configs.items():
        _, rows = feature_rows(inputs, config)
        grid = _eligible_grid(rows, *span)
        runs = {
            group: _run_linear(rows, labels, group, PRIMARY_TAIL, selected[tail_key][group], span)[
                1
            ]
            for group in GROUPS
        }
        results[name] = {
            "config": ft.config_identity(config),
            "eligible_forecasts": len(grid),
            "Q2_vs_Q1": ex.paired_summary(runs["Q1"], runs["Q2"], alpha=PRIMARY_TAIL, grid=grid),
            "Q1_vs_Q0": ex.paired_summary(runs["Q0"], runs["Q1"], alpha=PRIMARY_TAIL, grid=grid),
        }
    return results


def develop(
    inputs: StudyInputs, split: Mapping[str, Any], *, with_trees: bool = True
) -> dict[str, Any]:
    """Run the declared development search and sensitivities; never touches the test range."""
    if split["design"] == "prototype_only":
        raise StudyError("The admitted sample does not support a development search.")
    calendar = load_snapshot(inputs.calendar_path)
    labels = ex.load_labels(inputs.market_dataset)
    base = ft.FeatureConfig(sampling_rate=inputs.sampling_rate)
    table_path, rows = feature_rows(inputs, base)
    span = _range(split, "development")
    grid = _eligible_grid(rows, *span)
    search: list[dict[str, object]] = []
    selected: dict[str, dict[str, float]] = {}
    chosen: dict[str, dict[str, dict[date, QuantileObservation]]] = {}
    for tail in TAILS:
        key = f"{tail:g}"
        selected[key], chosen[key] = {}, {}
        for group in GROUPS:
            losses: dict[float, float] = {}
            runs: dict[float, dict[date, QuantileObservation]] = {}
            for penalty in ex.LINEAR_PENALTIES:
                attempts, observed = _run_linear(rows, labels, group, tail, penalty, span)
                runs[penalty] = observed
                losses[penalty] = ex.mean_pinball(observed, sorted(observed), tail)
                search.append(
                    {
                        "family": "linear",
                        "group": group,
                        "tail": tail,
                        "penalty": penalty,
                        "valid_forecasts": len(observed),
                        "status_counts": _status_counts(attempts),
                        "mean_pinball": losses[penalty],
                    }
                )
            best = ex.select_candidate(losses, simplicity=lambda penalty: penalty)
            selected[key][group], chosen[key][group] = best, runs[best]
    tree_selected: dict[str, dict[str, list[int]]] = {}
    tree_chosen: dict[str, dict[str, dict[date, QuantileObservation]]] = {}
    if with_trees:
        for tail in TAILS:
            key = f"{tail:g}"
            tree_selected[key], tree_chosen[key] = {}, {}
            for group in GROUPS:
                tree_losses: dict[tuple[int, int], float] = {}
                tree_runs: dict[tuple[int, int], dict[date, QuantileObservation]] = {}
                for setting in ex.TREE_GRID:
                    attempts, observed = _run_tree(rows, labels, group, tail, setting, span)
                    tree_runs[setting] = observed
                    tree_losses[setting] = ex.mean_pinball(observed, sorted(observed), tail)
                    search.append(
                        {
                            "family": "tree",
                            "group": group,
                            "tail": tail,
                            "depth": setting[0],
                            "trees": setting[1],
                            "valid_forecasts": len(observed),
                            "status_counts": _status_counts(attempts),
                            "mean_pinball": tree_losses[setting],
                        }
                    )
                best_tree = ex.select_candidate(
                    tree_losses, simplicity=lambda setting: (-setting[0], -setting[1])
                )
                tree_selected[key][group] = list(best_tree)
                tree_chosen[key][group] = tree_runs[best_tree]
    baselines = _baselines(calendar, labels, span, grid)
    strongest: dict[str, str] = {}
    baseline_losses: dict[str, dict[str, float | None]] = {}
    for tail in TAILS:
        key = f"{tail:g}"
        baseline_losses[key] = {}
        common = [s for s in grid if all(s in baselines[key][m] for m in ex.BASELINE_IDS)]
        for model_id in ex.BASELINE_IDS:
            baseline_losses[key][model_id] = (
                ex.mean_pinball(baselines[key][model_id], common, tail) if common else None
            )
        strongest[key] = min(
            ex.BASELINE_IDS, key=lambda model_id: baseline_losses[key][model_id] or float("inf")
        )
    comparisons: dict[str, object] = {}
    for tail in TAILS:
        key = f"{tail:g}"
        models = chosen[key]
        best_baseline = baselines[key][strongest[key]]
        no_vix = _run_linear(rows, labels, "Q0", tail, selected[key]["Q0"], span, without_vix=True)[
            1
        ]
        comparisons[key] = {
            "Q2_vs_Q1": ex.paired_summary(models["Q1"], models["Q2"], alpha=tail, grid=grid),
            "Q2_vs_Q0": ex.paired_summary(models["Q0"], models["Q2"], alpha=tail, grid=grid),
            "Q1_vs_Q0": ex.paired_summary(models["Q0"], models["Q1"], alpha=tail, grid=grid),
            "Q0_vs_strongest_baseline": ex.paired_summary(
                best_baseline, models["Q0"], alpha=tail, grid=grid
            ),
            "Q2_vs_strongest_baseline": ex.paired_summary(
                best_baseline, models["Q2"], alpha=tail, grid=grid
            ),
            "Q0_with_vix_vs_without": ex.paired_summary(
                no_vix, models["Q0"], alpha=tail, grid=grid
            ),
        }
    source = dominant_source(inputs.corpus, span[0])
    configs = sensitivity_configs(base, source)
    return {
        "schema_version": "development_record_v1",
        "scope": "Development range only. No test-range outcome or forecast was computed.",
        "inputs": inputs.identity(),
        "feature_table_id": table_path.name,
        "split": dict(split),
        "development_eligible_forecasts": len(grid),
        "search": search,
        "selected_linear_penalty": selected,
        "selected_tree_setting": tree_selected,
        "baseline_mean_pinball": baseline_losses,
        "strongest_baseline": strongest,
        "model_summaries": {
            f"{tail:g}": {
                **{
                    group: ex.model_summary(
                        chosen[f"{tail:g}"][group], alpha=tail, calendar=calendar, grid=grid
                    )
                    for group in GROUPS
                },
                **{
                    model_id: ex.model_summary(
                        baselines[f"{tail:g}"][model_id], alpha=tail, calendar=calendar, grid=grid
                    )
                    for model_id in ex.BASELINE_IDS
                },
            }
            for tail in TAILS
        },
        "comparisons": comparisons,
        "dominant_training_source": source,
        "sensitivities_primary_tail": _sensitivities(inputs, labels, configs, selected, span),
        "regimes_Q2_vs_Q1_primary_tail": _regime_table(
            rows,
            chosen[f"{PRIMARY_TAIL:g}"]["Q1"],
            chosen[f"{PRIMARY_TAIL:g}"]["Q2"],
            _regime_thresholds(rows, span[0]),
            PRIMARY_TAIL,
        ),
    }


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def preregistration(
    development_path: Path, *, code_commit: str, lock_sha256: str, admission_path: Path
) -> dict[str, Any]:
    """Freeze everything the final evaluation may use, before any test outcome is read."""
    development = json.loads(development_path.read_text(encoding="utf-8"))
    body = {
        "schema_version": "preregistration_v1",
        "inputs": development["inputs"],
        "feature_table_id": development["feature_table_id"],
        "split": development["split"],
        "admission_record_sha256": file_sha256(admission_path),
        "development_record_sha256": file_sha256(development_path),
        "code_commit": code_commit,
        "lock_sha256": lock_sha256,
        "target": "S&P 500 price-index next-session close-to-close simple return",
        "information_cutoff": "30 minutes before the scheduled XNYS close; "
        "market inputs through t-1",
        "availability": "Class B: GDELT batch time + 15 minutes",
        "feature_groups": {group: list(ft.FEATURE_GROUPS[group]) for group in GROUPS},
        "fitting": {
            "refit": "first origin of each calendar month, expanding window",
            "training_rows": "eligible rows whose label was available by the refit cutoff",
            "min_training_rows": ex.MIN_TRAINING_ROWS,
            "linear": "QuantileRegressor(highs), median impute, constant filter, StandardScaler",
            "seed": ex.SEED,
        },
        "selected_linear_penalty": development["selected_linear_penalty"],
        "selected_tree_setting": development["selected_tree_setting"],
        "strongest_baseline": development["strongest_baseline"],
        "dominant_training_source": development["dominant_training_source"],
        "primary_comparison": {
            "challenger": "Q2",
            "baseline": "Q1",
            "tail": PRIMARY_TAIL,
            "metric": "mean pinball-loss difference on common eligible target sessions",
            "uncertainty": "paired moving-block bootstrap, 2,000 replications, block 20, "
            "seed 1729, "
            "95% percentile interval; blocks 10 and 5 as robustness",
            "supported_if": "mean improvement > 0 and the block-20 interval excludes zero",
            "practical_interest_relative_gain": PRACTICAL_GAIN,
        },
        "secondary_exploratory": [
            "Q2 vs Q0, Q1 vs Q0, Q0 and Q2 vs the development-selected strongest baseline",
            "Q0 with vs without VIX",
            "1% tail for every comparison (sparse; exploratory)",
            "tree challenger T0/T1/T2 with development-selected settings",
            "rebuild-and-refit sensitivities: buffer 60/240 minutes, one-session delay, sentiment "
            "lag 5/20, recap exclusion, dominant-source exclusion, raw counts",
            "ex-ante volatility regimes from training-period terciles of vol_21",
        ],
        "exclusions": "an origin is scored only if its feed window is complete, scoring "
        "coverage is at least 98%, market inputs through t-1 exist, news warm-up is complete, "
        "and a label exists",
        "no_redesign": "No feature, setting, split or method is changed after the test is opened.",
    }
    return {"preregistration_id": sha256(canonical_json(body)), **body}


def _ledger_rows(
    model: str, tail: float, rows: Mapping[date, QuantileObservation]
) -> list[dict[str, object]]:
    return [
        {
            "model_id": model,
            "tail": tail,
            "target_end_session": session,
            "q_return": row.q_return,
            "return_simple": row.return_simple,
        }
        for session, row in sorted(rows.items())
    ]


def evaluate(
    inputs: StudyInputs,
    registration: Mapping[str, Any],
    ledger: list[dict[str, object]] | None = None,
) -> dict[str, Any]:
    """Execute the frozen protocol on the test range exactly as preregistered."""
    body = {key: value for key, value in registration.items() if key != "preregistration_id"}
    if sha256(canonical_json(body)) != registration["preregistration_id"]:
        raise StudyError("Preregistration content does not match its identifier.")
    if registration["inputs"] != json.loads(canonical_json(inputs.identity())):
        raise StudyError("Study inputs differ from the preregistered inputs.")
    calendar = load_snapshot(inputs.calendar_path)
    labels = ex.load_labels(inputs.market_dataset)
    base = ft.FeatureConfig(sampling_rate=inputs.sampling_rate)
    table_path, rows = feature_rows(inputs, base)
    if table_path.name != registration["feature_table_id"]:
        raise StudyError("Feature table differs from the preregistered table.")
    split = registration["split"]
    span = _range(split, "test")
    grid = _eligible_grid(rows, *span)
    selected = registration["selected_linear_penalty"]
    linear: dict[str, dict[str, dict[date, QuantileObservation]]] = {}
    statuses: dict[str, dict[str, int]] = {}
    for tail in TAILS:
        key = f"{tail:g}"
        linear[key] = {}
        for group in GROUPS:
            attempts, observed = _run_linear(rows, labels, group, tail, selected[key][group], span)
            linear[key][group] = observed
            statuses[_model_id(group, tail)] = _status_counts(attempts)
    trees: dict[str, dict[str, dict[date, QuantileObservation]]] = {}
    for key, settings in registration["selected_tree_setting"].items():
        trees[key] = {}
        for group, setting in settings.items():
            attempts, observed = _run_tree(
                rows, labels, group, float(key), (int(setting[0]), int(setting[1])), span
            )
            trees[key][group] = observed
            statuses[_model_id(group, float(key), kind="T")] = _status_counts(attempts)
    baselines = _baselines(calendar, labels, span, grid)
    comparisons: dict[str, object] = {}
    summaries: dict[str, object] = {}
    for tail in TAILS:
        key = f"{tail:g}"
        models = linear[key]
        strongest = baselines[key][registration["strongest_baseline"][key]]
        no_vix = _run_linear(rows, labels, "Q0", tail, selected[key]["Q0"], span, without_vix=True)[
            1
        ]
        comparisons[key] = {
            "Q2_vs_Q1": ex.paired_summary(models["Q1"], models["Q2"], alpha=tail, grid=grid),
            "Q2_vs_Q0": ex.paired_summary(models["Q0"], models["Q2"], alpha=tail, grid=grid),
            "Q1_vs_Q0": ex.paired_summary(models["Q0"], models["Q1"], alpha=tail, grid=grid),
            "Q0_vs_strongest_baseline": ex.paired_summary(
                strongest, models["Q0"], alpha=tail, grid=grid
            ),
            "Q2_vs_strongest_baseline": ex.paired_summary(
                strongest, models["Q2"], alpha=tail, grid=grid
            ),
            "Q0_with_vix_vs_without": ex.paired_summary(
                no_vix, models["Q0"], alpha=tail, grid=grid
            ),
        }
        if key in trees:
            comparisons[key]["T2_vs_T1"] = ex.paired_summary(  # type: ignore[index]
                trees[key]["Q1"], trees[key]["Q2"], alpha=tail, grid=grid
            )
            comparisons[key]["T2_vs_Q2"] = ex.paired_summary(  # type: ignore[index]
                models["Q2"], trees[key]["Q2"], alpha=tail, grid=grid
            )
        summaries[key] = {
            **{
                group: ex.model_summary(models[group], alpha=tail, calendar=calendar, grid=grid)
                for group in GROUPS
            },
            **{
                f"T{group[1]}": ex.model_summary(
                    trees[key][group], alpha=tail, calendar=calendar, grid=grid
                )
                for group in (GROUPS if key in trees else ())
            },
            **{
                model_id: ex.model_summary(
                    baselines[key][model_id], alpha=tail, calendar=calendar, grid=grid
                )
                for model_id in ex.BASELINE_IDS
            },
        }
    if ledger is not None:
        for key, models in linear.items():
            for group, observed in models.items():
                ledger.extend(_ledger_rows(group, float(key), observed))
            for model_id, observed in baselines[key].items():
                ledger.extend(_ledger_rows(model_id, float(key), observed))
    primary = comparisons[f"{PRIMARY_TAIL:g}"]["Q2_vs_Q1"]  # type: ignore[index]
    interval = primary["bootstrap"]["block_20"]["interval_95"]
    supported = primary["mean_improvement"] > 0 and interval[0] > 0
    configs = sensitivity_configs(base, registration["dominant_training_source"])
    return {
        "schema_version": "final_evaluation_v1",
        "preregistration_id": registration["preregistration_id"],
        "test_range": list(split["test"]),
        "test_eligible_forecasts": len(grid),
        "status_counts": statuses,
        "model_summaries": summaries,
        "comparisons": comparisons,
        "crossings": {
            group: ex.crossing_rate(linear["0.01"][group], linear["0.05"][group])
            for group in GROUPS
        },
        "sensitivities_primary_tail": _sensitivities(inputs, labels, configs, selected, span),
        "regimes_Q2_vs_Q1_primary_tail": _regime_table(
            rows,
            linear[f"{PRIMARY_TAIL:g}"]["Q1"],
            linear[f"{PRIMARY_TAIL:g}"]["Q2"],
            _regime_thresholds(rows, span[0]),
            PRIMARY_TAIL,
        ),
        "primary_decision": {
            "mean_improvement": primary["mean_improvement"],
            "relative_gain": primary["relative_gain"],
            "interval_95_block_20": interval,
            "claim_supported": bool(supported),
            "meets_practical_interest": bool(
                supported and (primary["relative_gain"] or 0.0) >= PRACTICAL_GAIN
            ),
        },
    }
