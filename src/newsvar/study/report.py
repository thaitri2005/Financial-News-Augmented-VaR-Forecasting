"""Result tables and figures rebuilt from saved study records; nothing is fitted here."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
MUTED = "#52514e"
GRID = "#e4e3df"
BLUE = "#2a78d6"
ORANGE = "#eb6834"
NAMES = {
    "historical_simulation_linear_w250": "B0 historical simulation (250)",
    "gaussian_ewma_d0.94_i63": "B1 Gaussian EWMA",
    "garch_t": "B2 GARCH-t",
    "filtered_historical": "B3 filtered historical simulation",
    "Q0": "Q0 market",
    "Q1": "Q1 market + news counts",
    "Q2": "Q2 market + counts + sentiment",
    "T0": "T0 tree, market",
    "T1": "T1 tree, + counts",
    "T2": "T2 tree, + sentiment",
}


def _bp(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value * 10_000:.{digits}f}"


def _pct(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value * 100:.{digits}f}%"


def _summary_table(summaries: Mapping[str, Any], tail: str) -> list[str]:
    lines = [
        "| Model | Forecasts | Breaches (expected) | Breach rate | Mean pinball (bp) "
        "| Kupiec p | Independence p | Longest run |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for model, item in summaries[tail].items():
        if not item.get("forecasts"):
            continue
        christoffersen = item["christoffersen"]
        independence = (
            f"{christoffersen['independence_p_value']:.3f}"
            if christoffersen["status"] == "estimated"
            else "not estimable"
        )
        lines.append(
            f"| {NAMES.get(model, model)} | {item['forecasts']} | {item['breaches']} "
            f"({item['expected_breaches']:.1f}) | {_pct(item['breach_rate'])} "
            f"| {_bp(item['mean_pinball'])} | {item['kupiec']['p_value']:.3f} | {independence} "
            f"| {item['max_breach_run']} |"
        )
    return lines


def _comparison_table(comparisons: Mapping[str, Any], tail: str) -> list[str]:
    lines = [
        "| Comparison (challenger vs baseline) | Pairs | Baseline (bp) | Challenger (bp) "
        "| Improvement (bp) | Relative gain | 95% interval, block 20 (bp) |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for name, item in comparisons[tail].items():
        if not item.get("common_forecasts"):
            continue
        low, high = item["bootstrap"]["block_20"]["interval_95"]
        lines.append(
            f"| {name.replace('_', ' ')} | {item['common_forecasts']} "
            f"| {_bp(item['baseline_mean_pinball'])} | {_bp(item['challenger_mean_pinball'])} "
            f"| {_bp(item['mean_improvement'], 4)} | {_pct(item['relative_gain'])} "
            f"| [{_bp(low, 4)}, {_bp(high, 4)}] |"
        )
    return lines


def _sensitivity_table(sensitivities: Mapping[str, Any]) -> list[str]:
    lines = [
        "| Sensitivity (rebuilt and refitted) | Eligible forecasts | Q2 vs Q1 relative gain "
        "| 95% interval, block 20 (bp) | Q1 vs Q0 relative gain |",
        "|---|---:|---:|---|---:|",
    ]
    for name, item in sensitivities.items():
        primary, counts = item["Q2_vs_Q1"], item["Q1_vs_Q0"]
        low, high = primary["bootstrap"]["block_20"]["interval_95"]
        lines.append(
            f"| {name.replace('_', ' ')} | {item['eligible_forecasts']} "
            f"| {_pct(primary['relative_gain'])} | [{_bp(low, 4)}, {_bp(high, 4)}] "
            f"| {_pct(counts['relative_gain'])} |"
        )
    return lines


def figures(ledger: Path, figure_dir: Path) -> dict[str, Path]:
    """Draw the forecast/breach series and the cumulative paired score difference."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    figure_dir.mkdir(parents=True, exist_ok=True)
    table = pq.read_table(ledger).to_pylist()
    series: dict[str, dict[Any, tuple[float, float]]] = {}
    for row in table:
        if abs(row["tail"] - 0.05) < 1e-12:
            series.setdefault(row["model_id"], {})[row["target_end_session"]] = (
                row["q_return"],
                row["return_simple"],
            )
    common = sorted(set(series["Q1"]).intersection(series["Q2"]))
    returns = np.asarray([series["Q2"][day][1] for day in common]) * 100
    q1 = np.asarray([series["Q1"][day][0] for day in common]) * 100
    q2 = np.asarray([series["Q2"][day][0] for day in common]) * 100
    # Break the forecast lines where sessions are missing, so a feed gap is not drawn as data.
    gaps = [i for i in range(1, len(common)) if (common[i] - common[i - 1]).days > 7]
    line_days = np.asarray(common, dtype="datetime64[D]").astype(object)
    q1_line, q2_line = q1.astype(float).copy(), q2.astype(float).copy()
    for index in gaps:
        q1_line[index] = np.nan
        q2_line[index] = np.nan
    plt.rcParams.update({"font.size": 10, "axes.edgecolor": GRID, "text.color": INK})

    def style(axis: Any) -> None:
        axis.set_facecolor(SURFACE)
        axis.grid(axis="y", color=GRID, linewidth=0.8)
        axis.tick_params(colors=MUTED, length=0)
        for side in ("top", "right", "left"):
            axis.spines[side].set_visible(False)

    figure, axis = plt.subplots(figsize=(11, 4.6), facecolor=SURFACE)
    style(axis)
    axis.vlines(common, 0, returns, color="#b9b8b2", linewidth=0.8, label="Realized return")
    axis.plot(line_days, q1_line, color=BLUE, linewidth=1.6, label="Q1: market + news counts")
    axis.plot(line_days, q2_line, color=ORANGE, linewidth=1.6, label="Q2: + sentiment")
    hits = returns < q2
    axis.scatter(
        np.asarray(common)[hits],
        returns[hits],
        s=34,
        facecolor=SURFACE,
        edgecolor=INK,
        linewidth=1.3,
        zorder=3,
        label=f"Breach of Q2 ({int(hits.sum())})",
    )
    axis.set_ylabel("Next-session return (%)", color=MUTED)
    axis.set_title(
        "Locked test: 5% return quantile forecasts and realized S&P 500 returns",
        loc="left",
        fontsize=12,
        pad=28,
    )
    axis.legend(frameon=False, ncols=4, loc="lower left", bbox_to_anchor=(0.0, 1.0), fontsize=9)
    figure.tight_layout()
    forecast_path = figure_dir / "final_quantiles_and_breaches.png"
    figure.savefig(forecast_path, dpi=160)
    plt.close(figure)

    def loss(observed: Any, quantile: Any) -> Any:
        return (0.05 - (observed < quantile)) * (observed - quantile)

    difference = (loss(returns, q1) - loss(returns, q2)) * 100  # percent -> basis points
    figure, axis = plt.subplots(figsize=(11, 3.8), facecolor=SURFACE)
    style(axis)
    axis.axhline(0, color=MUTED, linewidth=0.8)
    axis.plot(common, np.cumsum(difference), color=BLUE, linewidth=2)
    axis.set_ylabel("Cumulative pinball gain (bp)", color=MUTED)
    axis.set_title(
        "Locked test: cumulative Q1 minus Q2 pinball loss (above zero favors sentiment)",
        loc="left",
        fontsize=12,
    )
    figure.tight_layout()
    cumulative_path = figure_dir / "final_cumulative_q2_vs_q1.png"
    figure.savefig(cumulative_path, dpi=160)
    plt.close(figure)
    return {"forecasts": forecast_path, "cumulative": cumulative_path}


