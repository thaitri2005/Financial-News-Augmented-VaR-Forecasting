"""Volatility-first study: does a news surprise improve a HAR volatility forecast and its VaR/ES?

Two forecast contracts are evaluated on identical machinery.

``pre_close``  Forecast for session s made 30 minutes before the close of s-1.
               Market inputs through the close of s-2; news from the pre-close
               window ending at that cutoff. Target: close-to-close return and
               variance of session s.
``at_open``    Forecast for session s made at its open, on the SPY exchange-traded
               fund because the index's own opening value is partly stale. Market
               inputs through the close of s-1 plus SPY's overnight gap; news that
               arrived between the previous close and 15 minutes before the open.
               Target: SPY open-to-close return and variance of session s.

For each contract a baseline HAR model (lagged variances and VIX, plus the gap
for ``at_open``) is compared with the same model plus one news-surprise term.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from newsvar.data.calendar import load_snapshot
from newsvar.data.news import load_corpus
from newsvar.data.ohlc import (
    file_sha256,
    parse_chart,
    parse_dividends,
    validate_against_closes,
    validate_tracking,
)
from newsvar.evaluation.inference import (
    diebold_mariano,
    dynamic_quantile,
    fz0,
    giacomini_white,
    qlike,
)
from newsvar.evaluation.metrics import block_bootstrap_mean, kupiec_test, pinball_loss
from newsvar.features.intervals import ToneIndex, expanding_surprise
from newsvar.hashing import canonical_json, sha256
from newsvar.nlp.scoring import ScoreFingerprint, load_scores
from newsvar.volatility.har import HarError, fit_log_variance
from newsvar.volatility.proxies import close_to_close_variance, garman_klass, overnight_variance
from newsvar.volatility.tail import StandardizedTail, standardized_tail
from newsvar.volatility.text_ridge import fit_text_residual

CONTRACTS = ("pre_close", "at_open")
LAG = {"pre_close": 2, "at_open": 1}
TAILS = (0.05, 0.01)
MIN_TRAINING_ROWS = 250
MIN_TAIL_HISTORY = 250
MIN_SCORED_HEADLINES = 20
MIN_SCORING_COVERAGE = 0.98
MIN_PAIRS = 60
TEXT_MODEL = "text_ridge"
TEXT_VOCABULARY_END = datetime(2020, 12, 31, 23, 59, 59, tzinfo=UTC)
TEXT_MAX_FEATURES = 5000
TEXT_MIN_DOCUMENTS = 200
BOOTSTRAP_BLOCKS = (20, 10, 5)
OPEN_BUFFER = timedelta(minutes=15)
ISSUE_GRACE = timedelta(minutes=30)
BASE_FEATURES = {
    "pre_close": ("har_d", "har_w", "har_m", "log_vix"),
    "at_open": ("har_d", "har_w", "har_m", "log_vix", "gap"),
}
PRIMARY_NEWS = "negative_share_surprise"
PRIMARY_MODEL = "har+text_ridge"
NEWS_VARIANTS = (
    "negative_share_surprise",
    "negative_mean_surprise",
    "negative_share_level",
    "count_surprise",
)


class VolatilityStudyError(ValueError):
    """A stage was asked to run outside its declared gate or on inconsistent inputs."""


@dataclass(frozen=True)
class VolatilityInputs:
    calendar_path: Path
    fred_csv: Path
    vix_csv: Path
    ohlc_json: Path
    etf_json: Path
    corpus: Path
    scores_root: Path
    fingerprint: ScoreFingerprint
    sampling_rate: float

    def identity(self) -> dict[str, object]:
        return {
            "calendar_id": load_snapshot(self.calendar_path).calendar_id,
            "fred_sha256": file_sha256(self.fred_csv),
            "vix_sha256": file_sha256(self.vix_csv),
            "ohlc_sha256": file_sha256(self.ohlc_json),
            "etf_sha256": file_sha256(self.etf_json),
            "scores_sha256": scores_digest(self.scores_root, self.fingerprint),
            "corpus_id": load_corpus(self.corpus)["corpus_id"],
            "score_fingerprint_id": self.fingerprint.identity,
            "sampling_rate": self.sampling_rate,
        }


def scores_digest(root: Path, fingerprint: ScoreFingerprint) -> str:
    """Hash of the committed score parts, so later scoring cannot silently change eligibility."""
    directory = root / fingerprint.identity
    parts = sorted(directory.glob("part-*.parquet")) if directory.is_dir() else []
    return sha256("\n".join(f"{part.name}:{file_sha256(part)}" for part in parts).encode())


def _read_series(path: Path, date_column: str, value_column: str, fmt: str) -> dict[date, float]:
    values: dict[date, float] = {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            raw = row[value_column]
            if raw in ("", "."):
                continue
            values[datetime.strptime(row[date_column], fmt).date()] = float(raw)
    return values


def _log_mean(values: Sequence[float]) -> float:
    return float(np.log(np.mean(values)))


def build_panel(inputs: VolatilityInputs, *, as_of: datetime | None = None) -> list[dict[str, Any]]:
    """One row per target session with both contracts' inputs and outcomes.

    Each input column is built only from data dated at or before the contract's
    information time; outcome columns (``ret_*``, ``var_*``) belong to session s.

    With ``as_of`` (operations), a session that has not closed by that time has no
    outcome and contributes nothing to later rows, even if a partial bar exists.
    """
    calendar = load_snapshot(inputs.calendar_path)
    closes = _read_series(inputs.fred_csv, "observation_date", "SP500", "%Y-%m-%d")
    vix = _read_series(inputs.vix_csv, "DATE", "CLOSE", "%m/%d/%Y")
    bars = parse_chart(inputs.ohlc_json)
    validate_against_closes(bars, closes)
    etf = parse_chart(inputs.etf_json)
    validate_tracking(etf, closes)
    dividends = parse_dividends(inputs.etf_json)
    tone = ToneIndex(
        inputs.corpus,
        load_scores(inputs.scores_root, inputs.fingerprint),
        sampling_rate=inputs.sampling_rate,
    )
    origins = list(calendar.origins)
    sessions = [origin.session for origin in origins]
    intraday: list[float | None] = []
    daily: list[float | None] = []
    for position, session in enumerate(sessions):
        bar, fund = bars.get(session), etf.get(session)
        previous = closes.get(sessions[position - 1]) if position else None
        if as_of is not None and origins[position].close_utc > as_of:
            daily.append(None)
            intraday.append(None)
            continue
        # The index open is partly stale at 09:30. The stale part cancels in the
        # close-to-close sum, so index bars serve the pre-close contract only; the
        # at-open contract uses the fund's bars, which start from an opening auction.
        daily.append(
            None
            if bar is None or previous is None
            else close_to_close_variance(previous, bar.open, bar.high, bar.low, bar.close)
        )
        intraday.append(
            None if fund is None else garman_klass(fund.open, fund.high, fund.low, fund.close)
        )
    rows: list[dict[str, Any]] = []
    for position in range(24, len(sessions)):
        session, origin = sessions[position], origins[position]
        prior, prior2 = origins[position - 1], origins[position - 2]
        fund, fund_before = etf.get(session), etf.get(prior.session)
        row: dict[str, Any] = {"session": session, "month": (session.year, session.month)}
        close, last_close = closes.get(session), closes.get(prior.session)
        closed = as_of is None or origin.close_utc <= as_of
        if not closed:
            close = None
        row["ret_pre_close"] = None if None in (close, last_close) else close / last_close - 1.0  # type: ignore[operator]
        row["var_pre_close"] = daily[position]
        row["ret_at_open"] = None if fund is None or not closed else fund.close / fund.open - 1.0
        row["var_at_open"] = intraday[position]
        for contract, lag, history in (("pre_close", 2, daily), ("at_open", 1, intraday)):
            window = history[position - lag - 21 : position - lag + 1]
            anchor = origins[position - lag].session
            level = vix.get(anchor)
            if any(value is None for value in window) or level is None:
                row[f"har_d_{contract}"] = None
                continue
            values = [float(value) for value in window if value is not None]
            row[f"har_d_{contract}"] = float(np.log(values[-1]))
            row[f"har_w_{contract}"] = _log_mean(values[-5:])
            row[f"har_m_{contract}"] = _log_mean(values)
            row[f"log_vix_{contract}"] = float(2.0 * np.log(level / 100.0))
            row[f"mean22_{contract}"] = float(np.mean(values))
            known_close, earlier_close = (
                closes.get(anchor),
                closes.get(origins[position - lag - 1].session),
            )
            row[f"last_return_{contract}"] = (
                None if None in (known_close, earlier_close) else known_close / earlier_close - 1.0  # type: ignore[operator]
            )
        if fund is not None and fund_before is not None and row.get("mean22_at_open"):
            # Add back a cash dividend on its ex-date so the gap is a total return.
            opened = fund.open + dividends.get(session, 0.0)
            row["gap_at_open"] = float(
                np.log1p(overnight_variance(fund_before.close, opened) / row["mean22_at_open"])
            )
        else:
            row["gap_at_open"] = None
        windows = {
            "pre_close": (prior2.cutoff_utc, prior.cutoff_utc),
            "at_open": (prior.close_utc, origin.open_utc - OPEN_BUFFER),
        }
        # A forecast issued after these times no longer precedes its target period.
        row["deadline_pre_close"] = prior.close_utc
        row["deadline_at_open"] = origin.open_utc + ISSUE_GRACE
        for contract, (start, end) in windows.items():
            summary = tone.query(start, end)
            hours = (end - start).total_seconds() / 3600.0
            row[f"window_{contract}"] = (start, end)
            row[f"ingested_{contract}"] = tone.ingested_through(end)
            row[f"complete_{contract}"] = summary.complete
            row[f"scored_{contract}"] = summary.scored
            row[f"covered_{contract}"] = (
                summary.scored >= MIN_SCORED_HEADLINES
                and summary.scored >= MIN_SCORING_COVERAGE * summary.designated
            )
            row[f"negative_share_level_{contract}"] = summary.negative_share
            row[f"negative_mean_level_{contract}"] = summary.negative_mean
            row[f"count_level_{contract}"] = float(np.log1p(24.0 * summary.retained / hours))
        rows.append(row)
    _add_surprises(rows)
    return rows


def _add_surprises(rows: list[dict[str, Any]]) -> None:
    """Attach expanding-window news surprises for each contract and tone measure."""
    months = [row["month"] for row in rows]
    refit = [index == 0 or months[index] != months[index - 1] for index in range(len(rows))]
    for contract in CONTRACTS:
        lag = LAG[contract]
        known = [index - lag for index in range(len(rows))]
        for measure in ("negative_share", "negative_mean", "count"):
            level = [
                row[f"{measure}_level_{contract}"]
                if row[f"complete_{contract}"] and row[f"covered_{contract}"]
                else None
                for row in rows
            ]
            previous = [None, *level[:-1]]
            controls = np.asarray(
                [
                    [
                        _nan(row.get(f"log_vix_{contract}")),
                        _nan(row.get(f"last_return_{contract}")),
                        _nan(previous[index]),
                    ]
                    for index, row in enumerate(rows)
                ]
            )
            surprise = expanding_surprise(level, controls, refit, known)
            for row, value in zip(rows, surprise, strict=True):
                row[f"{measure}_surprise_{contract}"] = value


def _nan(value: float | None) -> float:
    return float("nan") if value is None else float(value)


def ineligibility(row: Mapping[str, Any], contract: str) -> str | None:
    """First reason a row cannot be used for this contract, or None when it can."""
    if any(row.get(f"{name}_{contract}") is None for name in BASE_FEATURES[contract]):
        return "market_inputs_missing"
    if row.get(f"ret_{contract}") is None or row.get(f"var_{contract}") is None:
        return "outcome_missing"
    if not row[f"complete_{contract}"]:
        return "news_window_incomplete"
    if not row[f"covered_{contract}"]:
        return "too_few_scored_headlines"
    if any(row.get(f"{name}_{contract}") is None for name in NEWS_VARIANTS):
        return "news_surprise_warmup_or_gap"
    return None


def _eligible(row: Mapping[str, Any], contract: str) -> bool:
    return ineligibility(row, contract) is None


def text_shares(
    inputs: VolatilityInputs, rows: Sequence[Mapping[str, Any]]
) -> dict[str, np.ndarray]:
    """Term shares of every row's news window, with the vocabulary frozen at a declared date.

    The returned mapping also carries the vocabulary under the key ``terms``.
    """
    from newsvar.features.text_index import TextIndex

    index = TextIndex(
        inputs.corpus,
        vocabulary_end=TEXT_VOCABULARY_END,
        max_features=TEXT_MAX_FEATURES,
        min_document_count=TEXT_MIN_DOCUMENTS,
    )
    output = {
        contract: index.shares([row[f"window_{contract}"] for row in rows])
        for contract in CONTRACTS
    }
    output["terms"] = np.asarray(index.terms)
    return output


def _features_ready(row: Mapping[str, Any], contract: str, names: Sequence[str]) -> bool:
    """Inputs for a forecast exist and the news window is complete; the outcome may be unknown."""
    return bool(row[f"complete_{contract}"]) and all(row.get(name) is not None for name in names)


def forecast_all(
    rows: Sequence[Mapping[str, Any]],
    contract: str,
    news: Sequence[str] = (),
    *,
    text: np.ndarray | None = None,
    include_unlabelled: bool = False,
) -> dict[date, dict[str, float]]:
    """Monthly-refit expanding forecasts of variance, VaR and ES over every feasible session.

    Refits happen on the first row of each calendar month and are retried until
    enough training rows exist. The standardized tail comes from past
    out-of-sample forecasts once 250 of them have known outcomes; before that it
    comes from in-sample fitted volatilities. With ``text`` the HAR residual is
    additionally regressed on window term shares.

    Study runs forecast only rows that pass every eligibility rule, so all models
    share one sample. With ``include_unlabelled`` (operations) a row is also
    forecast when its inputs exist and its news window is complete even though
    its outcome is not known yet; such rows never enter training or the tail.
    """
    names = [f"{name}_{contract}" for name in (*BASE_FEATURES[contract], *news)]
    lag = LAG[contract]
    usable = [index for index, row in enumerate(rows) if _eligible(row, contract)]
    matrix = {index: [float(rows[index][name]) for name in names] for index in usable}
    if include_unlabelled:
        for index, row in enumerate(rows):
            if index not in matrix and _features_ready(row, contract, names):
                matrix[index] = [float(row[name]) for name in names]
    labelled = set(usable)
    forecasts: dict[date, dict[str, float]] = {}
    realized: list[tuple[int, float]] = []
    fitted = None
    text_fit = None
    residual_variance = 0.0
    in_sample: dict[float, StandardizedTail] = {}
    month: tuple[int, int] | None = None
    for index, row in enumerate(rows):
        if row["month"] != month or fitted is None:
            month = row["month"]
            training = [item for item in usable if item <= index - lag]
            fitted, text_fit, in_sample = None, None, {}
            if len(training) >= MIN_TRAINING_ROWS:
                targets = np.asarray([rows[item][f"var_{contract}"] for item in training])
                try:
                    fitted = fit_log_variance(
                        names, np.asarray([matrix[item] for item in training]), targets
                    )
                except HarError:
                    fitted = None
                if fitted is not None:
                    logs = np.asarray([fitted.log_forecast(matrix[item]) for item in training])
                    residual_variance = fitted.residual_variance
                    if text is not None:
                        text_fit = fit_text_residual(text[training], np.log(targets) - logs)
                        # With zero stacking the model is exactly the HAR baseline.
                        if text_fit.stacking > 0:
                            logs = logs + text_fit.out_of_fold
                            residual_variance = float(
                                np.var(np.log(targets) - logs, ddof=len(names) + 1)
                            )
                    volatility = np.sqrt(np.exp(logs + 0.5 * residual_variance))
                    returns = [rows[item][f"ret_{contract}"] for item in training]
                    in_sample = {
                        alpha: standardized_tail(returns, volatility, alpha=alpha)
                        for alpha in TAILS
                    }
        if fitted is None or index not in matrix:
            continue
        log_forecast = fitted.log_forecast(matrix[index])
        if text_fit is not None and text is not None and text_fit.stacking > 0:
            log_forecast += float(text_fit.predict(text[index : index + 1])[0])
        variance = float(np.exp(log_forecast + 0.5 * residual_variance))
        volatility_now = float(np.sqrt(variance))
        known = [value for position, value in realized if position <= index - lag]
        record = {
            "variance": variance,
            "tail_source_out_of_sample": float(len(known) >= MIN_TAIL_HISTORY),
        }
        if text_fit is not None:
            record["text_alpha"] = text_fit.alpha
            record["text_stacking"] = text_fit.stacking
        for alpha in TAILS:
            tail = (
                standardized_tail(known, np.ones(len(known)), alpha=alpha)
                if len(known) >= MIN_TAIL_HISTORY
                else in_sample[alpha]
            )
            record[f"q_{alpha:g}"], record[f"es_{alpha:g}"] = tail.forecast(volatility_now)
        forecasts[row["session"]] = record
        if index in labelled:
            realized.append((index, float(row[f"ret_{contract}"]) / volatility_now))
    return forecasts


def historical_simulation(
    rows: Sequence[Mapping[str, Any]], contract: str, *, window: int = 250
) -> dict[date, dict[str, float]]:
    """Rolling empirical quantile and tail mean of the contract's own past returns."""
    lag = LAG[contract]
    forecasts: dict[date, dict[str, float]] = {}
    returns = [row[f"ret_{contract}"] for row in rows]
    for index, row in enumerate(rows):
        history = [value for value in returns[: max(index - lag + 1, 0)] if value is not None]
        if len(history) < window:
            continue
        ordered = np.sort(np.asarray(history[-window:]))
        record: dict[str, float] = {}
        for alpha in TAILS:
            mass = alpha * len(ordered)
            whole = int(np.floor(mass))
            record[f"q_{alpha:g}"] = float(np.quantile(ordered, alpha, method="linear"))
            record[f"es_{alpha:g}"] = float(
                (ordered[:whole].sum() + (mass - whole) * ordered[whole]) / mass
            )
        forecasts[row["session"]] = record
    return forecasts


