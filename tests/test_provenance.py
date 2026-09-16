"""Restart/integrity fixtures exercise externally meaningful commit boundaries."""

from pathlib import Path

import pytest

from newsvar.provenance import IntegrityError, RawStore, StoragePathError


def page(store: RawStore, payload: bytes = b'{"news":[{"id":1}]}'):
    return store.commit(
        source_id="synthetic",
        ingestion_run_id="run_1",
        request_identity={"start": "2020-01-01T00:00:00Z", "page": 1, "cursor_hash": "no_cursor"},
        payload=payload,
        row_count=1,
        is_interval_complete=True,
        source_terms_record="fixture_only",
        adapter_version="fixture_v1",
    )


def test_replay_and_changed_payload_get_stable_distinct_ids(tmp_path: Path) -> None:
    store = RawStore(tmp_path / "raw")
    first = page(store)
    replay = page(store)
    changed = page(store, b'{"news":[{"id":2}]}')
    assert first.directory == replay.directory
    assert replay.manifest.retrieved_at_utc == first.manifest.retrieved_at_utc
    assert changed.manifest.raw_id != first.manifest.raw_id
    assert changed.directory.is_dir() and first.payload_path.read_bytes() == b'{"news":[{"id":1}]}'


def test_interruption_after_payload_keeps_partial_stage_invisible(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "raw"
    store = RawStore(root)

    def interrupt(boundary: str) -> None:
        if boundary == "payload_written":
            raise RuntimeError("simulated stop before manifest")

    monkeypatch.setattr(store, "_transition", interrupt)
    with pytest.raises(RuntimeError):
        page(store)
    assert not list((root / "committed" / "synthetic").iterdir())
    assert len(list((root / ".staging" / "synthetic").iterdir())) == 1
    artifact = page(RawStore(root))
    assert artifact.payload_path.is_file()
    assert len(list((root / "committed" / "synthetic").iterdir())) == 1
    assert len(list((root / ".staging" / "synthetic").iterdir())) == 1  # identifiable orphan


def test_valid_stage_resumes_after_stop_before_rename(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "raw"
    store = RawStore(root)

    def interrupt(boundary: str) -> None:
        if boundary == "ready_to_commit":
            raise RuntimeError("simulated stop before directory rename")

    monkeypatch.setattr(store, "_transition", interrupt)
    with pytest.raises(RuntimeError):
        page(store)
    assert not list((root / "committed" / "synthetic").iterdir())
    artifact = page(RawStore(root))
    assert artifact.manifest.state == "committed"
    assert not list((root / ".staging" / "synthetic").iterdir())


def test_staged_metadata_conflict_does_not_publish_artifact(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "raw"
    store = RawStore(root)

    def interrupt(boundary: str) -> None:
        if boundary == "ready_to_commit":
            raise RuntimeError("simulated stop")

    monkeypatch.setattr(store, "_transition", interrupt)
    with pytest.raises(RuntimeError):
        page(store)
    with pytest.raises(IntegrityError, match="metadata"):
        store.commit(
            source_id="synthetic",
            ingestion_run_id="run_2",
            request_identity={
                "start": "2020-01-01T00:00:00Z",
                "page": 1,
                "cursor_hash": "no_cursor",
            },
            payload=b'{"news":[{"id":1}]}',
            row_count=2,
            is_interval_complete=True,
            source_terms_record="fixture_only",
            adapter_version="fixture_v1",
        )
    assert not list((root / "committed" / "synthetic").iterdir())


def test_stop_after_rename_replays_visible_commit(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "raw"
    store = RawStore(root)

    def interrupt(boundary: str) -> None:
        if boundary == "committed":
            raise RuntimeError("simulated stop before cursor advancement")

    monkeypatch.setattr(store, "_transition", interrupt)
    with pytest.raises(RuntimeError):
        page(store)
    artifact = page(RawStore(root))
    assert artifact.payload_path.is_file()
    assert len(list((root / "committed" / "synthetic").iterdir())) == 1


def test_corrupt_committed_payload_is_never_reused(tmp_path: Path) -> None:
    store = RawStore(tmp_path / "raw")
    artifact = page(store)
    artifact.payload_path.write_bytes(b'{"news":[{"id":9}]}')
    with pytest.raises(IntegrityError, match="checksum"):
        store.load("synthetic", artifact.manifest.raw_id)
    with pytest.raises(IntegrityError):
        page(store)


def test_replay_with_changed_parsed_row_count_is_rejected(tmp_path: Path) -> None:
    store = RawStore(tmp_path / "raw")
    page(store)
    with pytest.raises(IntegrityError, match="metadata"):
        store.commit(
            source_id="synthetic",
            ingestion_run_id="run_2",
            request_identity={
                "start": "2020-01-01T00:00:00Z",
                "page": 1,
                "cursor_hash": "no_cursor",
            },
            payload=b'{"news":[{"id":1}]}',
            row_count=2,
            is_interval_complete=True,
            source_terms_record="fixture_only",
            adapter_version="fixture_v1",
        )


def test_reject_secret_identity_and_escaped_storage_paths(tmp_path: Path) -> None:
    store = RawStore(tmp_path / "raw")
    with pytest.raises(ValueError):
        store.commit(
            source_id="../escape",
            ingestion_run_id="run_1",
            request_identity={"page_token": "live_cursor"},
            payload=b"x",
            row_count=0,
            is_interval_complete=True,
            source_terms_record="fixture_only",
            adapter_version="fixture_v1",
        )
    with pytest.raises(StoragePathError):
        store._inside(tmp_path)  # private check guards all constructed paths
    with pytest.raises(ValueError, match="credential"):
        store.commit(
            source_id="synthetic",
            ingestion_run_id="run_1",
            request_identity={"api_key": "sensitive"},
            payload=b"x",
            row_count=0,
            is_interval_complete=True,
            source_terms_record="fixture_only",
            adapter_version="fixture_v1",
        )
