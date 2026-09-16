"""Collect small public snapshots and audit archived GDELT metadata.

Not a full ingestion pipeline. No authentication or paid service is used.
Compressed responses have strict caps; ZIP contents are streamed, not extracted.
"""

import csv
import hashlib
import html
import io
import json
import re
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "data" / "raw" / "feasibility_20260915"
BATCHES = ["20170103200000", "20200316200000", "20220613200000", "20230313200000", "20250403200000"]
DOMAINS = {"reuters.com", "cnbc.com", "marketwatch.com", "finance.yahoo.com", "benzinga.com", "nasdaq.com", "ft.com", "wsj.com", "bloomberg.com"}
TITLE = re.compile(r"<PAGE_TITLE>(.*?)</PAGE_TITLE>", re.DOTALL)


def get_snapshot(name, url, cap):
    path = DEST / name
    if path.exists():
        payload = path.read_bytes()
        status = "local_cache"
    else:
        request = Request(url, headers={"User-Agent": "VaRResearchFeasibility/1.0"})
        with urlopen(request, timeout=30) as response:
            length = response.headers.get("Content-Length")
            if length and int(length) > cap:
                raise ValueError(f"Declared response exceeds {cap}-byte cap")
            payload = response.read(cap + 1)
            if len(payload) > cap:
                raise ValueError(f"Response exceeds {cap}-byte cap")
            status = response.status
        staged = path.with_suffix(path.suffix + ".partial")
        staged.write_bytes(payload)
        staged.replace(path)
    return payload, {"name": name, "url": url, "path": path.relative_to(ROOT).as_posix(), "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(), "http_status": status}


def market_summary(payload, value_key, date_format):
    records = list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig"))))
    date_key = next(iter(records[0]))
    valid = [(datetime.strptime(row[date_key], date_format).date(), float(row[value_key])) for row in records if row[value_key] not in ("", ".")]
    return {"rows": len(records), "valid_values": len(valid), "year_counts": dict(sorted(Counter(str(date.year) for date, value in valid).items())), "first_date": str(valid[0][0]), "last_date": str(valid[-1][0]), "nonpositive_values": sum(value <= 0 for date, value in valid), "duplicate_dates": len(valid) - len({date for date, value in valid})}


def inspect_gkg(payload, batch):
    counts = Counter()
    domains = Counter()
    eligible_domains = Counter()
    field_counts = Counter()
    date_values = Counter()
    fields_seen = set()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        if len(archive.infolist()) != 1:
            raise ValueError("Expected exactly one GKG member")
        member = archive.infolist()[0]
        if member.file_size > 256 * 1024 * 1024:
            raise ValueError("ZIP member exceeds 256 MiB uncompressed safety cap")
        with archive.open(member) as raw:
            for line in io.TextIOWrapper(raw, encoding="utf-8", errors="replace"):
                cols = line.rstrip("\r\n").split("\t")
                field_counts[len(cols)] += 1
                counts["rows"] += 1
                if len(cols) < 27:
                    counts["short_rows"] += 1
                    continue
                date_values[cols[1]] += 1
                fields_seen.update(re.findall(r"<([A-Z_]+)>", cols[26]))
                domain = (urlparse(cols[4]).hostname or cols[3]).lower().removeprefix("www.")
                domains[domain] += 1
                match = TITLE.search(cols[26])
                title = html.unescape(match.group(1)).strip() if match else ""
                counts["with_title"] += bool(title)
                counts["translated_id"] += bool(re.search(r"-T\d+$", cols[0]))
                if any(domain == base or domain.endswith("." + base) for base in DOMAINS):
                    counts["selected_finance_domains"] += 1
                    eligible_domains[domain] += 1
                    counts["selected_with_title"] += bool(title)
                    counts["selected_nontranslated_with_title"] += bool(title) and not bool(re.search(r"-T\d+$", cols[0]))
                try:
                    float(cols[15].split(",")[0])
                    counts["parseable_tone"] += 1
                except ValueError:
                    counts["missing_tone"] += 1
    return {"batch": batch, **dict(counts), "uncompressed_bytes": member.file_size, "field_counts": dict(field_counts), "distinct_date_values": dict(date_values), "extras_tags": sorted(fields_seen), "selected_domain_counts": dict(eligible_domains.most_common()), "top_domains": dict(domains.most_common(10)), "warning": "One selected 15-minute batch per year; not a representative estimate of annual financial-news coverage. Nontranslated does not independently prove English."}


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    report = {"retrieved_at_utc": datetime.now(timezone.utc).isoformat(), "scope": "Retained public market files and five archived GKG intervals; no full news corpus or model evaluation", "snapshots": []}
    specs = [("fred_sp500.csv", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500", 250_000, "SP500", "%Y-%m-%d"), ("cboe_vix.csv", "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv", 750_000, "CLOSE", "%m/%d/%Y")]
    for name, url, cap, value_key, date_format in specs:
        try:
            payload, item = get_snapshot(name, url, cap)
            item["audit"] = market_summary(payload, value_key, date_format)
        except Exception as error:
            item = {"name": name, "error": str(error)}
        report["snapshots"].append(item)
        print(json.dumps(item), flush=True)
    for batch in BATCHES:
        name = f"{batch}.gkg.csv.zip"
        try:
            payload, item = get_snapshot(name, "https://data.gdeltproject.org/gdeltv2/" + name, 16 * 1024 * 1024)
            item["audit"] = inspect_gkg(payload, batch)
        except Exception as error:
            item = {"name": name, "error": str(error)}
        report["snapshots"].append(item)
        print(json.dumps(item), flush=True)
    output = Path(__file__).with_name("retained_sample_audit.json")
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