def _mean_test(differences: Sequence[float] | np.ndarray) -> dict[str, float]:
    """Diebold-Mariano test, with identical forecasts reported as a tie instead of noise."""
    values = np.asarray(differences, dtype=np.float64)
    if np.abs(values).max() < 1e-12:
        return {
            "mean_difference": 0.0,
            "statistic": 0.0,
            "p_value_two_sided": 1.0,
            "p_value_challenger_better": 0.5,
            "lags": 0.0,
            "observations": float(len(values)),
        }
    return diebold_mariano(values)


def _paired(
    baseline: Sequence[float], challenger: Sequence[float], grid: Sequence[float | None]
) -> dict[str, Any]:
    differences = np.asarray(baseline) - np.asarray(challenger)
    base_mean = float(np.mean(baseline))
    return {
        "pairs": len(differences),
        "baseline_mean": base_mean,
        "challenger_mean": float(np.mean(challenger)),
        "mean_improvement": float(differences.mean()),
        # A ratio is meaningful only for a positive loss scale; FZ0 means are negative.
        "relative_gain": float(differences.mean() / base_mean) if base_mean > 0 else None,
        "diebold_mariano": _mean_test(differences),
        "bootstrap": {
            f"block_{length}": block_bootstrap_mean(grid, block_length=length)
            for length in BOOTSTRAP_BLOCKS
        },
    }


