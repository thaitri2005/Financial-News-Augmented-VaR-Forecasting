"""Record non-secret execution dependencies for the feasibility artifacts."""

import importlib.metadata
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path


def main():
    packages = {}
    for name in (
        "nbformat", "nbclient", "nbconvert", "ipykernel", "jupyter_core",
        "matplotlib", "numpy", "pandas", "pyarrow", "psutil",
    ):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    record = {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "operating_system": platform.system(),
        "operating_system_release": platform.release(),
        "architecture": platform.machine(),
        "packages": packages,
        "scope": "Observed research execution environment; not a production lockfile.",
    }
    path = Path(__file__).with_name("execution_environment.json")
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record))


if __name__ == "__main__":
    main()
