"""Small stage CLI; implemented commands do not imply later pipeline readiness."""

import json
from pathlib import Path
from typing import Annotated

import typer

from newsvar.doctor import GIB, Stage, collect_snapshot, evaluate, make_report

app = typer.Typer(no_args_is_help=True, add_completion=False)
calendar_app = typer.Typer(no_args_is_help=True, add_completion=False)
app.add_typer(calendar_app, name="calendar")
market_app = typer.Typer(no_args_is_help=True, add_completion=False)
app.add_typer(market_app, name="market")
labels_app = typer.Typer(no_args_is_help=True, add_completion=False)
app.add_typer(labels_app, name="labels")


@app.callback()
def main() -> None:
    """Local financial-news VaR research tools."""


@app.command()
def doctor(
    stage: Annotated[Stage, typer.Option(help="Requested preflight stage.")] = Stage.DIAGNOSTICS,
    project_root: Annotated[
        Path,
        typer.Option(
            exists=True, file_okay=False, resolve_path=True, help="Project storage volume."
        ),
    ] = Path("."),
    json_output: Annotated[
        bool, typer.Option("--json", help="Write structured JSON to stdout.")
    ] = False,
) -> None:
    """Inspect current resources and timezones without reading data or credentials."""
    snapshot = collect_snapshot(project_root)
    report = make_report(snapshot, stage)
    if json_output:
        typer.echo(json.dumps(report, indent=2))
    else:
        typer.echo(f"Preflight {stage.value}: {'ready' if report['ready'] else 'blocked'}")
        typer.echo(
            f"Python {snapshot.python_version}; "
            f"available RAM {snapshot.ram_available_bytes / GIB:.2f} GiB"
        )
        typer.echo(
            f"Free disk {snapshot.disk_free_bytes / GIB:.2f} GiB; "
            f"process RSS {snapshot.process_tree_rss_bytes / GIB:.3f} GiB"
        )
        typer.echo("Run with --json for all stage gates, reasons, and scope limitations.")
        if not report["ready"]:
            for reason in evaluate(snapshot, stage).reasons:
                typer.echo(f"- {reason}")
    raise typer.Exit(code=0 if report["ready"] else 3)


@calendar_app.command("build")
def calendar_build(
    start: Annotated[str, typer.Option(help="First requested YYYY-MM-DD date (inclusive).")],
    end: Annotated[str, typer.Option(help="Last requested YYYY-MM-DD date (inclusive).")],
    output_dir: Annotated[Path, typer.Option(help="Directory for immutable calendar JSON.")] = Path(
        "data/calendars"
    ),
) -> None:
    """Build and save a versioned XNYS pre-close origin grid."""
    from datetime import date

    from newsvar.calendar import build_xnys_snapshot, write_snapshot
    from newsvar.provenance import IntegrityError

    try:
        snapshot = build_xnys_snapshot(date.fromisoformat(start), date.fromisoformat(end))
        path = write_snapshot(snapshot, output_dir)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    except (OSError, IntegrityError) as exc:
        typer.echo(f"Calendar build failed: {exc}", err=True)
        raise typer.Exit(5) from exc
    typer.echo(
        json.dumps(
            {
                "calendar_id": snapshot.calendar_id,
                "path": str(path.resolve()),
                "requested_start": start,
                "requested_end": end,
                "origins": len(snapshot.origins),
                "package_version": snapshot.calendar_package_version,
                "tzdata_version": snapshot.tzdata_version,
            },
            indent=2,
        )
    )


@calendar_app.command("inspect")
def calendar_inspect(
    path: Annotated[Path, typer.Argument(exists=True, file_okay=True, dir_okay=False)],
) -> None:
    """Validate and summarize a saved XNYS calendar file."""
    from newsvar.calendar import load_snapshot
    from newsvar.provenance import IntegrityError

    try:
        snapshot = load_snapshot(path)
    except IntegrityError as exc:
        typer.echo(f"Calendar validation failed: {exc}", err=True)
        raise typer.Exit(5) from exc
    typer.echo(
        json.dumps(
            {
                "calendar_id": snapshot.calendar_id,
                "origins": len(snapshot.origins),
                "first_origin": snapshot.origins[0].session.isoformat(),
                "last_origin": snapshot.origins[-1].session.isoformat(),
                "package_version": snapshot.calendar_package_version,
            },
            indent=2,
        )
    )


@market_app.command("audit")
def market_audit(
    calendar_path: Annotated[
        Path,
        typer.Option(exists=True, file_okay=True, dir_okay=False, help="Frozen calendar JSON."),
    ],
    project_root: Annotated[
        Path, typer.Option(exists=True, file_okay=False, resolve_path=True)
    ] = Path("."),
    audit_manifest: Annotated[
        Path, typer.Option(exists=True, file_okay=True, dir_okay=False)
    ] = Path("docs/research/retained_sample_audit.json"),
) -> None:
    """Audit retained market source dates on XNYS; report no returns or model scores."""
    from newsvar.calendar import load_snapshot
    from newsvar.ingestion.market import MarketSourceError, market_coverage, retained_market_sources
    from newsvar.provenance import IntegrityError

    try:
        snapshot = load_snapshot(calendar_path)
        sp500, vix = retained_market_sources(project_root, audit_manifest)
        report = market_coverage(snapshot, sp500, vix).report(sp500, vix)
    except (IntegrityError, MarketSourceError, OSError, ValueError) as exc:
        typer.echo(f"Market audit failed: {exc}", err=True)
        raise typer.Exit(5) from exc
    typer.echo(json.dumps(report, indent=2))


