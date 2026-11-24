"""Small stage CLI; implemented commands do not imply later pipeline readiness."""

import json
import sys
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
gdelt_app = typer.Typer(no_args_is_help=True, add_completion=False)
app.add_typer(gdelt_app, name="gdelt")
news_app = typer.Typer(no_args_is_help=True, add_completion=False)
app.add_typer(news_app, name="news")
study_app = typer.Typer(no_args_is_help=True, add_completion=False)
app.add_typer(study_app, name="study")


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


def _gdelt_day_worker(arguments: tuple[str, str, str, str, int]) -> tuple[str, int, int]:
    from datetime import date as date_type

    from newsvar.ingestion.gdelt import OK, extract_day, read_catalog

    day_text, catalog_path, output_root, catalog_sha256, threads = arguments
    day = date_type.fromisoformat(day_text)
    catalog = read_catalog(Path(catalog_path), start=day, end=day)
    manifest = extract_day(
        day, catalog, Path(output_root), catalog_sha256=catalog_sha256, threads=threads
    )
    batches = manifest["batches"]
    assert isinstance(batches, list)
    title_rows = manifest["title_rows"]
    assert isinstance(title_rows, int)
    return day_text, sum(batch["status"] == OK for batch in batches), title_rows


@gdelt_app.command("extract")
def gdelt_extract(
    start: Annotated[str, typer.Option(help="First UTC date, YYYY-MM-DD.")],
    end: Annotated[str, typer.Option(help="Last UTC date, YYYY-MM-DD.")],
    catalog_path: Annotated[
        Path, typer.Option(exists=True, dir_okay=False, help="Saved GDELT master file list.")
    ] = Path("data/raw/gdelt/masterfilelist.txt"),
    output_root: Annotated[Path, typer.Option(help="Committed per-day title store.")] = Path(
        "data/raw/gdelt/titles"
    ),
    processes: Annotated[int, typer.Option(min=1, max=16)] = 4,
    threads: Annotated[int, typer.Option(min=1, max=16)] = 8,
    max_seconds: Annotated[
        int, typer.Option(min=0, help="Stop starting new days after this budget; 0 is unbounded.")
    ] = 0,
) -> None:
    """Stream catalogued GKG batches, keep relevance-matched titles, and commit per UTC day."""
    import hashlib
    import time
    from datetime import date as date_type
    from multiprocessing import Pool

    from newsvar.ingestion.gdelt import day_is_final, iter_days, load_day

    first, last = date_type.fromisoformat(start), date_type.fromisoformat(end)
    with catalog_path.open("rb") as stream:
        catalog_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
    pending = []
    for day in iter_days(first, last):
        manifest = load_day(output_root, day)
        if manifest is None or not day_is_final(manifest):
            pending.append(day)
    typer.echo(f"pending_days={len(pending)} catalog_sha256={catalog_sha256}")
    started, done = time.monotonic(), 0
    jobs = (
        (day.isoformat(), str(catalog_path), str(output_root), catalog_sha256, threads)
        for day in pending
        if not max_seconds or time.monotonic() - started < max_seconds
    )
    with Pool(processes=processes) as pool:
        for day_text, ok_batches, title_rows in pool.imap(_gdelt_day_worker, jobs):
            done += 1
            typer.echo(
                f"{day_text} ok_batches={ok_batches} titles={title_rows} "
                f"done={done}/{len(pending)} elapsed={time.monotonic() - started:.0f}s"
            )
    typer.echo(f"finished days={done} remaining={len(pending) - done}")


@news_app.command("corpus")
def news_corpus(
    start: Annotated[str, typer.Option(help="First UTC date, YYYY-MM-DD.")],
    end: Annotated[str, typer.Option(help="Last UTC date, YYYY-MM-DD.")],
    title_root: Annotated[Path, typer.Option()] = Path("data/raw/gdelt/titles"),
    output_root: Annotated[Path, typer.Option()] = Path("data/derived/news"),
) -> None:
    """Normalize, filter and chronologically deduplicate committed GDELT days."""
    from datetime import date as date_type

    from newsvar.news import build_corpus

    path, manifest = build_corpus(
        title_root,
        output_root,
        start=date_type.fromisoformat(start),
        end=date_type.fromisoformat(end),
    )
    typer.echo(json.dumps({"path": str(path), **manifest}, indent=2))


