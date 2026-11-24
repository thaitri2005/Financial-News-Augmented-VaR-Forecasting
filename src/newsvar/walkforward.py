"""Causal market-only walk-forward assembly, separated from forecast publication."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from newsvar.baselines import BaselineInputError, TailForecast, gaussian_ewma, historical_simulation
from newsvar.calendar import ForecastOrigin, load_snapshot
from newsvar.datasets import load_market_dataset
from newsvar.garch import (
    MAX_PERSISTENCE,
    GarchFitError,
    fit_garch_t,
    fixed_garch_state,
    simulated_tail_forecast,
)
from newsvar.provenance import canonical_json, sha256


@dataclass(frozen=True)
class AvailableLabel:
    """A known future outcome becomes training data only at its recorded availability."""

    origin_session: date
    target_end_session: date
    return_simple: float
    available_at_utc: datetime


@dataclass(frozen=True)
class ForecastAttempt:
    """One model/origin record, including visible insufficient-history failures."""

    origin_session: date
    cutoff_utc: datetime
    refit_month: bool
    model_id: str
    status: str
    eligible_labels: int
    q_return: float | None
    es_return: float | None


def eligible_labels(
    labels: Iterable[AvailableLabel], *, origin: ForecastOrigin
) -> tuple[AvailableLabel, ...]:
    """Select only earlier origins whose outcomes were usable by this cutoff."""
    selected = tuple(
        sorted(
            (
                label
                for label in labels
                if label.origin_session < origin.session
                and label.available_at_utc <= origin.cutoff_utc
            ),
            key=lambda label: label.origin_session,
        )
    )
    if len({label.origin_session for label in selected}) != len(selected):
        raise ValueError("Walk-forward labels must have unique origin sessions.")
    return selected


def _attempt(
    model: str, history: Sequence[float], *, alpha: float, refit_month: bool
) -> TailForecast:
    if model == "historical":
        return historical_simulation(history, alpha=alpha, window=250)
    if model == "ewma":
        return gaussian_ewma(history, alpha=alpha, initialization_window=63)
    raise ValueError(f"Unsupported walk-forward model: {model}")


def build_attempts(
    origins: Sequence[ForecastOrigin],
    labels: Iterable[AvailableLabel],
    *,
    alpha: float = 0.05,
    models: tuple[str, ...] = ("historical", "ewma"),
) -> tuple[ForecastAttempt, ...]:
    """Create chronological attempts without reading outcomes of their own targets."""
    if not origins:
        raise ValueError("Walk-forward origins cannot be empty.")
    labels_tuple = tuple(labels)
    if any(label.available_at_utc.tzinfo is None for label in labels_tuple):
        raise ValueError("Label availability must be timezone-aware.")
    attempts: list[ForecastAttempt] = []
    previous_month: tuple[int, int] | None = None
    for origin in origins:
        month = (origin.session.year, origin.session.month)
        refit_month = month != previous_month
        previous_month = month
        history = eligible_labels(labels_tuple, origin=origin)
        returns = [label.return_simple for label in history]
        for model in models:
            try:
                forecast = _attempt(model, returns, alpha=alpha, refit_month=refit_month)
            except BaselineInputError:
                attempts.append(
                    ForecastAttempt(
                        origin.session,
                        origin.cutoff_utc,
                        refit_month,
                        model,
                        "insufficient_or_invalid_history",
                        len(history),
                        None,
                        None,
                    )
                )
            else:
                attempts.append(
                    ForecastAttempt(
                        origin.session,
                        origin.cutoff_utc,
                        refit_month,
                        forecast.model_id,
                        "ready",
                        len(history),
                        forecast.q_return,
                        forecast.es_return,
                    )
                )
    return tuple(attempts)


def build_garch_attempts(
    origins: Sequence[ForecastOrigin],
    labels: Iterable[AvailableLabel],
    *,
    simulations: int = 50_000,
    alpha: float = 0.05,
) -> tuple[ForecastAttempt, ...]:
    """Monthly GARCH parameter refits with daily state updates from eligible labels."""
    if not origins:
        raise ValueError("Walk-forward origins cannot be empty.")
    labels_tuple = tuple(labels)
    fitted = None
    used_fallback_at_previous_refit = False
    previous_month: tuple[int, int] | None = None
    attempts: list[ForecastAttempt] = []
    for origin in origins:
        month = (origin.session.year, origin.session.month)
        refit_month = month != previous_month
        previous_month = month
        history = eligible_labels(labels_tuple, origin=origin)
        returns = [label.return_simple for label in history]
        fit_status = "ready"
        if refit_month or fitted is None:
            try:
                fitted = fit_garch_t(returns)
                used_fallback_at_previous_refit = False
            except GarchFitError:
                try:
                    if fitted is None:
                        raise
                    fitted = fit_garch_t(returns, starting_values=fitted.result.params)
                    used_fallback_at_previous_refit = False
                    fit_status = "ready_after_retry"
                except GarchFitError:
                    if fitted is None or used_fallback_at_previous_refit:
                        for model_id in ("garch_t", "filtered_historical"):
                            attempts.append(
                                ForecastAttempt(
                                    origin.session,
                                    origin.cutoff_utc,
                                    refit_month,
                                    model_id,
                                    "garch_refit_failed",
                                    len(history),
                                    None,
                                    None,
                                )
                            )
                        continue
                    used_fallback_at_previous_refit = True
                    fit_status = "fallback_previous_refit"
        try:
            state = fixed_garch_state(returns, fitted)
        except GarchFitError:
            for model_id in ("garch_t", "filtered_historical"):
                attempts.append(
                    ForecastAttempt(
                        origin.session,
                        origin.cutoff_utc,
                        refit_month,
                        model_id,
                        "garch_state_update_failed",
                        len(history),
                        None,
                        None,
                    )
                )
            continue
        for model_id, filtered in (("garch_t", False), ("filtered_historical", True)):
            try:
                forecast = simulated_tail_forecast(
                    state,
                    origin_session=origin.session,
                    model_id=model_id,
                    alpha=alpha,
                    simulations=simulations,
                    filtered_historical=filtered,
                )
            except GarchFitError:
                attempts.append(
                    ForecastAttempt(
                        origin.session,
                        origin.cutoff_utc,
                        refit_month,
                        model_id,
                        "garch_simulation_failed",
                        len(history),
                        None,
                        None,
                    )
                )
            else:
                attempts.append(
                    ForecastAttempt(
                        origin.session,
                        origin.cutoff_utc,
                        refit_month,
                        forecast.model_id,
                        fit_status,
                        len(history),
                        forecast.q_return,
                        forecast.es_return,
                    )
                )
    return tuple(attempts)


ATTEMPT_SCHEMA = pa.schema(
    [
        pa.field("origin_session", pa.date32(), nullable=False),
        pa.field("cutoff_utc", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("refit_month", pa.bool_(), nullable=False),
        pa.field("model_id", pa.string(), nullable=False),
        pa.field("status", pa.string(), nullable=False),
        pa.field("eligible_labels", pa.int32(), nullable=False),
        pa.field("q_return", pa.float64(), nullable=True),
        pa.field("es_return", pa.float64(), nullable=True),
    ]
)


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def materialize_development_attempts(
    *,
    market_dataset: Path,
    calendar_path: Path,
    output_root: Path,
    target_start: date,
    target_end: date,
) -> tuple[Path, dict[str, object]]:
    """Write a verified private development-only attempt ledger."""
    market_manifest = load_market_dataset(market_dataset)
    calendar = load_snapshot(calendar_path)
    if market_manifest["identity"]["calendar_id"] != calendar.calendar_id:
        raise ValueError("Forecast calendar does not match the market dataset manifest.")
    labels_table = pq.read_table(market_dataset / "labels.parquet")
    labels = tuple(
        AvailableLabel(
            origin_session=row["origin_session"],
            target_end_session=row["target_end_session"],
            return_simple=float(row["return_simple"]),
            available_at_utc=row["label_available_at_utc"],
        )
        for row in labels_table.to_pylist()
    )
    origins = tuple(
        origin for origin in calendar.origins if target_start <= origin.next_session <= target_end
    )
    if not origins:
        raise ValueError("Development target-end range has no calendar origins.")
    identity = {
        "schema_version": "forecast_attempts_v1",
        "market_dataset_id": market_manifest["dataset_id"],
        "calendar_id": calendar.calendar_id,
        "target_start": target_start.isoformat(),
        "target_end": target_end.isoformat(),
        "models": ["historical_w250", "gaussian_ewma_d0.94_i63"],
        "alpha": 0.05,
        "availability_rule": "label_available_at_lte_origin_cutoff_v1",
        "refit_schedule": "calendar_month_v1",
    }
    run_id = sha256(canonical_json(identity))
    destination = output_root / run_id
    if destination.exists():
        return destination, load_attempt_manifest(destination)
    attempts = build_attempts(origins, labels)
    output_root.mkdir(parents=True, exist_ok=True)
    stage = output_root / f".{run_id}.{uuid.uuid4().hex}.staging"
    stage.mkdir()
    table_path = stage / "attempts.parquet"
    pq.write_table(
        pa.Table.from_pylist([item.__dict__ for item in attempts], schema=ATTEMPT_SCHEMA),
        table_path,
    )
    with table_path.open("r+b") as stream:
        os.fsync(stream.fileno())
    manifest = {
        "run_id": run_id,
        "identity": identity,
        "attempts": {"path": table_path.name, "rows": len(attempts), "sha256": _digest(table_path)},
    }
    manifest_path = stage / "manifest.json"
    with manifest_path.open("x", encoding="utf-8") as stream:
        stream.write(canonical_json(manifest).decode("utf-8") + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    load_attempt_manifest(stage, directory_id_required=False)
    os.replace(stage, destination)
    return destination, load_attempt_manifest(destination)


def materialize_garch_development_attempts(
    *,
    market_dataset: Path,
    calendar_path: Path,
    output_root: Path,
    target_start: date,
    target_end: date,
    simulations: int = 50_000,
) -> tuple[Path, dict[str, object]]:
    """Write a private, causal GARCH/FHS development ledger and verify it."""
    if simulations < 1:
        raise ValueError("GARCH simulation count must be positive.")
    market_manifest = load_market_dataset(market_dataset)
    calendar = load_snapshot(calendar_path)
    if market_manifest["identity"]["calendar_id"] != calendar.calendar_id:
        raise ValueError("Forecast calendar does not match the market dataset manifest.")
    labels_table = pq.read_table(market_dataset / "labels.parquet")
    labels = tuple(
        AvailableLabel(
            origin_session=row["origin_session"],
            target_end_session=row["target_end_session"],
            return_simple=float(row["return_simple"]),
            available_at_utc=row["label_available_at_utc"],
        )
        for row in labels_table.to_pylist()
    )
    origins = tuple(
        origin for origin in calendar.origins if target_start <= origin.next_session <= target_end
    )
    if not origins:
        raise ValueError("Development target-end range has no calendar origins.")
    identity = {
        "schema_version": "garch_attempts_v1",
        "market_dataset_id": market_manifest["dataset_id"],
        "calendar_id": calendar.calendar_id,
        "target_start": target_start.isoformat(),
        "target_end": target_end.isoformat(),
        "models": ["garch_t", "filtered_historical"],
        "alpha": 0.05,
        "availability_rule": "label_available_at_lte_origin_cutoff_v1",
        "refit_schedule": "calendar_month_v1",
        "persistence_cap": MAX_PERSISTENCE,
        "simulation_paths": simulations,
        "horizon_steps": 2,
        "forecast_path_column": 2,
    }
    run_id = sha256(canonical_json(identity))
    destination = output_root / run_id
    if destination.exists():
        return destination, load_attempt_manifest(destination)
    attempts = build_garch_attempts(origins, labels, simulations=simulations)
    output_root.mkdir(parents=True, exist_ok=True)
    stage = output_root / f".{run_id}.{uuid.uuid4().hex}.staging"
    stage.mkdir()
    table_path = stage / "attempts.parquet"
    pq.write_table(
        pa.Table.from_pylist([item.__dict__ for item in attempts], schema=ATTEMPT_SCHEMA),
        table_path,
    )
    with table_path.open("r+b") as stream:
        os.fsync(stream.fileno())
    manifest = {
        "run_id": run_id,
        "identity": identity,
        "attempts": {"path": table_path.name, "rows": len(attempts), "sha256": _digest(table_path)},
    }
    manifest_path = stage / "manifest.json"
    with manifest_path.open("x", encoding="utf-8") as stream:
        stream.write(canonical_json(manifest).decode("utf-8") + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    load_attempt_manifest(stage, directory_id_required=False)
    os.replace(stage, destination)
    return destination, load_attempt_manifest(destination)


def load_attempt_manifest(path: Path, *, directory_id_required: bool = True) -> dict[str, object]:
    """Verify a private forecast-attempt ledger before exposing its metadata."""
    root = path.resolve(strict=True)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or set(manifest) != {"run_id", "identity", "attempts"}:
        raise ValueError("Invalid forecast-attempt manifest.")
    if (
        not isinstance(manifest["identity"], dict)
        or not isinstance(manifest["run_id"], str)
        or sha256(canonical_json(manifest["identity"])) != manifest["run_id"]
        or (directory_id_required and root.name != manifest["run_id"])
    ):
        raise ValueError("Forecast-attempt manifest identity mismatch.")
    info = manifest["attempts"]
    if not isinstance(info, dict) or set(info) != {"path", "rows", "sha256"}:
        raise ValueError("Invalid forecast-attempt table record.")
    table_path = (root / info["path"]).resolve(strict=True)
    if not table_path.is_relative_to(root) or _digest(table_path) != info["sha256"]:
        raise ValueError("Forecast-attempt table checksum mismatch.")
    metadata = pq.ParquetFile(table_path).metadata
    if metadata is None or metadata.num_rows != info["rows"]:
        raise ValueError("Forecast-attempt table row count mismatch.")
    return manifest
