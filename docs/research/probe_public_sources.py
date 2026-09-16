"""Bounded, read-only public-source audit; does not build the project dataset.

Only aggregate diagnostics and content hashes are retained. Each HTTP response
is read with a hard byte cap, even if the server ignores the Range header.
Run from the repository root with Python 3.12 (standard library only).
"""

import csv
import hashlib
import io
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


SOURCES = [
    ("fred_sp500", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500", 250_000),
    ("cboe_vix", "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv", 750_000),
    ("fnspid_external_prefix", "https://huggingface.co/datasets/Zihan1004/FNSPID/resolve/main/Stock_news/All_external.csv", 1_048_576),
    ("fnspid_nasdaq_prefix", "https://huggingface.co/datasets/Zihan1004/FNSPID/resolve/main/Stock_news/nasdaq_exteral_data.csv", 1_048_576),
]


def probe(name, url, cap):
    result = {"name": name, "url": url, "byte_cap": cap}
    try:
        request = Request(url, headers={"User-Agent": "VaRResearchFeasibility/1.0", "Range": f"bytes=0-{cap - 1}"})
        with urlopen(request, timeout=30) as response:
            payload = response.read(cap)
            result.update(http_status=response.status, content_type=response.headers.get("Content-Type"), content_range=response.headers.get("Content-Range"), bytes_read=len(payload), sha256=hashlib.sha256(payload).hexdigest())
        rows = list(csv.reader(io.StringIO(payload.decode("utf-8-sig", errors="replace"))))
        header = rows[0]
        # A byte-capped prefix may end inside a multiline CSV record.
        candidates = rows[1:-1] if len(payload) == cap else rows[1:]
        records = [dict(zip(header, row)) for row in candidates if len(row) == len(header)]
        result.update(columns=header, parsed_rows=len(records), prefix_only=len(payload) == cap)
        if name.startswith("fnspid"):
            dates = [row.get("Date", "") for row in records]
            result.update(
                midnight_rows=sum("00:00:00" in date for date in dates),
                utc_suffix_rows=sum(date.endswith("UTC") for date in dates),
                distinct_symbols=len({row.get("Stock_symbol") for row in records}),
                distinct_urls=len({row.get("Url") for row in records if row.get("Url")}),
                missing_headlines=sum(not row.get("Article_title", "").strip() for row in records),
                year_counts=dict(sorted(Counter(date[:4] for date in dates).items())),
                sample_warning="Contiguous file prefix, NOT a random or representative sample; dates are unvalidated strings.",
            )
        else:
            date_column = header[0]
            value_column = "SP500" if name == "fred_sp500" else "CLOSE"
            valid = [row for row in records if row.get(value_column, "") not in ("", ".")]
            result.update(nonmissing_values=len(valid), first_date=valid[0][date_column] if valid else None, last_date=valid[-1][date_column] if valid else None)
        result["status"] = "ok"
    except Exception as error:
        result.update(status="error", error_type=type(error).__name__, error=str(error))
    return result


def main():
    report = {"inspected_at_utc": datetime.now(timezone.utc).isoformat(), "scope": "HTTP accessibility, CSV schema, and bounded prefix diagnostics; no authenticated API or point-in-time certification", "sources": []}
    for source in SOURCES:
        result = probe(*source)
        report["sources"].append(result)
        print(json.dumps(result), flush=True)
    output = Path(__file__).with_name("public_source_probe.json")
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
