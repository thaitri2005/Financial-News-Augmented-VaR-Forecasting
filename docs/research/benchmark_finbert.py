"""Bounded CPU FinBERT benchmark; outputs aggregate evidence only.

The Yahoo collection is permitted here for engineering throughput only. This tool
never reads its supplied price, sentiment, entity, description, or body fields.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import os
import platform
import time
from collections import Counter
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import psutil
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from newsvar.doctor import Stage, collect_snapshot, evaluate

MODEL_ID = "ProsusAI/finbert"
MODEL_REVISION = "5fcfed04a2ca89adf4170ec0a4715103ed7745db"
RAW_DIRECTORY = Path("data/raw/feasibility_20260915")
DEFAULT_CACHE = Path("data/cache/huggingface")
RSS_LIMIT_BYTES = 6 * 1024**3


def select_titles(raw_directory: Path, count: int) -> tuple[list[str], list[dict[str, Any]]]:
    """Read only ordered English title strings until the requested bounded sample."""
    selected: list[str] = []
    lineage: list[dict[str, Any]] = []
    for path in sorted(raw_directory.glob("yahoo_*_processed.json.xz")):
        with lzma.open(path, "rt", encoding="utf-8") as stream:
            records = json.load(stream)
        accepted = 0
        for record in records:
            if record.get("language") != "en":
                continue
            title = record.get("title")
            if not isinstance(title, str) or not title.strip():
                continue
            selected.append(title.strip())
            accepted += 1
            if len(selected) == count:
                break
        lineage.append(
            {
                "path": str(path).replace("\\", "/"),
                "sha256": hashlib.file_digest(path.open("rb"), "sha256").hexdigest(),
                "titles_selected": accepted,
            }
        )
        if len(selected) == count:
            break
    if len(selected) != count:
        raise ValueError(f"Needed {count} English titles, found {len(selected)}.")
    return selected, lineage


def result_digest(labels: list[str], probabilities: list[list[float]]) -> str:
    payload = json.dumps(
        {"labels": labels, "probabilities": probabilities}, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def infer(
    titles: list[str],
    tokenizer: Any,
    model: Any,
    *,
    batch_size: int,
    process: psutil.Process,
) -> tuple[Counter[str], str, int, float]:
    labels: list[str] = []
    probabilities: list[list[float]] = []
    peak_rss = process.memory_info().rss
    started = time.perf_counter()
    with torch.inference_mode():
        for offset in range(0, len(titles), batch_size):
            encoded = tokenizer(
                titles[offset : offset + batch_size],
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="pt",
            )
            logits = model(**encoded).logits
            batch_probabilities = torch.softmax(logits, dim=1).tolist()
            for probability in batch_probabilities:
                best = max(range(len(probability)), key=probability.__getitem__)
                labels.append(str(model.config.id2label[best]))
                probabilities.append([float(value) for value in probability])
            peak_rss = max(peak_rss, process.memory_info().rss)
            if peak_rss > RSS_LIMIT_BYTES:
                raise MemoryError(f"RSS exceeded {RSS_LIMIT_BYTES} bytes during inference.")
    elapsed = time.perf_counter() - started
    return Counter(labels), result_digest(labels, probabilities), peak_rss, elapsed


def model_file_hashes(cache_path: Path) -> dict[str, str]:
    required = [
        "config.json",
        "pytorch_model.bin",
        "special_tokens_map.json",
        "tokenizer_config.json",
        "vocab.txt",
    ]
    missing = [name for name in required if not (cache_path / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Model cache is missing: {', '.join(missing)}")
    return {
        name: hashlib.file_digest((cache_path / name).open("rb"), "sha256").hexdigest()
        for name in required
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, choices=(1000, 10000), default=1000)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.batch_size < 1:
        raise ValueError("batch size must be positive")
    preflight = evaluate(collect_snapshot(Path(".")), Stage.SENTIMENT)
    if not preflight.ready:
        raise RuntimeError("Sentiment preflight did not pass; benchmark not started.")
    os.environ["HF_HOME"] = str(arguments.cache_dir.resolve())
    torch.set_num_threads(min(4, os.cpu_count() or 1))
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    titles, source_lineage = select_titles(RAW_DIRECTORY, arguments.count)
    process = psutil.Process()
    initial_rss = process.memory_info().rss
    tokenizer = AutoTokenizer.from_pretrained(
        MODEL_ID, revision=MODEL_REVISION, cache_dir=arguments.cache_dir, trust_remote_code=False
    )
    model = AutoModelForSequenceClassification.from_pretrained(
        MODEL_ID, revision=MODEL_REVISION, cache_dir=arguments.cache_dir, trust_remote_code=False
    )
    model.eval()
    cache_path = Path(model.name_or_path)
    if not cache_path.is_dir():
        from huggingface_hub import snapshot_download

        cache_path = Path(
            snapshot_download(
                MODEL_ID,
                revision=MODEL_REVISION,
                cache_dir=arguments.cache_dir,
                local_files_only=True,
            )
        )
    hashes = model_file_hashes(cache_path)
    warmup_count = min(arguments.batch_size, len(titles))
    infer(titles[:warmup_count], tokenizer, model, batch_size=arguments.batch_size, process=process)
    labels, digest, peak_rss, elapsed = infer(
        titles, tokenizer, model, batch_size=arguments.batch_size, process=process
    )
    repeat_count = min(32, len(titles))
    _, prefix_digest, prefix_peak_rss, _ = infer(
        titles[:repeat_count], tokenizer, model, batch_size=arguments.batch_size, process=process
    )
    _, repeat_digest, repeat_peak_rss, _ = infer(
        titles[:repeat_count], tokenizer, model, batch_size=arguments.batch_size, process=process
    )
    output = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "scope": (
            "Engineering-only CPU compatibility benchmark; no raw titles, scores, prices, "
            "outcomes, or predictive claim."
        ),
        "model": {
            "id": MODEL_ID,
            "revision": MODEL_REVISION,
            "cache_path": str(cache_path).replace("\\", "/"),
            "file_sha256": hashes,
            "trust_remote_code": False,
            "device": "cpu",
            "precision": "fp32",
        },
        "environment": {
            "python": platform.python_version(),
            "torch": version("torch"),
            "transformers": version("transformers"),
            "threads": torch.get_num_threads(),
            "interop_threads": torch.get_num_interop_threads(),
        },
        "sample": {
            "requested_titles": arguments.count,
            "processed_titles": sum(labels.values()),
            "batch_size": arguments.batch_size,
            "source": "retained_yahoo_engineering_only",
            "source_lineage": source_lineage,
        },
        "measurement": {
            "wall_seconds": elapsed,
            "titles_per_second": arguments.count / elapsed,
            "initial_rss_bytes": initial_rss,
            "peak_rss_bytes": max(peak_rss, prefix_peak_rss, repeat_peak_rss),
            "final_rss_bytes": process.memory_info().rss,
            "rss_limit_bytes": RSS_LIMIT_BYTES,
            "label_counts": dict(sorted(labels.items())),
            "repeat_prefix_count": repeat_count,
            "repeat_prefix_match": prefix_digest == repeat_digest,
            "full_digest": digest,
            "repeat_prefix_digest": repeat_digest,
        },
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"output": str(arguments.output), "measurement": output["measurement"]}, indent=2
        )
    )


if __name__ == "__main__":
    main()
