"""Command-line interface: data stages, the two studies, and daily operation.

Run every command from the repository root; paths in settings files are
relative to it.
"""

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
vol_app = typer.Typer(no_args_is_help=True, add_completion=False)
app.add_typer(vol_app, name="vol")


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

    from newsvar.data.calendar import build_xnys_snapshot, write_snapshot
    from newsvar.hashing import IntegrityError

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
    from newsvar.data.calendar import load_snapshot
    from newsvar.hashing import IntegrityError

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
    ] = Path("data/raw/market/manifest.json"),
) -> None:
    """Audit retained market source dates on XNYS; report no returns or model scores."""
    from newsvar.data.calendar import load_snapshot
    from newsvar.data.market import MarketSourceError, market_coverage, retained_market_sources
    from newsvar.hashing import IntegrityError

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
    ] = Path("data/raw/market/manifest.json"),
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
    from newsvar.data.calendar import build_xnys_snapshot, load_snapshot, write_snapshot
    from newsvar.data.datasets import (
        DatasetIntegrityError,
        materialize_market_dataset,
        verify_calendar_extension,
    )
    from newsvar.data.market import MarketSourceError, retained_market_sources
    from newsvar.hashing import IntegrityError

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
    from newsvar.data.datasets import DatasetIntegrityError, load_market_dataset

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
    ] = Path("data/raw/market/manifest.json"),
) -> None:
    """Count adjacent eligible historical-proxy labels without exposing return values."""
    from newsvar.data.calendar import load_snapshot
    from newsvar.data.labels import (
        HISTORICAL_AVAILABILITY_BASIS,
        build_labels,
        historical_prior_session_availability,
    )
    from newsvar.data.market import MarketSourceError, retained_market_sources
    from newsvar.hashing import IntegrityError

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


def _gdelt_day_worker(
    arguments: tuple[str, str, str, str, int, bool],
) -> tuple[str, int, int]:
    from datetime import date as date_type

    from newsvar.data.gdelt import OK, extract_day, read_catalog

    day_text, catalog_path, output_root, catalog_sha256, threads, force = arguments
    day = date_type.fromisoformat(day_text)
    catalog = read_catalog(Path(catalog_path), start=day, end=day)
    manifest = extract_day(
        day,
        catalog,
        Path(output_root),
        catalog_sha256=catalog_sha256,
        threads=threads,
        force=force,
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
    force: Annotated[
        bool,
        typer.Option(help="Discard committed days in the range and download them again."),
    ] = False,
) -> None:
    """Stream catalogued GKG batches, keep relevance-matched titles, and commit per UTC day."""
    import hashlib
    import time
    from datetime import date as date_type
    from multiprocessing import Pool

    from newsvar.data.gdelt import day_is_final, iter_days, load_day, read_catalog

    first, last = date_type.fromisoformat(start), date_type.fromisoformat(end)
    with catalog_path.open("rb") as stream:
        catalog_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
    catalog = read_catalog(catalog_path, start=first, end=last)
    pending = []
    for day in iter_days(first, last):
        manifest = load_day(output_root, day)
        if force or manifest is None or not day_is_final(manifest, catalog):
            pending.append(day)
    del catalog
    typer.echo(f"pending_days={len(pending)} catalog_sha256={catalog_sha256}")
    started, done = time.monotonic(), 0
    chunk = processes * 4
    with Pool(processes=processes) as pool:
        for offset in range(0, len(pending), chunk):
            # The budget is checked between small chunks; queued work is never abandoned.
            if max_seconds and time.monotonic() - started >= max_seconds:
                break
            jobs = [
                (
                    day.isoformat(),
                    str(catalog_path),
                    str(output_root),
                    catalog_sha256,
                    threads,
                    force,
                )
                for day in pending[offset : offset + chunk]
            ]
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

    from newsvar.data.news import build_corpus

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
    sampling_rate: Annotated[
        float, typer.Option(min=0.0, max=1.0, help="Fixed rate; 0 derives it from the cap.")
    ] = 0.0,
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

    from newsvar.data.news import load_corpus, sample_key, sample_threshold
    from newsvar.nlp.encoder import FinbertEncoder
    from newsvar.nlp.scoring import score_titles

    manifest = load_corpus(corpus)
    unique = manifest["unique_retained_titles"]
    assert isinstance(unique, int)
    rate = sampling_rate or _sampling_rate(unique, title_cap)
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

    from newsvar.nlp.encoder import MODEL_REVISION, model_fingerprint
    from newsvar.study.pipeline import StudyInputs

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
    """Write JSON atomically; NaN is refused so records stay valid JSON."""
    import os

    path.parent.mkdir(parents=True, exist_ok=True)
    stage = path.with_name(f".{path.name}.staging")
    text = json.dumps(payload, indent=1, sort_keys=True, allow_nan=False) + "\n"
    with stage.open("w", encoding="utf-8") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(stage, path)