@market_app.command("materialize")
def market_materialize(
    calendar_path: Annotated[
        Path,
        typer.Option(
            exists=True, file_okay=True, dir_okay=False, help="Original frozen calendar JSON."
        ),
    ],
    project_root: Annotated[
        Path, typer.Option(exists=True, file_okay=False, resolve_path=True)
    ] = Path("."),
    audit_manifest: Annotated[
        Path, typer.Option(exists=True, file_okay=True, dir_okay=False)
    ] = Path("docs/research/retained_sample_audit.json"),
    output_dir: Annotated[
        Path, typer.Option(help="Versioned private derived-dataset directory.")
    ] = Path("data/derived/market"),
    extended_end: Annotated[
        str, typer.Option(help="Extended XNYS origin end YYYY-MM-DD.")
    ] = "2026-01-02",
    study_target_end: Annotated[
        str, typer.Option(help="Last allowed label target-end session YYYY-MM-DD.")
    ] = "2025-12-31",
) -> None:
    """Write immutable market/label Parquet tables after the normalization resource gate."""
    from datetime import date

    preflight = collect_snapshot(project_root)
    if not evaluate(preflight, Stage.NORMALIZATION).ready:
        typer.echo("Market materialization paused: normalization preflight did not pass.", err=True)
        raise typer.Exit(3)
    from newsvar.calendar import build_xnys_snapshot, load_snapshot, write_snapshot
    from newsvar.datasets import (
        DatasetIntegrityError,
        materialize_market_dataset,
        verify_calendar_extension,
    )
    from newsvar.ingestion.market import MarketSourceError, retained_market_sources
    from newsvar.provenance import IntegrityError

    try:
        original = load_snapshot(calendar_path)
        end = date.fromisoformat(extended_end)
        target_end = date.fromisoformat(study_target_end)
        extended = build_xnys_snapshot(original.requested_start, end)
        verify_calendar_extension(original, extended)
        extended_path = write_snapshot(extended, calendar_path.parent)
        sp500, vix = retained_market_sources(project_root, audit_manifest)
        dataset_path, manifest = materialize_market_dataset(
            output_dir, extended, sp500, vix, study_target_end=target_end
        )
    except (DatasetIntegrityError, IntegrityError, MarketSourceError, OSError, ValueError) as exc:
        typer.echo(f"Market materialization failed: {exc}", err=True)
        raise typer.Exit(5) from exc
    tables = manifest["tables"]
    typer.echo(
        json.dumps(
            {
                "dataset_id": manifest["dataset_id"],
                "path": str(dataset_path.resolve()),
                "extended_calendar_id": extended.calendar_id,
                "extended_calendar_path": str(extended_path.resolve()),
                "market_observation_rows": tables["market_observations"]["rows"],
                "label_rows": tables["labels"]["rows"],
                "label_exclusion_rows": tables["label_exclusions"]["rows"],
                "study_target_end": study_target_end,
                "scope": "Versioned tables and admission counts only; no return/model report.",
            },
            indent=2,
        )
    )


@market_app.command("inspect")
def market_inspect(
    dataset_path: Annotated[
        Path,
        typer.Argument(exists=True, file_okay=False, dir_okay=True),
    ],
) -> None:
    """Validate a versioned market dataset without disclosing outcomes."""
    from newsvar.datasets import DatasetIntegrityError, load_market_dataset

    try:
        manifest = load_market_dataset(dataset_path)
    except (DatasetIntegrityError, OSError, ValueError) as exc:
        typer.echo(f"Market dataset validation failed: {exc}", err=True)
        raise typer.Exit(5) from exc
    typer.echo(
        json.dumps(
            {
                "dataset_id": manifest["dataset_id"],
                "calendar_id": manifest["identity"]["calendar_id"],
                "study_target_end": manifest["identity"]["study_target_end"],
                "market_observation_rows": manifest["tables"]["market_observations"]["rows"],
                "label_rows": manifest["tables"]["labels"]["rows"],
                "label_exclusion_rows": manifest["tables"]["label_exclusions"]["rows"],
                "scope": "Integrity and row counts only; no return/model report.",
            },
            indent=2,
        )
    )


@labels_app.command("audit")
def labels_audit(
    calendar_path: Annotated[
        Path,
        typer.Option(exists=True, file_okay=True, dir_okay=False, help="Frozen calendar JSON."),
    ],
    project_root: Annotated[
        Path, typer.Option(exists=True, file_okay=False, resolve_path=True)
    ] = Path("."),
    audit_manifest: Annotated[
        Path, typer.Option(exists=True, file_okay=True, dir_okay=False)
    ] = Path("docs/research/retained_sample_audit.json"),
) -> None:
    """Count adjacent eligible historical-proxy labels without exposing return values."""
    from newsvar.calendar import load_snapshot
    from newsvar.ingestion.market import MarketSourceError, retained_market_sources
    from newsvar.labels import (
        HISTORICAL_AVAILABILITY_BASIS,
        build_labels,
        historical_prior_session_availability,
    )
    from newsvar.provenance import IntegrityError

    try:
        snapshot = load_snapshot(calendar_path)
        sp500, _ = retained_market_sources(project_root, audit_manifest)
        available = historical_prior_session_availability(snapshot, sp500)
        report = build_labels(
            snapshot,
            sp500,
            available,
            availability_basis=HISTORICAL_AVAILABILITY_BASIS,
        ).quality_report()
    except (IntegrityError, MarketSourceError, OSError, ValueError) as exc:
        typer.echo(f"Label audit failed: {exc}", err=True)
        raise typer.Exit(5) from exc
    typer.echo(json.dumps(report, indent=2))
