"""Operational forecasts: next-session volatility, VaR and ES from the validated models."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

import numpy as np

from newsvar.study import volatility as study


def contract_status(
    row: Mapping[str, Any], contract: str, *, as_of: datetime, data_as_of: datetime
) -> tuple[str, str | None]:
    """Whether one set-up can be forecast now, and if not, why."""
    _, end = row[f"window_{contract}"]
    names = [f"{name}_{contract}" for name in study.BASE_FEATURES[contract]]
    missing = [name for name in names if row.get(name) is None]
    if end > as_of:
        return "unavailable", "information time not reached"
    if end > data_as_of:
        return "unavailable", "data were refreshed before the information time; run update"
    if not row.get(f"ingested_{contract}", False):
        return "unavailable", "news not yet ingested up to the information time; run update"
    if not row[f"complete_{contract}"]:
        return "unavailable", "news window incomplete"
    if missing:
        return "unavailable", f"missing inputs: {', '.join(missing)}"
    return "ok", None


def forecast_session(
    inputs: study.VolatilityInputs,
    session: date,
    *,
    as_of: datetime,
    data_as_of: datetime | None = None,
    text: Mapping[str, np.ndarray] | None = None,
    rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Forecast one target session with the baseline and the text model for both set-ups.

    ``as_of`` is the issue time. ``data_as_of`` is when the input files were last
    refreshed (default: the issue time); a session counts as closed, and a set-up
    as ready, only relative to that time, so a partial price bar fetched during a
    session is never read as its outcome. A set-up is reported as unavailable,
    with the reason, when its information time has not passed, the data are older
    than that time, the news has not been ingested up to it, or an input is
    missing. ``timing`` says whether the forecast still precedes its target.
    """
    known = min(as_of, data_as_of) if data_as_of is not None else as_of
    panel = rows if rows is not None else study.build_panel(inputs, as_of=known)
    kept = [row for row in panel if row["session"] <= session]
    if not kept or kept[-1]["session"] != session:
        raise study.VolatilityStudyError(f"{session} is not a session of the saved calendar.")
    target = kept[-1]
    output: dict[str, Any] = {
        "target_session": session.isoformat(),
        "as_of_utc": as_of.isoformat(),
        "data_as_of_utc": known.isoformat(),
        "inputs": inputs.identity() if rows is None else None,
        "contracts": {},
    }
    statuses = {
        contract: contract_status(target, contract, as_of=as_of, data_as_of=known)
        for contract in study.CONTRACTS
    }
    shares = text
    if shares is None and any(status == "ok" for status, _ in statuses.values()):
        shares = study.text_shares(inputs, kept)
    for contract in study.CONTRACTS:
        start, end = target[f"window_{contract}"]
        status, reason = statuses[contract]
        section: dict[str, Any] = {
            "news_window_utc": [start.isoformat(), end.isoformat()],
            "status": status,
            "timing": "on_time" if as_of <= target[f"deadline_{contract}"] else "late",
        }
        if reason is not None:
            section["reason"] = reason
            output["contracts"][contract] = section
            continue
        assert shares is not None
        models = {
            "har": study.forecast_all(kept, contract, include_unlabelled=True),
            study.PRIMARY_MODEL: study.forecast_all(
                kept, contract, text=shares[contract][: len(kept)], include_unlabelled=True
            ),
        }
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