CONFIG_OPTION = typer.Option(exists=True, dir_okay=False, help="Study input paths JSON.")


@study_app.command("admit")
def study_admit(
    output: Annotated[Path, typer.Option(help="Admission record JSON to write.")],
    config: Annotated[Path, CONFIG_OPTION] = Path("data/study.json"),
) -> None:
    """Write the outcome-blind continuity, sample-size and split record."""
    from newsvar.study.pipeline import admission

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
    from newsvar.study.pipeline import develop

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

    from newsvar.study.pipeline import file_sha256, preregistration

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
    from newsvar.study.pipeline import evaluate as run_final

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
    from newsvar.study.report import write_report

    write_report(
        admission=json.loads(admission_record.read_text(encoding="utf-8")),
        development=json.loads(development_record.read_text(encoding="utf-8")),
        final=json.loads(final_record.read_text(encoding="utf-8")),
        ledger=ledger,
        output=output,
        figure_dir=figure_dir,
    )
    typer.echo(str(output))


def _download(url: str, destination: Path, *, max_bytes: int) -> int:
    """Stream a public file to disk atomically with an explicit size bound."""
    import urllib.request

    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = destination.with_name(destination.name + ".part")
    total = 0
    with urllib.request.urlopen(url, timeout=120) as response, stage.open("wb") as stream:  # noqa: S310
        while chunk := response.read(1 << 20):
            total += len(chunk)
            if total > max_bytes:
                raise typer.BadParameter(f"{url} exceeds the {max_bytes}-byte bound.")
            stream.write(chunk)
    stage.replace(destination)
    return total