def compare(
    rows: Sequence[Mapping[str, Any]],
    contract: str,
    baseline: Mapping[date, Mapping[str, float]],
    challenger: Mapping[date, Mapping[str, float]],
    *,
    start: date,
    end: date,
) -> dict[str, Any]:
    """Paired variance, VaR and joint VaR/ES comparisons on common sessions in a range."""
    by_session = {row["session"]: row for row in rows}
    grid_sessions = [row["session"] for row in rows if start <= row["session"] <= end]
    common = [s for s in grid_sessions if s in baseline and s in challenger]
    result: dict[str, Any] = {"pairs": len(common), "grid": len(grid_sessions)}
    if len(common) < MIN_PAIRS:
        result["status"] = "too_few_pairs"
        return result
    result["status"] = "estimated"

    def losses(model: Mapping[date, Mapping[str, float]], kind: str, alpha: float) -> list[float]:
        output = []
        for session in common:
            row, forecast = by_session[session], model[session]
            observed = row[f"ret_{contract}"]
            if kind == "qlike":
                output.append(qlike(row[f"var_{contract}"], forecast["variance"]))
            elif kind == "pinball":
                output.append(pinball_loss(observed, forecast[f"q_{alpha:g}"], alpha))
            else:
                output.append(
                    fz0(observed, forecast[f"q_{alpha:g}"], forecast[f"es_{alpha:g}"], alpha)
                )
        return output

    def grid(base: list[float], other: list[float]) -> list[float | None]:
        lookup = dict(zip(common, np.asarray(base) - np.asarray(other), strict=True))
        return [None if s not in lookup else float(lookup[s]) for s in grid_sessions]

    if "variance" in baseline[common[0]] and "variance" in challenger[common[0]]:
        base, other = losses(baseline, "qlike", 0.0), losses(challenger, "qlike", 0.0)
        result["qlike"] = _paired(base, other, grid(base, other))
        differences = np.asarray(base) - np.asarray(other)
        instruments = np.asarray(
            [
                [
                    by_session[s][f"log_vix_{contract}"],
                    abs(by_session[s][f"{PRIMARY_NEWS}_{contract}"]),
                ]
                for s in common
            ]
        )
        result["qlike"]["giacomini_white"] = giacomini_white(
            differences, instruments - instruments.mean(axis=0), horizon=LAG[contract]
        )
        yearly: dict[str, list[float]] = {}
        for session, value in zip(common, differences, strict=True):
            yearly.setdefault(str(session.year), []).append(float(value))
        result["qlike"]["yearly"] = {
            year: {"pairs": len(values), "mean_improvement": float(np.mean(values))}
            for year, values in sorted(yearly.items())
        }
    for alpha in TAILS:
        base, other = losses(baseline, "pinball", alpha), losses(challenger, "pinball", alpha)
        result[f"pinball_{alpha:g}"] = _paired(base, other, grid(base, other))
        base, other = losses(baseline, "fz0", alpha), losses(challenger, "fz0", alpha)
        result[f"fz0_{alpha:g}"] = _paired(base, other, grid(base, other))
    return result