def _sampling_rate(unique_titles: int, cap: int) -> float:
    import math

    return 1.0 if unique_titles <= cap else math.floor(cap / unique_titles * 100) / 100


@news_app.command("score")
def news_score(
    corpus: Annotated[Path, typer.Option(exists=True, file_okay=False)],
    model_snapshot: Annotated[Path, typer.Option(exists=True, file_okay=False)],
    scores_root: Annotated[Path, typer.Option()] = Path("data/derived/scores"),
    title_cap: Annotated[int, typer.Option(min=1)] = 1_000_000,
    batch_size: Annotated[int, typer.Option(min=1, max=256)] = 32,
    threads: Annotated[int, typer.Option(min=1, max=16)] = 4,
    max_seconds: Annotated[int, typer.Option(min=0)] = 0,
    project_root: Annotated[
        Path, typer.Option(exists=True, file_okay=False, resolve_path=True)
    ] = Path("."),
) -> None:
    """Score the frozen content-hash sample of unique titles with the pinned FinBERT."""
    import time

    preflight = collect_snapshot(project_root)
    if not evaluate(preflight, Stage.SENTIMENT).ready:
        typer.echo("Scoring paused: sentiment resource preflight did not pass.", err=True)
        raise typer.Exit(3)
    import pyarrow.parquet as pq
    import torch

    from newsvar.news import load_corpus, sample_key, sample_threshold
    from newsvar.scoring import score_titles
    from newsvar.sentiment import FinbertEncoder

    manifest = load_corpus(corpus)
    unique = manifest["unique_retained_titles"]
    assert isinstance(unique, int)
    rate = _sampling_rate(unique, title_cap)
    threshold = sample_threshold(rate)
    table = pq.read_table(corpus / "titles.parquet", columns=["content_sha256", "title_clean"])
    titles = [
        (digest, text)
        for digest, text in zip(
            table.column(0).to_pylist(), table.column(1).to_pylist(), strict=True
        )
        if sample_key(digest) < threshold
    ]
    torch.set_num_threads(threads)
    encoder = FinbertEncoder.load_local(model_snapshot)
    started = time.monotonic()

    def progress(done: int, total: int) -> None:
        elapsed = time.monotonic() - started
        typer.echo(f"scored={done}/{total} elapsed={elapsed:.0f}s rate={done / elapsed:.1f}/s")
        sys.stdout.flush()

    counts = score_titles(
        titles,
        root=scores_root,
        fingerprint=encoder.fingerprint,
        score_batch=encoder.score_batch,
        batch_size=batch_size,
        progress=progress,
        should_stop=(lambda: time.monotonic() - started > max_seconds) if max_seconds else None,
    )
    typer.echo(
        json.dumps(
            {
                "unique_retained_titles": unique,
                "sampling_rate": rate,
                "designated_titles": len(titles),
                "fingerprint": encoder.fingerprint.__dict__,
                "fingerprint_id": encoder.fingerprint.identity,
                **counts,
                "seconds": round(time.monotonic() - started, 1),
            },
            indent=2,
        )
    )


def _study_inputs(config: Path):  # type: ignore[no-untyped-def]
    from datetime import date as date_type

    from newsvar.sentiment import MODEL_REVISION, model_fingerprint
    from newsvar.study import StudyInputs

    settings = json.loads(config.read_text(encoding="utf-8"))
    snapshot = Path(settings["model_snapshot"])
    if snapshot.name != MODEL_REVISION:
        raise typer.BadParameter("Model snapshot is not the pinned FinBERT revision.")
    return StudyInputs(
        market_dataset=Path(settings["market_dataset"]),
        calendar_path=Path(settings["calendar_path"]),
        corpus=Path(settings["corpus"]),
        corpus_start=date_type.fromisoformat(settings["corpus_start"]),
        scores_root=Path(settings["scores_root"]),
        fingerprint=model_fingerprint(snapshot),
        sampling_rate=float(settings["sampling_rate"]),
        feature_root=Path(settings["feature_root"]),
    ), date_type.fromisoformat(settings["study_end"])


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")