@market_app.command("fetch")
def market_fetch(
    output_dir: Annotated[Path, typer.Option(help="Private directory for the two CSVs.")] = Path(
        "data/raw/market"
    ),
    manifest: Annotated[Path, typer.Option(help="Snapshot manifest to write.")] = Path(
        "data/raw/market/manifest.json"
    ),
) -> None:
    """Download FRED SP500 and Cboe VIX and write the dated snapshot manifest."""
    import csv
    import hashlib
    from datetime import UTC, datetime

    sources = (
        ("fred_sp500.csv", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500", "SP500"),
        (
            "cboe_vix.csv",
            "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv",
            "CLOSE",
        ),
    )
    snapshots = []
    for name, url, column in sources:
        path = output_dir / name
        size = _download(url, path, max_bytes=2 * 1024 * 1024)
        with path.open(encoding="utf-8-sig", newline="") as stream:
            values = [row[column] for row in csv.DictReader(stream)]
        snapshots.append(
            {
                "name": name,
                "url": url,
                "path": str(path),
                "bytes": size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "audit": {
                    "rows": len(values),
                    "valid_values": sum(value not in ("", ".") for value in values),
                },
            }
        )
    _write_json(
        manifest,
        {"retrieved_at_utc": datetime.now(UTC).isoformat(), "snapshots": snapshots},
    )
    typer.echo(str(manifest))


@gdelt_app.command("catalog")
def gdelt_catalog(
    output: Annotated[Path, typer.Option()] = Path("data/raw/gdelt/masterfilelist.txt"),
) -> None:
    """Download the GDELT master file list used to verify every batch."""
    size = _download(
        "https://data.gdeltproject.org/gdeltv2/masterfilelist.txt", output, max_bytes=1 << 30
    )
    typer.echo(f"{output} {size} bytes")


@news_app.command("fetch-model")
def news_fetch_model(
    output_root: Annotated[Path, typer.Option()] = Path(".cache/models/ProsusAI_finbert"),
) -> None:
    """Download the five pinned FinBERT files into a directory named after the revision."""
    import shutil

    from huggingface_hub import hf_hub_download

    from newsvar.nlp.encoder import MODEL_REVISION, REQUIRED_MODEL_FILES, model_fingerprint

    destination = output_root / MODEL_REVISION
    destination.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED_MODEL_FILES:
        cached = hf_hub_download("ProsusAI/finbert", name, revision=MODEL_REVISION)
        shutil.copyfile(cached, destination / name)
    typer.echo(f"{destination} fingerprint={model_fingerprint(destination).identity}")


@market_app.command("fetch-ohlc")
def market_fetch_ohlc(
    output_dir: Annotated[Path, typer.Option()] = Path("data/raw/market"),
    fred_csv: Annotated[Path, typer.Option(exists=True, dir_okay=False)] = Path(
        "data/raw/market/fred_sp500.csv"
    ),
) -> None:
    """Download daily bars for the S&P 500 index and SPY and validate both against FRED closes."""
    import time
    import urllib.request

    from newsvar.data import ohlc
    from newsvar.study.volatility import _read_series

    closes = _read_series(fred_csv, "observation_date", "SP500", "%Y-%m-%d")
    report: dict[str, object] = {}
    targets = (
        ("yahoo_gspc_daily.json", ohlc.INDEX_SYMBOL, ohlc.validate_against_closes),
        ("yahoo_spy_daily.json", ohlc.ETF_SYMBOL, ohlc.validate_tracking),
    )
    for name, symbol, check in targets:
        request = urllib.request.Request(  # noqa: S310
            ohlc.SOURCE_URL.format(symbol=symbol, period2=int(time.time()) + 86_400),
            headers={"User-Agent": "Mozilla/5.0"},
        )
        output = output_dir / name
        output.parent.mkdir(parents=True, exist_ok=True)
        stage = output.with_name(output.name + ".part")
        with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
            stage.write_bytes(response.read(8 * 1024 * 1024))
        bars = ohlc.parse_chart(stage)
        checked = check(bars, closes)
        stage.replace(output)
        report[name] = {
            "sha256": ohlc.file_sha256(output),
            "bars": len(bars),
            "first": min(bars).isoformat(),
            "last": max(bars).isoformat(),
            **checked,
        }
    typer.echo(json.dumps(report, indent=2))


def _vol_inputs(settings: dict[str, str]):  # type: ignore[no-untyped-def]
    from newsvar.nlp.encoder import MODEL_REVISION, model_fingerprint
    from newsvar.study import volatility as study

    snapshot = Path(settings["model_snapshot"])
    if snapshot.name != MODEL_REVISION:
        raise typer.BadParameter("Model snapshot is not the pinned FinBERT revision.")
    return study.VolatilityInputs(
        calendar_path=Path(settings["calendar_path"]),
        fred_csv=Path(settings["fred_csv"]),
        vix_csv=Path(settings["vix_csv"]),
        ohlc_json=Path(settings["ohlc_json"]),
        etf_json=Path(settings["etf_json"]),
        corpus=Path(settings["corpus"]),
        scores_root=Path(settings["scores_root"]),
        fingerprint=model_fingerprint(snapshot),
        sampling_rate=float(settings["sampling_rate"]),
    )


def _vol_setup(config: Path):  # type: ignore[no-untyped-def]
    """Load inputs, the panel and cached text shares for the volatility study."""
    import numpy as np

    from newsvar.hashing import canonical_json, sha256
    from newsvar.study import volatility as study

    settings = json.loads(config.read_text(encoding="utf-8"))
    inputs = _vol_inputs(settings)
    rows = study.build_panel(inputs)
    identity = inputs.identity()
    key = sha256(
        canonical_json(
            {
                "corpus": identity["corpus_id"],
                "calendar": identity["calendar_id"],
                "text": study.protocol_constants()["text_model"],
                "buffers": [15, study.OPEN_BUFFER.total_seconds()],
                "rows": [
                    rows[0]["session"].isoformat(),
                    rows[-1]["session"].isoformat(),
                    len(rows),
                ],
            }
        )
    )
    cache = Path(settings.get("text_cache", "data/derived/text_shares")) / f"{key}.npz"
    loaded = np.load(cache) if cache.is_file() else None
    if loaded is not None and "terms" in loaded.files:
        text = {name: loaded[name] for name in (*study.CONTRACTS, "terms")}
    else:
        text = study.text_shares(inputs, rows)
        cache.parent.mkdir(parents=True, exist_ok=True)
        stage = cache.with_name(f".{cache.stem}.staging.npz")
        np.savez_compressed(
            stage, pre_close=text["pre_close"], at_open=text["at_open"], terms=text["terms"]
        )
        stage.replace(cache)
    return study, settings, inputs, rows, text


def _source_state() -> dict[str, str]:
    """Identify the running code by content; refuse if tracked source differs from HEAD.

    Run from the repository root. The Git tree of ``src`` and the hashes of
    ``pyproject.toml`` and ``uv.lock`` do not change when a record is committed.
    """
    import subprocess

    from newsvar.data.ohlc import file_sha256

    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--", "src", "pyproject.toml", "uv.lock"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    ignored = subprocess.run(
        ["git", "status", "--porcelain", "--ignored", "--", "src"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    hidden = [line for line in ignored.splitlines() if line.startswith("!!") and ".py" in line]
    if dirty or hidden:
        typer.echo(
            "Commit source changes first: the protocol is tied to source content. "
            + (f"Ignored source files: {hidden}" if hidden else ""),
            err=True,
        )
        raise typer.Exit(4)
    tree = subprocess.run(
        ["git", "rev-parse", "HEAD:src"], check=True, capture_output=True, text=True
    ).stdout.strip()
    return {
        "src_tree": tree,
        "pyproject_sha256": file_sha256(Path("pyproject.toml")),
        "lock_sha256": file_sha256(Path("uv.lock")),
    }


VOL_CONFIG = typer.Option(exists=True, dir_okay=False, help="Volatility study settings JSON.")


@vol_app.command("develop")
def vol_develop(
    output: Annotated[Path, typer.Option(help="Development record JSON to write.")],
    config: Annotated[Path, VOL_CONFIG] = Path("data/volatility_study.json"),
) -> None:
    """Compare all models on the development range only; later rows are dropped first."""
    from datetime import date as date_type

    import numpy as np

    study, settings, inputs, rows, text = _vol_setup(config)
    start = date_type.fromisoformat(settings["development_start"])
    end = date_type.fromisoformat(settings["development_end"])
    kept = [row for row in rows if row["session"] <= end]
    forecasts = study.all_forecasts(
        kept,
        study.NEWS_VARIANTS,
        {name: text[name][: len(kept)] for name in study.CONTRACTS},
    )
    record = study.run_range(kept, forecasts, start=start, end=end)
    record["pooled_primary_model"] = {
        kind: study.pooled_test(kept, forecasts, study.PRIMARY_MODEL, kind, start=start, end=end)
        for kind in ("qlike", "fz0", "pinball")
    }
    record["text_model_choices"] = {}
    for contract in study.CONTRACTS:
        fitted = [
            item
            for session, item in forecasts[contract][study.PRIMARY_MODEL].items()
            if start <= session <= end
        ]
        penalties = sorted({item["text_alpha"] for item in fitted})
        record["text_model_choices"][contract] = {
            "penalties_chosen": penalties,
            "mean_stacking": float(np.mean([item["text_stacking"] for item in fitted])),
            "share_of_forecasts_with_zero_stacking": float(
                np.mean([item["text_stacking"] == 0 for item in fitted])
            ),
        }
    record["panel"] = study.panel_summary(kept, through=end)
    record["inputs"] = inputs.identity()
    record["scope"] = "Development range only. Rows after its end were removed before fitting."
    _write_json(output, record)
    typer.echo(str(output))


@vol_app.command("preregister")
def vol_preregister(
    development_record: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option(help="Preregistration JSON to write.")],
    config: Annotated[Path, VOL_CONFIG] = Path("data/volatility_study.json"),
) -> None:
    """Freeze the confirmatory protocol. Requires a clean committed source tree."""
    from datetime import date as date_type

    if output.exists():
        typer.echo("A preregistration already exists at this path.", err=True)
        raise typer.Exit(4)
    source = _source_state()
    study, settings, inputs, rows, _ = _vol_setup(config)
    start = date_type.fromisoformat(settings["holdout_start"])
    end = date_type.fromisoformat(settings["holdout_end"])
    record = study.preregistration(
        inputs,
        development_record,
        development_end=date_type.fromisoformat(settings["development_end"]),
        holdout_start=start,
        holdout_end=end,
        fresh_start=date_type.fromisoformat(settings["fresh_start"]),
        source=source,
        # Counts only: whether inputs and an outcome exist, never an outcome's value.
        holdout_rows=json.loads(json.dumps(study.panel_summary(rows, start=start, through=end))),
        power_note=str(settings.get("power_note", "")),
    )
    _write_json(output, record)
    typer.echo(json.dumps({"preregistration_id": record["preregistration_id"]}, indent=2))


@vol_app.command("evaluate")
def vol_evaluate(
    registration: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    config: Annotated[Path, VOL_CONFIG] = Path("data/volatility_study.json"),
    record_dir: Annotated[Path, typer.Option()] = Path("docs/records"),
    private_dir: Annotated[Path, typer.Option()] = Path("data/derived/study"),
) -> None:
    """Evaluate the holdout once, exactly as preregistered.

    The registration must be committed. Output paths derive from its identifier,
    and an "opened" marker is written before any outcome is computed, so a second
    run for the same registration is refused.
    """
    import subprocess
    from datetime import UTC, datetime

    import pyarrow as pa
    import pyarrow.parquet as pq

    from newsvar.study import volatility as study

    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(registration)], capture_output=True, text=True
    )
    changed = subprocess.run(
        ["git", "status", "--porcelain", "--", str(registration)], capture_output=True, text=True
    ).stdout.strip()
    if tracked.returncode != 0 or changed:
        typer.echo("Commit the preregistration before evaluating.", err=True)
        raise typer.Exit(4)
    source = _source_state()
    record_in = json.loads(registration.read_text(encoding="utf-8"))
    short = record_in["preregistration_id"][:12]
    output = record_dir / f"volatility_evaluation_{short}.json"
    ledger = private_dir / f"volatility_forecasts_{short}.parquet"
    marker = private_dir / f"volatility_opened_{short}.json"
    if output.exists() or ledger.exists() or marker.exists():
        typer.echo(
            "This registration has already been opened; it is not evaluated twice.", err=True
        )
        raise typer.Exit(4)
    inputs = _vol_inputs(json.loads(config.read_text(encoding="utf-8")))
    try:
        # Everything that can be checked without reading an outcome is checked before
        # the registration is marked as opened.
        study.verify_registration(inputs, record_in, source=source)
        study.check_holdout_rows(study.build_panel(inputs), record_in)
    except study.VolatilityStudyError as error:
        typer.echo(f"Evaluation refused: {error}", err=True)
        raise typer.Exit(4) from error
    private_dir.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps({"opened_at_utc": datetime.now(UTC).isoformat(), "id": short}) + "\n",
        encoding="utf-8",
    )
    rows: list[dict[str, object]] = []
    try:
        record = study.evaluate(inputs, record_in, source=source, ledger=rows)
    except (ValueError, KeyError) as error:
        typer.echo(f"Evaluation failed after the holdout was opened: {error!r}", err=True)
        raise typer.Exit(5) from error
    stage = ledger.with_name(f".{ledger.name}.staging")
    pq.write_table(pa.Table.from_pylist(rows), stage)
    stage.replace(ledger)
    _write_json(output, record)
    typer.echo(
        json.dumps({k: v for k, v in record["decisions"].items() if k != "pooled"}, indent=2)
    )