def calibration(
    rows: Sequence[Mapping[str, Any]],
    contract: str,
    model: Mapping[date, Mapping[str, float]],
    sessions: Sequence[date],
) -> dict[str, Any]:
    """Coverage, mean losses and dynamic-quantile diagnostics on a given session set."""
    by_session = {row["session"]: row for row in rows}
    summary: dict[str, Any] = {"forecasts": len(sessions)}
    if not sessions:
        return summary
    if "variance" in model[sessions[0]]:
        summary["mean_qlike"] = float(
            np.mean(
                [qlike(by_session[s][f"var_{contract}"], model[s]["variance"]) for s in sessions]
            )
        )
    for alpha in TAILS:
        observed = [by_session[s][f"ret_{contract}"] for s in sessions]
        quantiles = [model[s][f"q_{alpha:g}"] for s in sessions]
        shortfalls = [model[s][f"es_{alpha:g}"] for s in sessions]
        hits = [value < quantile for value, quantile in zip(observed, quantiles, strict=True)]
        summary[f"tail_{alpha:g}"] = {
            "breaches": int(sum(hits)),
            "expected": alpha * len(sessions),
            "mean_pinball": float(
                np.mean(
                    [pinball_loss(y, q, alpha) for y, q in zip(observed, quantiles, strict=True)]
                )
            ),
            "mean_fz0": float(
                np.mean(
                    [
                        fz0(y, q, e, alpha)
                        for y, q, e in zip(observed, quantiles, shortfalls, strict=True)
                    ]
                )
            ),
            "kupiec": kupiec_test(int(sum(hits)), len(sessions), alpha),
            # Missing sessions are treated as adjacent; read with the forecast count in mind.
            "dynamic_quantile": dynamic_quantile(hits, quantiles, alpha)
            if len(sessions) >= 100
            else {"status": "not_estimable"},
        }
    return summary