CONFIG_OPTION = typer.Option(exists=True, dir_okay=False, help="Study input paths JSON.")


@study_app.command("admit")
def study_admit(
    output: Annotated[Path, typer.Option(help="Admission record JSON to write.")],
    config: Annotated[Path, CONFIG_OPTION] = Path("data/study.json"),
) -> None:
    """Write the outcome-blind continuity, sample-size and split record."""
    from newsvar.study import admission

    inputs, study_end = _study_inputs(config)
    record = admission(inputs, study_end=study_end)
    _write_json(output, record)
    typer.echo(json.dumps({k: record[k] for k in ("criteria", "split")}, indent=2))


@study_app.command("develop")
def study_develop(
    admission_record: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option(help="Development record JSON to write.")],
    config: Annotated[Path, CONFIG_OPTION] = Path("data/study.json"),
    trees: Annotated[bool, typer.Option(help="Include the small tree challenger.")] = True,
) -> None:
    """Run the declared development search and sensitivities; never opens the test range."""
    from newsvar.study import develop

    inputs, _ = _study_inputs(config)
    split = json.loads(admission_record.read_text(encoding="utf-8"))["split"]
    record = develop(inputs, split, with_trees=trees)
    _write_json(output, record)
    typer.echo(
        json.dumps(
            {
                "selected_linear_penalty": record["selected_linear_penalty"],
                "strongest_baseline": record["strongest_baseline"],
                "development_eligible_forecasts": record["development_eligible_forecasts"],
            },
            indent=2,
        )
    )


@study_app.command("preregister")
def study_preregister(
    admission_record: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    development_record: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option(help="Preregistration JSON to write.")],
    lock_file: Annotated[Path, typer.Option(exists=True, dir_okay=False)] = Path("uv.lock"),
) -> None:
    """Freeze the final protocol. Requires a clean committed source tree."""
    import subprocess

    from newsvar.study import file_sha256, preregistration

    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--", "src", "pyproject.toml", "uv.lock"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if dirty:
        typer.echo("Commit source changes before preregistering.", err=True)
        raise typer.Exit(4)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    record = preregistration(
        development_record,
        code_commit=commit,
        lock_sha256=file_sha256(lock_file),
        admission_path=admission_record,
    )
    _write_json(output, record)
    typer.echo(json.dumps({"preregistration_id": record["preregistration_id"]}, indent=2))


@study_app.command("evaluate")
def study_evaluate(
    registration: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option(help="Final evaluation JSON to write.")],
    config: Annotated[Path, CONFIG_OPTION] = Path("data/study.json"),
    ledger: Annotated[Path, typer.Option(help="Private per-date forecast ledger.")] = Path(
        "data/derived/study/final_forecasts.parquet"
    ),
) -> None:
    """Open the locked test range once, exactly as preregistered."""
    from newsvar.study import evaluate as run_final

    if output.exists():
        typer.echo("A final evaluation already exists; it is not overwritten.", err=True)
        raise typer.Exit(4)
    import pyarrow as pa
    import pyarrow.parquet as pq

    inputs, _ = _study_inputs(config)
    rows: list[dict[str, object]] = []
    record = run_final(inputs, json.loads(registration.read_text(encoding="utf-8")), rows)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), ledger)
    _write_json(output, record)
    typer.echo(json.dumps(record["primary_decision"], indent=2))


@study_app.command("report")
def study_report(
    admission_record: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    development_record: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    final_record: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    ledger: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option(help="Markdown results tables to write.")],
    figure_dir: Annotated[Path, typer.Option()] = Path("docs/figures"),
) -> None:
    """Rebuild result tables and figures from saved records; fits nothing."""
    from newsvar.report import write_report

    write_report(
        admission=json.loads(admission_record.read_text(encoding="utf-8")),
        development=json.loads(development_record.read_text(encoding="utf-8")),
        final=json.loads(final_record.read_text(encoding="utf-8")),
        ledger=ledger,
        output=output,
        figure_dir=figure_dir,
    )
    typer.echo(str(output))