@vol_app.command("report")
def vol_report(
    registration: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    config: Annotated[Path, VOL_CONFIG] = Path("data/volatility_study.json"),
    record_dir: Annotated[Path, typer.Option()] = Path("docs/records"),
    private_dir: Annotated[Path, typer.Option()] = Path("data/derived/study"),
    figure_dir: Annotated[Path, typer.Option()] = Path("docs/figures"),
    macros: Annotated[Path, typer.Option()] = Path("report/generated.tex"),
) -> None:
    """Rebuild tables, figures and report macros from the saved evaluation and ledger."""
    from datetime import date as date_type

    from newsvar.study import volatility_report as report

    record_in = json.loads(registration.read_text(encoding="utf-8"))
    short = record_in["preregistration_id"][:12]
    evaluation = json.loads(
        (record_dir / f"volatility_evaluation_{short}.json").read_text(encoding="utf-8")
    )
    ledger = report.load_ledger(private_dir / f"volatility_forecasts_{short}.parquet")
    extra = report.summary(ledger, evaluation, record_in)
    _, _, _, rows, text = _vol_setup(config)
    terms = report.term_weights(rows, text)
    report.figures(
        ledger,
        evaluation,
        date_type.fromisoformat(record_in["fresh_slice_start"]),
        figure_dir,
        terms,
    )
    extra["term_weights_descriptive"] = terms
    _write_json(record_dir / f"volatility_summary_{short}.json", extra)
    output = record_dir / "volatility_result_tables.md"
    output.write_text(report.markdown(evaluation, record_in, extra), encoding="utf-8")
    macros.parent.mkdir(parents=True, exist_ok=True)
    macros.write_text(report.latex_macros(evaluation, record_in, extra), encoding="utf-8")
    typer.echo(str(output))


