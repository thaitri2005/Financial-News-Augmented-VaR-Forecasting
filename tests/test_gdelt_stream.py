"""Synthetic GDELT stream fixtures; ordinary tests never touch the network."""

import hashlib
import io
import zipfile
from datetime import date
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from newsvar.ingestion import gdelt


def _row(record: str, themes: str, *, title: str | None, location: str = "") -> str:
    fields = [""] * gdelt.GKG_FIELDS
    fields[0], fields[1], fields[2] = record, "20200316000000", "1"
    fields[3], fields[4] = "example.com", f"https://example.com/{record}"
    fields[7], fields[9], fields[15] = themes, location, "-2.5,1,3.5,4.5,20,0,300"
    fields[26] = "" if title is None else f"<PAGE_TITLE>{title}</PAGE_TITLE>"
    return "\t".join(fields)


def _zip(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("batch.gkg.csv", text)
    return buffer.getvalue()


PAYLOAD = (
    "\n".join(
        [
            _row(
                "a-1",
                "TAX_FNCACT;ECON_STOCKMARKET;ECON_INFLATION",
                title="Stocks &amp; bonds fall",
                location="1#United States#US#US#38#-97#US",
            ),
            _row("a-2", "ECON_STOCKMARKET_EXTRA", title="Substring theme must not match"),
            _row("a-3", "ECON_STOCKMARKET", title=None, location="1#France#FR#FR#46#2#FR"),
            _row("a-4", "EDUCATION", title="Unrelated"),
            "broken\tECON_STOCKMARKET\trow",
        ]
    )
    + "\n"
)


def test_parse_keeps_only_whole_theme_and_counts_every_row() -> None:
    records, counts = gdelt.parse_gkg("20200316000000", PAYLOAD.encode())
    assert [record["gkg_record_id"] for record in records] == ["a-1", "a-3"]
    assert records[0]["page_title_raw"] == "Stocks &amp; bonds fall"
    assert records[0]["has_us_location"] and records[0]["theme_inflation"]
    assert records[0]["gdelt_tone"] == -2.5
    assert records[1]["page_title_raw"] is None and not records[1]["has_us_location"]
    assert counts == {"rows": 5, "malformed_rows": 1, "titled_rows": 3, "matched_rows": 2}


def _catalog_file(tmp_path: Path, entries: dict[str, bytes]) -> Path:
    lines = [
        f"{len(body)} {hashlib.md5(body).hexdigest()} "
        f"http://data.gdeltproject.org/gdeltv2/{stamp}.gkg.csv.zip\n"
        for stamp, body in entries.items()
    ]
    lines.append(
        "5 " + "0" * 32 + " http://data.gdeltproject.org/gdeltv2/20200316000000.export.CSV.zip\n"
    )
    path = tmp_path / "catalog.txt"
    path.write_text("".join(lines), encoding="utf-8")
    return path


def test_day_commit_distinguishes_absent_failed_and_corrupt_batches(tmp_path: Path) -> None:
    day = date(2020, 3, 16)
    good = _zip(PAYLOAD)
    bodies = {"20200316000000": good, "20200316001500": good, "20200316003000": good}
    catalog = gdelt.read_catalog(_catalog_file(tmp_path, bodies), start=day, end=day)
    calls: list[str] = []

    def fetch(stamp: str) -> bytes:
        calls.append(stamp)
        if stamp == "20200316001500":
            return good[:-1] + b"x"
        if stamp == "20200316003000":
            raise gdelt.GdeltError("offline")
        return good

    root = tmp_path / "titles"
    manifest = gdelt.extract_day(
        day, catalog, root, catalog_sha256="c" * 64, fetch=fetch, threads=2
    )
    status = {batch["stamp"]: batch["status"] for batch in manifest["batches"]}
    assert len(status) == 96
    assert status["20200316000000"] == gdelt.OK
    assert status["20200316001500"] == gdelt.MD5_MISMATCH
    assert status["20200316003000"] == gdelt.FETCH_FAILED
    assert status["20200316004500"] == gdelt.ABSENT
    assert not gdelt.day_is_final(manifest)
    assert pq.read_table(root / "date=2020-03-16" / "titles.parquet").num_rows == 2

    # A rerun retries the non-final day; once every catalogued batch verifies it is final
    # and later runs do not fetch again.
    calls.clear()
    final = gdelt.extract_day(
        day, catalog, root, catalog_sha256="c" * 64, fetch=lambda stamp: good, threads=2
    )
    assert gdelt.day_is_final(final) and final["title_rows"] == 6
    again = gdelt.extract_day(day, catalog, root, catalog_sha256="c" * 64, fetch=fetch, threads=2)
    assert again == final and calls == []
    assert gdelt.summarize([final])["batch_status"] == {gdelt.ABSENT: 93, gdelt.OK: 3}


def test_committed_day_checksum_is_enforced(tmp_path: Path) -> None:
    day = date(2020, 3, 16)
    good = _zip(PAYLOAD)
    catalog = gdelt.read_catalog(
        _catalog_file(tmp_path, {"20200316000000": good}), start=day, end=day
    )
    root = tmp_path / "titles"
    gdelt.extract_day(day, catalog, root, catalog_sha256="c" * 64, fetch=lambda stamp: good)
    (root / "date=2020-03-16" / "titles.parquet").write_bytes(b"tampered")
    with pytest.raises(gdelt.GdeltError):
        gdelt.load_day(root, day)


def test_batch_stamp_grid_and_catalog_conflicts(tmp_path: Path) -> None:
    assert len(gdelt.expected_stamps(date(2020, 3, 16))) == 96
    with pytest.raises(gdelt.GdeltError):
        gdelt.batch_time("20200316000100")
    path = tmp_path / "catalog.txt"
    path.write_text(
        "1 " + "a" * 32 + " http://data.gdeltproject.org/gdeltv2/20200316000000.gkg.csv.zip\n"
        "2 " + "a" * 32 + " http://data.gdeltproject.org/gdeltv2/20200316000000.gkg.csv.zip\n",
        encoding="utf-8",
    )
    with pytest.raises(gdelt.GdeltError):
        gdelt.read_catalog(path, start=date(2020, 3, 16), end=date(2020, 3, 16))