Forecasts = dict[str, dict[str, dict[date, dict[str, float]]]]


def all_forecasts(
    rows: Sequence[Mapping[str, Any]],
    variants: Sequence[str],
    text: Mapping[str, np.ndarray] | None = None,
) -> Forecasts:
    """Every model's forecasts for both contracts, produced once over the whole panel."""
    output: Forecasts = {}
    for contract in CONTRACTS:
        models = {
            "har": forecast_all(rows, contract),
            "historical_simulation": historical_simulation(rows, contract),
        }
        for variant in variants:
            models[f"har+{variant}"] = forecast_all(rows, contract, (variant,))
        if text is not None:
            models[f"har+{TEXT_MODEL}"] = forecast_all(rows, contract, text=text[contract])
        output[contract] = models
    return output


def run_range(
    rows: Sequence[Mapping[str, Any]], forecasts: Forecasts, *, start: date, end: date
) -> dict[str, Any]:
    """Compare every model with the HAR baseline on one range of target sessions."""
    output: dict[str, Any] = {"range": [start.isoformat(), end.isoformat()], "contracts": {}}
    for contract in CONTRACTS:
        models = forecasts[contract]
        in_range = [row["session"] for row in rows if start <= row["session"] <= end]
        common = [s for s in in_range if all(s in model for model in models.values())]
        section: dict[str, Any] = {
            "sessions_in_range": len(in_range),
            "common_forecasts": len(common),
            "models": {
                name: calibration(rows, contract, model, common) for name, model in models.items()
            },
            "comparisons": {
                "har_vs_historical_simulation": compare(
                    rows,
                    contract,
                    models["historical_simulation"],
                    models["har"],
                    start=start,
                    end=end,
                )
            },
        }
        for name, model in models.items():
            if name.startswith("har+"):
                section["comparisons"][f"{name[4:]}_vs_har"] = compare(
                    rows, contract, models["har"], model, start=start, end=end
                )
        output["contracts"][contract] = section
    return output


