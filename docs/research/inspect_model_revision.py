"""Resolve historical FinBERT metadata without downloading model weights."""

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


def metadata(url):
    request = Request(url, headers={"User-Agent": "VaRResearchFeasibility/1.0"})
    with urlopen(request, timeout=30) as response:
        payload = response.read(128 * 1024 + 1)
    if len(payload) > 128 * 1024:
        raise ValueError("Metadata response exceeds cap")
    return json.loads(payload)


def main():
    base = "https://huggingface.co/api/models/ProsusAI/finbert"
    commits = metadata(base + "/commits/main")
    match = next(x for x in commits if x["id"].startswith("5fcfed0"))
    snapshot = metadata(base + "/revision/" + match["id"])
    record = {
        "inspected_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": "ProsusAI/finbert",
        "historical_commit": match,
        "resolved_sha": snapshot["sha"],
        "files": [x["rfilename"] for x in snapshot.get("siblings", [])],
        "scope": "Metadata only; model weights not downloaded or executed.",
    }
    Path(__file__).with_name("finbert_revision_audit.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(record))


if __name__ == "__main__":
    main()