OPS_CONFIG = typer.Option(exists=True, dir_okay=False, help="Operations settings JSON.")
STUDY_CONFIGS = (Path("data/study.json"), Path("data/volatility_study.json"))


@app.command()
def update(
    config: Annotated[Path, typer.Option(help="Operations settings JSON to write.")] = Path(
        "data/operations.json"
    ),
    corpus_start: Annotated[str, typer.Option()] = "2019-09-23",
    sampling_rate: Annotated[float, typer.Option(min=0.01, max=1.0)] = 0.27,
    model_snapshot: Annotated[Path, typer.Option()] = Path(
        ".cache/models/ProsusAI_finbert/5fcfed04a2ca89adf4170ec0a4715103ed7745db"
    ),
) -> None:
    """Refresh every input up to now and write the settings used by ``forecast``.

    Steps: market closes, VIX and bars into a new dated snapshot directory; an
    exchange calendar reaching two weeks ahead; the GDELT catalog; titles for
    every day that is missing or has newly catalogued batches; the corpus;
    FinBERT scores for newly sampled titles. The settings file is replaced only
    after every step succeeded, so a failed update leaves the previous
    consistent state in use. The corpus written by the previous update is
    removed unless a study settings file refers to it.
    """
    import csv
    import shutil
    import subprocess
    from datetime import UTC, datetime, timedelta

    def run(*arguments: str) -> str:
        typer.echo("-> newsvar " + " ".join(arguments))
        done = subprocess.run(
            [sys.executable, "-m", "newsvar", *arguments],
            capture_output=True,
            text=True,
            timeout=6 * 3600,
        )
        if done.returncode != 0:
            typer.echo(done.stdout[-2000:] + done.stderr[-2000:], err=True)
            raise typer.Exit(done.returncode)
        return done.stdout

    def relative(path: str) -> str:
        resolved = Path(path).resolve()
        here = Path.cwd().resolve()
        return str(resolved.relative_to(here)) if resolved.is_relative_to(here) else path

    started = datetime.now(UTC)
    today = started.date()
    snapshot = Path("data/raw/market") / started.strftime("%Y%m%dT%H%M%SZ")
    run(
        "market",
        "fetch",
        "--output-dir",
        str(snapshot),
        "--manifest",
        str(snapshot / "manifest.json"),
    )
    fred = snapshot / "fred_sp500.csv"
    run("market", "fetch-ohlc", "--output-dir", str(snapshot), "--fred-csv", str(fred))
    with fred.open(encoding="utf-8-sig") as stream:
        first = next(
            row["observation_date"]
            for row in csv.DictReader(stream)
            if row["SP500"] not in ("", ".")
        )
    calendar = json.loads(
        run(
            "calendar", "build", "--start", first, "--end", (today + timedelta(days=14)).isoformat()
        )
    )
    run("gdelt", "catalog")
    run("gdelt", "extract", "--start", corpus_start, "--end", today.isoformat())
    corpus = json.loads(run("news", "corpus", "--start", corpus_start, "--end", today.isoformat()))
    run(
        "news",
        "score",
        "--corpus",
        corpus["path"],
        "--model-snapshot",
        str(model_snapshot),
        "--sampling-rate",
        str(sampling_rate),
    )
    previous = json.loads(config.read_text(encoding="utf-8")) if config.is_file() else {}
    settings = {
        "calendar_path": relative(calendar["path"]),
        "fred_csv": str(fred),
        "vix_csv": str(snapshot / "cboe_vix.csv"),
        "ohlc_json": str(snapshot / "yahoo_gspc_daily.json"),
        "etf_json": str(snapshot / "yahoo_spy_daily.json"),
        "corpus": relative(corpus["path"]),
        "scores_root": "data/derived/scores",
        "model_snapshot": str(model_snapshot),
        "sampling_rate": sampling_rate,
        # Inputs are known only as of the start of this update, not its end.
        "updated_at_utc": started.isoformat(),
    }
    _write_json(config, settings)
    referenced = {settings["corpus"]}
    for path in STUDY_CONFIGS:
        if path.is_file():
            referenced.add(relative(json.loads(path.read_text(encoding="utf-8")).get("corpus", "")))
    stale = previous.get("corpus")
    if stale and relative(stale) not in referenced and Path(stale).is_dir():
        if Path(stale).resolve().parent == Path("data/derived/news").resolve():
            shutil.rmtree(stale)
            typer.echo(f"removed superseded corpus {stale}")
    typer.echo(str(config))