def write_report(
    *,
    admission: Mapping[str, Any],
    development: Mapping[str, Any],
    final: Mapping[str, Any],
    ledger: Path,
    output: Path,
    figure_dir: Path,
) -> None:
    paths = figures(ledger, figure_dir)
    relative = {name: Path("..") / path.relative_to("docs") for name, path in paths.items()}
    split = admission["split"]
    decision = final["primary_decision"]
    low, high = decision["interval_95_block_20"]
    lines = [
        "# Generated result tables",
        "",
        "Generated by `newsvar study report` from the admission, development and final records. "
        "Scores are mean pinball losses in basis points of return (decimal loss x 10,000). "
        "A positive improvement favors the challenger.",
        "",
        f"- Preregistration: `{final['preregistration_id']}`",
        f"- Design: `{split['design']}`; usable rows {split['usable_rows']} "
        f"(training {split['training_rows']}, development {split.get('development_rows', 'n/a')}, "
        f"test {split.get('test_rows', 'n/a')})",
        f"- Development target-end range: {split['development'][0]} to {split['development'][1]}",
        f"- Test target-end range: {split['test'][0]} to {split['test'][1]}; "
        f"eligible forecasts {final['test_eligible_forecasts']}",
        "",
        "## Primary comparison (Q2 vs Q1, 5% tail, locked test)",
        "",
        f"- Mean improvement: {_bp(decision['mean_improvement'], 4)} bp; "
        f"relative gain {_pct(decision['relative_gain'])}",
        f"- 95% block-bootstrap interval (block 20): [{_bp(low, 4)}, {_bp(high, 4)}] bp",
        f"- Preregistered claim supported: **{'yes' if decision['claim_supported'] else 'no'}**",
        "",
        f"![Quantile forecasts and breaches]({relative['forecasts'].as_posix()})",
        "",
        f"![Cumulative paired difference]({relative['cumulative'].as_posix()})",
        "",
    ]
    for tail in ("0.05", "0.01"):
        label = "5%" if tail == "0.05" else "1% (exploratory; few expected breaches)"
        lines += [f"## Locked test, {label} tail", "", "### Calibration", ""]
        lines += _summary_table(final["model_summaries"], tail)
        lines += ["", "### Paired comparisons", ""]
        lines += _comparison_table(final["comparisons"], tail)
        yearly = final["comparisons"][tail]["Q2_vs_Q1"]
        lines += [
            "",
            "Q2 vs Q1 by target year (bp): "
            + ", ".join(
                f"{year}: {_bp(value, 4)} ({yearly['yearly_pairs'][year]} pairs)"
                for year, value in yearly["yearly_mean_improvement"].items()
            ),
            "",
        ]
    lines += ["## Locked test, 5% tail: sensitivities", ""]
    lines += _sensitivity_table(final["sensitivities_primary_tail"])
    regimes = final["regimes_Q2_vs_Q1_primary_tail"]["regimes"]
    lines += [
        "",
        "Q2 vs Q1 by ex-ante volatility regime (training-period terciles of lagged 21-session "
        "volatility), bp: "
        + ", ".join(
            f"{name}: {_bp(item['mean_improvement'], 4)} ({item['pairs']} pairs)"
            for name, item in regimes.items()
        ),
        "",
        "Quantile crossings (1% above 5%): "
        + ", ".join(
            f"{group}: {item['crossings']}/{item['common_forecasts']}"
            for group, item in final["crossings"].items()
        ),
        "",
        "## Development range (used for selection only)",
        "",
        f"Selected L1 penalties: `{development['selected_linear_penalty']}`. "
        f"Strongest baseline: `{development['strongest_baseline']}`.",
        "",
        "### 5% tail calibration",
        "",
    ]
    lines += _summary_table(development["model_summaries"], "0.05")
    lines += ["", "### 5% tail paired comparisons", ""]
    lines += _comparison_table(development["comparisons"], "0.05")
    lines += ["", "### 5% tail sensitivities", ""]
    lines += _sensitivity_table(development["sensitivities_primary_tail"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