def panel_summary(
    rows: Sequence[Mapping[str, Any]], *, through: date, start: date | None = None
) -> dict[str, Any]:
    """Outcome-blind row counts, drop reasons and headline counts by contract."""
    summary: dict[str, Any] = {}
    for contract in CONTRACTS:
        yearly: dict[str, int] = {}
        reasons: dict[str, int] = {}
        scored: list[int] = []
        for row in rows:
            if row["session"] > through or (start is not None and row["session"] < start):
                continue
            reason = ineligibility(row, contract)
            if reason is None:
                key = str(row["session"].year)
                yearly[key] = yearly.get(key, 0) + 1
                scored.append(row[f"scored_{contract}"])
            else:
                reasons[reason] = reasons.get(reason, 0) + 1
        summary[contract] = {
            "eligible_rows": sum(yearly.values()),
            "by_year": yearly,
            "ineligible_by_reason": dict(sorted(reasons.items())),
            "median_scored_headlines": float(np.median(scored)) if scored else None,
        }
    return summary


def daily_differences(
    rows: Sequence[Mapping[str, Any]],
    contract: str,
    baseline: Mapping[date, Mapping[str, float]],
    challenger: Mapping[date, Mapping[str, float]],
    kind: str,
    *,
    alpha: float = 0.05,
) -> dict[date, float]:
    """Baseline loss minus challenger loss per common session; positive favors the challenger."""
    output: dict[date, float] = {}
    for row in rows:
        session = row["session"]
        if session not in baseline or session not in challenger:
            continue
        observed, proxy = row[f"ret_{contract}"], row[f"var_{contract}"]
        pair = []
        for model in (baseline[session], challenger[session]):
            if kind == "qlike":
                pair.append(qlike(proxy, model["variance"]))
            elif kind == "pinball":
                pair.append(pinball_loss(observed, model[f"q_{alpha:g}"], alpha))
            else:
                pair.append(fz0(observed, model[f"q_{alpha:g}"], model[f"es_{alpha:g}"], alpha))
        output[session] = pair[0] - pair[1]
    return output


def pooled_test(
    rows: Sequence[Mapping[str, Any]],
    forecasts: Forecasts,
    challenger: str,
    kind: str,
    *,
    start: date,
    end: date,
) -> dict[str, Any]:
    """One test across both contracts: the session-wise average of their loss improvements."""
    per_contract = {
        contract: daily_differences(
            rows, contract, forecasts[contract]["har"], forecasts[contract][challenger], kind
        )
        for contract in CONTRACTS
    }
    grid = [row["session"] for row in rows if start <= row["session"] <= end]
    values: list[float | None] = [
        float(np.mean([per_contract[c][s] for c in CONTRACTS]))
        if all(s in per_contract[c] for c in CONTRACTS)
        else None
        for s in grid
    ]
    valid = [value for value in values if value is not None]
    if len(valid) < MIN_PAIRS:
        return {"status": "too_few_pairs", "pairs": len(valid)}
    return {
        "status": "estimated",
        "pairs": len(valid),
        "mean_improvement": float(np.mean(valid)),
        "diebold_mariano": _mean_test(valid),
        "bootstrap": {
            f"block_{length}": block_bootstrap_mean(values, block_length=length)
            for length in BOOTSTRAP_BLOCKS
        },
    }


def protocol_constants() -> dict[str, Any]:
    """Every constant that defines the confirmatory analysis; frozen into the preregistration."""
    from newsvar.evaluation import inference
    from newsvar.evaluation import metrics as metric_module
    from newsvar.features import text_index
    from newsvar.volatility import proxies, text_ridge

    bootstrap_defaults = metric_module.block_bootstrap_mean.__kwdefaults__ or {}
    share_transform = f"log1p({text_ridge.SHARE_SCALE:g} * share), standardized on training rows"
    return {
        "contracts": {name: list(BASE_FEATURES[name]) for name in CONTRACTS},
        "information_lag_sessions": dict(LAG),
        "har_windows": [1, 5, 22],
        "panel_offset_rows": 24,
        "refit": "first row of each calendar month, retried until enough rows",
        "variance_floor": proxies.VARIANCE_FLOOR,
        "garman_klass_weight": proxies.GK_WEIGHT,
        "primary_model": PRIMARY_MODEL,
        "news_term": PRIMARY_NEWS,
        "secondary_news_terms": [name for name in NEWS_VARIANTS if name != PRIMARY_NEWS],
        "text_model": {
            "name": TEXT_MODEL,
            "vocabulary_end": TEXT_VOCABULARY_END.isoformat(),
            "max_features": TEXT_MAX_FEATURES,
            "min_documents": TEXT_MIN_DOCUMENTS,
            "token_pattern": text_index.TOKEN_PATTERN,
            "ngram_range": list(text_index.NGRAM_RANGE),
            "stop_words": text_index.STOP_WORDS,
            "binary_term_presence": True,
            "transform": share_transform,
            "ridge_penalties": list(text_ridge.ALPHAS),
            "folds": text_ridge.FOLDS,
            "stacking": "out-of-fold slope floored at 0 and capped; zero unless it beats "
            "the zero predictor out of fold",
            "stacking_cap": text_ridge.STACKING_CAP,
        },
        "availability_buffer_minutes": 15,
        "open_buffer_minutes": OPEN_BUFFER.total_seconds() / 60.0,
        "tails": list(TAILS),
        "min_training_rows": MIN_TRAINING_ROWS,
        "min_tail_history": MIN_TAIL_HISTORY,
        "min_scored_headlines": MIN_SCORED_HEADLINES,
        "min_scoring_coverage": MIN_SCORING_COVERAGE,
        "min_pairs": MIN_PAIRS,
        "bootstrap": {
            "blocks": list(BOOTSTRAP_BLOCKS),
            "replications": bootstrap_defaults["replications"],
            "seed": bootstrap_defaults["seed"],
        },
        "newey_west_lags": f"floor(4 * (n / 100) ** (2 / 9)); n=700 gives "
        f"{inference.default_lags(700)}",
        "test_level": 0.05,
    }


