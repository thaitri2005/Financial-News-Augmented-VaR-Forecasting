"""Operational forecasts: next-session volatility, VaR and ES from the validated models."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

import numpy as np

from newsvar.study import volatility as study


def forecast_session(
    inputs: study.VolatilityInputs,
    session: date,
    *,
    as_of: datetime,
    text: Mapping[str, np.ndarray] | None = None,
    rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Forecast one target session with the baseline and the text model for both contracts.

    Only information dated at or before ``as_of`` is treated as known: sessions
    that have not closed have no outcome, and later rows are dropped. A contract
    is reported as unavailable, with the reason, when an input is missing.
    """
    panel = rows if rows is not None else study.build_panel(inputs, as_of=as_of)
    kept = [row for row in panel if row["session"] <= session]
    if not kept or kept[-1]["session"] != session:
        raise study.VolatilityStudyError(f"{session} is not a session of the saved calendar.")
    shares = text if text is not None else study.text_shares(inputs, kept)
    target = kept[-1]
    output: dict[str, Any] = {
        "target_session": session.isoformat(),
        "as_of_utc": as_of.isoformat(),
        "inputs": inputs.identity(),
        "contracts": {},
    }
    for contract in study.CONTRACTS:
        start, end = target[f"window_{contract}"]
        section: dict[str, Any] = {
            "news_window_utc": [start.isoformat(), end.isoformat()],
            "news_window_complete": bool(target[f"complete_{contract}"]),
            "information_time_passed": end <= as_of,
        }
        names = [f"{name}_{contract}" for name in study.BASE_FEATURES[contract]]
        missing = [name for name in names if target.get(name) is None]
        if missing or not target[f"complete_{contract}"] or end > as_of:
            section["status"] = "unavailable"
            section["reason"] = (
                "information time not reached"
                if end > as_of
                else "news window incomplete"
                if not target[f"complete_{contract}"]
                else f"missing inputs: {', '.join(missing)}"
            )
            output["contracts"][contract] = section
            continue
        models = {
            "har": study.forecast_all(kept, contract, include_unlabelled=True),
            study.PRIMARY_MODEL: study.forecast_all(
                kept, contract, text=shares[contract][: len(kept)], include_unlabelled=True
            ),
        }
        section["status"] = "ok"
        section["models"] = {}
        for name, forecasts in models.items():
            record = forecasts.get(session)
            if record is None:
                section["models"][name] = {"status": "unavailable"}
                continue
            section["models"][name] = {
                "volatility_daily": float(np.sqrt(record["variance"])),
                "var_95_return": record["q_0.05"],
                "es_95_return": record["es_0.05"],
                "var_99_return": record["q_0.01"],
                "es_99_return": record["es_0.01"],
                "tail_from_out_of_sample_history": bool(record["tail_source_out_of_sample"]),
                **({"text_stacking": record["text_stacking"]} if "text_stacking" in record else {}),
            }
        output["contracts"][contract] = section
    return output