@app.command()
def forecast(
    session: Annotated[
        str, typer.Option(help="Target session YYYY-MM-DD; default: the current and next one.")
    ] = "",
    config: Annotated[Path, OPS_CONFIG] = Path("data/operations.json"),
    log: Annotated[Path, typer.Option(help="Append-only forecast log.")] = Path(
        "data/forecasts/log.jsonl"
    ),
) -> None:
    """Issue volatility, VaR and ES forecasts from data known at the last update.

    Run ``newsvar update`` first. Without ``--session`` the session that has not
    closed yet and the one after it are both considered, so a run after 15:30
    New York time issues the pre-close forecast for the next session and a run
    after the open issues the at-open forecast for the current one. A set-up is
    forecast only when its information time has passed, the data were refreshed
    after that time and the news has been ingested up to it. Each record states
    whether it was issued on time or late and is appended to the log; earlier
    entries are never rewritten.
    """
    import os
    from datetime import UTC, datetime
    from datetime import date as date_type

    from newsvar.data.calendar import load_snapshot
    from newsvar.data.gdelt import GdeltError
    from newsvar.data.ohlc import OhlcError
    from newsvar.study.operate import forecast_session
    from newsvar.study.volatility import VolatilityStudyError, build_panel, text_shares

    settings = json.loads(config.read_text(encoding="utf-8"))
    inputs = _vol_inputs(settings)
    now = datetime.now(UTC)
    data_as_of = min(now, datetime.fromisoformat(settings["updated_at_utc"]))
    origins = load_snapshot(inputs.calendar_path).origins
    if session:
        targets = [date_type.fromisoformat(session)]
    else:
        targets = [origin.session for origin in origins if origin.close_utc > now][:2]
    if not targets:
        typer.echo("The saved calendar has no session after now; run update.", err=True)
        raise typer.Exit(4)
    try:
        rows = build_panel(inputs, as_of=data_as_of)
        shares = text_shares(inputs, rows)
        records = [
            forecast_session(
                inputs, target, as_of=now, data_as_of=data_as_of, text=shares, rows=rows
            )
            for target in targets
        ]
    except (VolatilityStudyError, OhlcError, GdeltError) as error:
        typer.echo(f"Forecast failed: {error}", err=True)
        raise typer.Exit(5) from error
    identity = inputs.identity()
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as stream:
        for record in records:
            record["inputs"] = identity
            record["issued_at_utc"] = now.isoformat()
            stream.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    typer.echo(
        json.dumps([{k: v for k, v in r.items() if k != "inputs"} for r in records], indent=2)
    )