def preregistration(
    inputs: VolatilityInputs,
    development_path: Path,
    *,
    development_end: date,
    holdout_start: date,
    holdout_end: date,
    fresh_start: date,
    source: Mapping[str, str],
    holdout_rows: Mapping[str, Any],
    power_note: str = "",
) -> dict[str, Any]:
    """Build the frozen confirmatory protocol. The caller must run this before any holdout
    outcome is evaluated; ``evaluate`` later checks every recorded value against the code.

    ``source`` identifies the code by content (Git tree of ``src`` and file hashes), so
    committing this record afterwards does not invalidate it.
    """
    if not development_end < holdout_start <= fresh_start <= holdout_end:
        raise VolatilityStudyError("Development, holdout and fresh-slice dates are out of order.")
    development = json.loads(development_path.read_text(encoding="utf-8"))
    if date.fromisoformat(development["range"][1]) > development_end:
        raise VolatilityStudyError("The development record extends past the development end.")
    body = {
        "schema_version": "volatility_preregistration_v2",
        "inputs": inputs.identity(),
        "development_record_sha256": file_sha256(development_path),
        "development_end": development_end.isoformat(),
        "holdout": [holdout_start.isoformat(), holdout_end.isoformat()],
        "fresh_slice_start": fresh_start.isoformat(),
        "holdout_eligible_rows": dict(holdout_rows),
        "source": dict(source),
        "protocol": protocol_constants(),
        "model": "Baseline: OLS on log range-based variance with daily, weekly and monthly "
        "lags and log VIX (plus the overnight gap at the open); expanding window, refit "
        "monthly, at least 250 training rows. Challenger: the same plus a ridge regression "
        "of the baseline residual on headline term shares, penalty by blocked 5-fold "
        "cross-validation, scaled by an out-of-fold stacking weight. VaR and ES by filtered "
        "historical simulation using out-of-sample standardized returns once 250 are known.",
        "primary_hypothesis": f"H1: {PRIMARY_MODEL} has lower QLIKE than HAR on the holdout, "
        "tested once on the session-wise average of the two contracts' QLIKE improvements",
        "primary_test": "one-sided Diebold-Mariano test with Newey-West variance, 5% level. "
        "Nested models on an expanding window make this test conservative.",
        "key_secondary": "H2: the same model lowers the 5% FZ0 joint VaR/ES loss, same pooled "
        "one-sided test",
        "supporting": "per-contract tests with Holm-adjusted p-values; paired moving-block "
        "bootstrap (2,000 replications, blocks 20/10/5, seed 1729); 5% and 1% pinball and FZ0 "
        "losses; Giacomini-White conditional test with log VIX and absolute sentiment surprise "
        "as instruments; coverage and dynamic-quantile tests; FinBERT sentiment terms as "
        "exploratory comparisons",
        "verdict_rule": "confirmed: H1 p < 0.05, the QLIKE improvement is positive in both "
        "contracts, and the pooled 5% FZ0 improvement is not negative. strong: confirmed and H2 "
        "p < 0.05. Otherwise not confirmed.",
        "power_note": power_note,
        "disclosures": [
            "The 2023-12-14 to 2025-12-31 part of the holdout was the test period of the first "
            "study. That study's null result prompted this design, so the design is conditioned "
            "on an outcome from that period. No volatility forecast, range-based variance or "
            "text model was evaluated there before this record. The slice from "
            "fresh_slice_start onward had never been evaluated in any form and is reported "
            "separately.",
            "The primary news model was chosen on development data after generic FinBERT "
            "sentiment terms showed smaller gains. Development choices that were made or "
            "checked there: text model versus sentiment terms, level versus abnormal term "
            "shares, two penalty grids (the alternative grid lowered the pre-close gain), and "
            "index versus fund prices for the at-open contract. The vocabulary size, minimum "
            "term count, vocabulary date, transform and stacking cap were set once without "
            "tuning. Development figures are therefore optimistic.",
            "H1 compares the text model with a baseline built from daily data only. In the "
            "pre-close contract the baseline knows prices through session s-2 while headlines "
            "run to 30 minutes before the close of s-1, so part of any gain may come from "
            "headlines that describe same-day market moves. A confirmed H1 shows that news "
            "text improves on a daily-data volatility model; it does not show that news holds "
            "information beyond intraday prices.",
            "The at-open contract uses SPY prices because the S&P 500 index value at 09:30 is "
            "partly stale.",
            "The power figure applies to H1 alone under the development effect size; the "
            "confirmed verdict adds two conditions and has lower power.",
        ],
    }
    return {"preregistration_id": sha256(canonical_json(body)), **body}


