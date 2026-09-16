"""Audit all seven small academic news files without loading the corpus at once."""

import hashlib
import json
import lzma
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "data/raw/feasibility_20260915"


def iter_array(path):
    decoder = json.JSONDecoder()
    with lzma.open(path, "rt", encoding="utf-8") as stream:
        buf = ""
        started = False
        eof = False
        while True:
            if not eof and len(buf) < 65536:
                chunk = stream.read(65536)
                eof = not chunk
                buf += chunk
            buf = buf.lstrip()
            if not started:
                if not buf.startswith("["):
                    raise ValueError("Expected JSON array")
                buf = buf[1:]
                started = True
                continue
            buf = buf.lstrip()
            if buf.startswith(","):
                buf = buf[1:]
                continue
            if buf.startswith("]"):
                return
            try:
                value, end = decoder.raw_decode(buf)
            except json.JSONDecodeError:
                if eof:
                    raise
                chunk = stream.read(65536)
                eof = not chunk
                buf += chunk
                if len(buf) > 8 * 1024 * 1024:
                    raise ValueError("Individual record exceeds parser buffer cap")
                continue
            yield value
            buf = buf[end:]


def parse_time(value):
    if not value:
        return None
    time = datetime.fromisoformat(value.replace("Z", "+00:00"))
    # The original source README explicitly describes publication/download as UTC.
    return time.replace(tzinfo=timezone.utc) if time.tzinfo is None else time.astimezone(timezone.utc)


def percentile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * q)]


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    report = {"inspected_at_utc": datetime.now(timezone.utc).isoformat(), "source": "https://github.com/FelixDrinkall/financial-news-dataset", "files": [], "warning": "Source-file completeness is not complete-news-feed coverage. Crawl timestamps require original archive provenance; no supplied price, sentiment, or entity enrichment is used."}
    for year in range(2017, 2024):
        path = DEST / f"yahoo_{year}_processed.json.xz"
        url = f"https://raw.githubusercontent.com/FelixDrinkall/financial-news-dataset/main/data/{year}_processed.json.xz"
        if not path.exists():
            request = Request(url, headers={"User-Agent": "VaRResearchFeasibility/1.0"})
            with urlopen(request, timeout=45) as response:
                total = 0
                staged = path.with_suffix(".partial")
                with staged.open("wb") as out:
                    while chunk := response.read(256 * 1024):
                        total += len(chunk)
                        if total > 48 * 1024 * 1024:
                            raise ValueError("File exceeds 48 MiB download cap")
                        out.write(chunk)
                staged.replace(path)
        counts = Counter()
        languages = Counter()
        publish_dates = Counter()
        crawl_dates = Counter()
        lags = []
        fields = set()
        for row in iter_array(path):
            counts["rows"] += 1
            fields.update(row)
            languages[str(row.get("language"))] += 1
            counts["missing_title"] += not bool(row.get("title"))
            counts["with_modified_time"] += bool(row.get("date_modify"))
            try:
                published = parse_time(row.get("date_publish"))
                crawled = parse_time(row.get("date_download"))
            except ValueError:
                counts["unparseable_timestamp_rows"] += 1
                continue
            if published:
                publish_dates[published.date().isoformat()] += 1
                counts["publication_midnight"] += published.hour == published.minute == published.second == 0
            else:
                counts["missing_publication"] += 1
            if crawled:
                crawl_dates[crawled.date().isoformat()] += 1
            else:
                counts["missing_crawl"] += 1
            if published and crawled:
                lag = (crawled - published).total_seconds() / 3600
                lags.append(lag)
                counts["negative_crawl_lag"] += lag < 0
                counts["crawl_lag_over_24h"] += lag > 24
                counts["crawl_lag_over_7d"] += lag > 168
        with path.open("rb") as source_file:
            digest = hashlib.file_digest(source_file, "sha256").hexdigest()
        item = {"year_file": year, "url": url, "path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": digest, **dict(counts), "languages": dict(languages), "publication_days": len(publish_dates), "crawl_days": len(crawl_dates), "first_publication": min(publish_dates, default=None), "last_publication": max(publish_dates, default=None), "first_crawl": min(crawl_dates, default=None), "last_crawl": max(crawl_dates, default=None), "median_crawl_lag_hours": statistics.median(lags) if lags else None, "p90_crawl_lag_hours": percentile(lags, .9), "contains_future_price_fields": any(k.startswith("next_day_price_") for k in fields)}
        report["files"].append(item)
        print(json.dumps(item), flush=True)
    report["total_rows"] = sum(x["rows"] for x in report["files"])
    report["total_bytes"] = sum(x["bytes"] for x in report["files"])
    Path(__file__).with_name("yahoo_collection_audit.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