def verify_registration(
    inputs: VolatilityInputs, registration: Mapping[str, Any], *, source: Mapping[str, str]
) -> None:
    """Refuse to evaluate unless the record, inputs, constants and source content all match."""
    body = {key: value for key, value in registration.items() if key != "preregistration_id"}
    if sha256(canonical_json(body)) != registration["preregistration_id"]:
        raise VolatilityStudyError("Preregistration content does not match its identifier.")
    if registration["inputs"] != json.loads(canonical_json(inputs.identity())):
        raise VolatilityStudyError("Study inputs differ from the preregistered inputs.")
    if registration["protocol"] != json.loads(canonical_json(protocol_constants())):
        raise VolatilityStudyError("Protocol constants in the code differ from the registration.")
    if dict(registration["source"]) != dict(source):
        raise VolatilityStudyError("Source code or lockfile differs from the registered content.")
    start, end = (date.fromisoformat(value) for value in registration["holdout"])
    fresh = date.fromisoformat(registration["fresh_slice_start"])
    if not date.fromisoformat(registration["development_end"]) < start <= fresh <= end:
        raise VolatilityStudyError("Registered dates are out of order.")


def check_holdout_rows(rows: Sequence[Mapping[str, Any]], registration: Mapping[str, Any]) -> None:
    """Compare outcome-blind eligible row counts on the holdout with the registered counts."""
    counted = panel_summary(
        rows,
        start=date.fromisoformat(registration["holdout"][0]),
        through=date.fromisoformat(registration["holdout"][1]),
    )
    if json.loads(canonical_json(counted)) != registration["holdout_eligible_rows"]:
        raise VolatilityStudyError("Eligible holdout rows differ from the registered counts.")


def holm(p_values: Mapping[str, float]) -> dict[str, float]:
    """Holm step-down adjusted p-values."""
    ordered = sorted(p_values.items(), key=lambda item: item[1])
    adjusted: dict[str, float] = {}
    running = 0.0
    for rank, (name, value) in enumerate(ordered):
        running = max(running, min(1.0, (len(ordered) - rank) * value))
        adjusted[name] = running
    return adjusted


def evaluate(
    inputs: VolatilityInputs,
    registration: Mapping[str, Any],
    *,
    source: Mapping[str, str],
    ledger: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the frozen protocol on the holdout; slices reuse the same forecasts."""
    verify_registration(inputs, registration, source=source)
    rows = build_panel(inputs)
    check_holdout_rows(rows, registration)
    start, end = (date.fromisoformat(value) for value in registration["holdout"])
    fresh = date.fromisoformat(registration["fresh_slice_start"])
    forecasts = all_forecasts(rows, NEWS_VARIANTS, text_shares(inputs, rows))
    holdout = run_range(rows, forecasts, start=start, end=end)
    key = f"{PRIMARY_MODEL[4:]}_vs_har"
    comparisons = {c: holdout["contracts"][c]["comparisons"][key] for c in CONTRACTS}
    pooled = {
        kind: pooled_test(rows, forecasts, PRIMARY_MODEL, kind, start=start, end=end)
        for kind in ("qlike", "fz0", "pinball")
    }
    if any(item["status"] != "estimated" for item in (*comparisons.values(), *pooled.values())):
        raise VolatilityStudyError("The holdout has too few paired forecasts to evaluate.")
    p_values = {
        contract: comparisons[contract]["qlike"]["diebold_mariano"]["p_value_challenger_better"]
        for contract in CONTRACTS
    }
    adjusted = holm(p_values)
    h1 = pooled["qlike"]["diebold_mariano"]["p_value_challenger_better"]
    h2 = pooled["fz0"]["diebold_mariano"]["p_value_challenger_better"]
    confirmed = bool(
        h1 < 0.05
        and all(comparisons[c]["qlike"]["mean_improvement"] > 0 for c in CONTRACTS)
        and pooled["fz0"]["mean_improvement"] >= 0
    )
    decisions: dict[str, Any] = {
        "primary_model": PRIMARY_MODEL,
        "h1_pooled_qlike_one_sided_p": h1,
        "h2_pooled_fz0_5pct_one_sided_p": h2,
        "pooled": pooled,
        "per_contract": {
            contract: {
                "qlike_relative_gain": comparisons[contract]["qlike"]["relative_gain"],
                "one_sided_p": p_values[contract],
                "holm_adjusted_p": adjusted[contract],
                "pinball_5pct_relative_gain": comparisons[contract]["pinball_0.05"][
                    "relative_gain"
                ],
                "fz0_5pct_mean_improvement": comparisons[contract]["fz0_0.05"]["mean_improvement"],
            }
            for contract in CONTRACTS
        },
        "verdict": "strong"
        if confirmed and h2 < 0.05
        else "confirmed"
        if confirmed
        else "not_confirmed",
    }
    if ledger is not None:
        by_session = {row["session"]: row for row in rows}
        for contract in CONTRACTS:
            for name, model in forecasts[contract].items():
                for session, record in model.items():
                    if start <= session <= end:
                        ledger.append(
                            {
                                "contract": contract,
                                "model": name,
                                "session": session,
                                "ret": by_session[session][f"ret_{contract}"],
                                "var": by_session[session][f"var_{contract}"],
                                "text_alpha": None,
                                "text_stacking": None,
                                **record,
                            }
                        )
    return {
        "schema_version": "volatility_evaluation_v1",
        "preregistration_id": registration["preregistration_id"],
        "decisions": decisions,
        "holdout": holdout,
        "fresh_slice": run_range(rows, forecasts, start=fresh, end=end),
        "previously_used_slice": run_range(
            rows, forecasts, start=start, end=fresh - timedelta(days=1)
        ),
    }
