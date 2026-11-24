"""Tables, figures and LaTeX macros for the volatility study, rebuilt from saved records.

Nothing is fitted here except the descriptive full-sample term weights, which
are labelled as such. All losses are recomputed from the private forecast ledger
and must agree with the evaluation record.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq

from newsvar.evaluation.inference import diebold_mariano, fz0, qlike
from newsvar.evaluation.metrics import block_bootstrap_mean, pinball_loss

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
MUTED = "#52514e"
GRID = "#e4e3df"
BLUE = "#2a78d6"
ORANGE = "#eb6834"
CONTRACT_LABEL = {"pre_close": "Pre-close", "at_open": "At-open"}
MODEL_LABEL = {
    "historical_simulation": "Historical simulation (250 days)",
    "har": "HAR baseline",
    "har+text_ridge": "HAR + text model",
    "har+negative_share_surprise": "HAR + FinBERT negative-share surprise",
    "har+negative_mean_surprise": "HAR + FinBERT mean-negative surprise",
    "har+negative_share_level": "HAR + FinBERT negative-share level",
    "har+count_surprise": "HAR + news-count surprise",
}
PRIMARY = "har+text_ridge"


def load_ledger(path: Path) -> dict[str, dict[str, dict[date, dict[str, Any]]]]:
    """Ledger rows keyed by contract, model and session."""
    output: dict[str, dict[str, dict[date, dict[str, Any]]]] = {}
    for row in pq.read_table(path).to_pylist():
        output.setdefault(row["contract"], {}).setdefault(row["model"], {})[row["session"]] = row
    return output


def loss(row: Mapping[str, Any], kind: str) -> float:
    if kind == "qlike":
        return qlike(row["var"], row["variance"])
    if kind == "pinball":
        return pinball_loss(row["ret"], row["q_0.05"], 0.05)
    return fz0(row["ret"], row["q_0.05"], row["es_0.05"], 0.05)


def improvement_series(
    ledger: Mapping[str, Mapping[str, Mapping[date, Mapping[str, Any]]]],
    contract: str,
    kind: str,
    challenger: str = PRIMARY,
) -> dict[date, float]:
    """Baseline loss minus challenger loss per common session."""
    base, other = ledger[contract]["har"], ledger[contract][challenger]
    return {s: loss(base[s], kind) - loss(other[s], kind) for s in sorted(base) if s in other}


def pooled_series(
    ledger: Mapping[str, Mapping[str, Mapping[date, Mapping[str, Any]]]], kind: str
) -> dict[date, float]:
    first, second = (improvement_series(ledger, c, kind) for c in ("pre_close", "at_open"))
    return {s: 0.5 * (first[s] + second[s]) for s in sorted(first) if s in second}


def slice_test(series: Mapping[date, float], start: date, end: date) -> dict[str, Any]:
    """One-sided test and bootstrap interval of a mean improvement inside a date range."""
    values = [value for session, value in series.items() if start <= session <= end]
    test = diebold_mariano(values)
    interval = block_bootstrap_mean(values, block_length=20)["interval_95"]
    return {
        "n": len(values),
        "mean": float(np.mean(values)),
        "t": test["statistic"],
        "p": test["p_value_challenger_better"],
        "interval": interval,
    }


def _style(axis: Any) -> None:
    axis.set_facecolor(SURFACE)
    axis.set_axisbelow(True)
    axis.grid(axis="y", color=GRID, linewidth=0.8)
    axis.tick_params(colors=MUTED, length=0)
    for side in ("top", "right", "left"):
        axis.spines[side].set_visible(False)
    axis.spines["bottom"].set_color(GRID)


def figures(
    ledger: Mapping[str, Mapping[str, Mapping[date, Mapping[str, Any]]]],
    evaluation: Mapping[str, Any],
    fresh_start: date,
    figure_dir: Path,
    terms: Mapping[str, Sequence[tuple[str, float]]] | None = None,
) -> dict[str, Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure_dir.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 10, "text.color": INK, "axes.labelcolor": MUTED})
    paths: dict[str, Path] = {}

    # 1. Cumulative QLIKE improvement of the text model.
    figure, axis = plt.subplots(figsize=(10.5, 4.2), facecolor=SURFACE)
    _style(axis)
    for contract, color in (("pre_close", BLUE), ("at_open", ORANGE)):
        series = improvement_series(ledger, contract, "qlike")
        days = list(series)
        total = np.cumsum(list(series.values()))
        axis.plot(days, total, color=color, linewidth=2)
        axis.annotate(
            CONTRACT_LABEL[contract],
            (days[-1], total[-1]),
            xytext=(6, 0),
            textcoords="offset points",
            color=INK,
            va="center",
            fontsize=9,
        )
    axis.axhline(0, color=MUTED, linewidth=0.8)
    axis.axvspan(fresh_start, max(days), color="#e9e8e3", alpha=0.6, linewidth=0)
    axis.text(
        fresh_start,
        axis.get_ylim()[1],
        "  never-evaluated 2026 slice",
        va="top",
        color=MUTED,
        fontsize=9,
    )
    axis.set_ylabel("Cumulative QLIKE improvement over HAR")
    axis.set_title(
        "Holdout: cumulative volatility-forecast gain of the text model", loc="left", fontsize=12
    )
    axis.margins(x=0.08)
    figure.tight_layout()
    paths["cumulative"] = figure_dir / "vol_cumulative_qlike.png"
    figure.savefig(paths["cumulative"], dpi=170)
    plt.close(figure)

    # 2. Relative gains by news term and contract (dot plot with bootstrap intervals).
    names = [
        ("text_ridge", "Text model (primary)"),
        ("count_surprise", "News-count surprise"),
        ("negative_share_level", "FinBERT negative share"),
        ("negative_share_surprise", "FinBERT negative-share surprise"),
        ("negative_mean_surprise", "FinBERT mean-negative surprise"),
    ]
    figure, axes = plt.subplots(1, 2, figsize=(10.5, 3.6), facecolor=SURFACE, sharey=True)
    for axis, contract in zip(axes, ("pre_close", "at_open"), strict=True):
        _style(axis)
        axis.grid(axis="x", color=GRID, linewidth=0.8)
        axis.grid(axis="y", visible=False)
        comparisons = evaluation["holdout"]["contracts"][contract]["comparisons"]
        for position, (key, _) in enumerate(names):
            item = comparisons[f"{key}_vs_har"]["qlike"]
            base = item["baseline_mean"]
            low, high = (
                100 * value / base for value in item["bootstrap"]["block_20"]["interval_95"]
            )
            gain = 100 * item["relative_gain"]
            color = BLUE if key == "text_ridge" else MUTED
            axis.plot([low, high], [position, position], color=color, linewidth=2)
            axis.scatter([gain], [position], s=46, color=color, zorder=3)
        axis.axvline(0, color=INK, linewidth=0.8)
        axis.set_yticks(range(len(names)), [label for _, label in names])
        axis.invert_yaxis()
        axis.set_xlabel("QLIKE improvement over HAR (%), 95% interval")
        axis.set_title(CONTRACT_LABEL[contract], loc="left", fontsize=11)
    figure.suptitle(
        "Holdout: which news terms improve the volatility forecast", x=0.01, ha="left", fontsize=12
    )
    figure.tight_layout()
    paths["gains"] = figure_dir / "vol_gains_by_term.png"
    figure.savefig(paths["gains"], dpi=170)
    plt.close(figure)

    # 3. VaR forecasts and realized returns, pre-close contract.
    figure, axis = plt.subplots(figsize=(10.5, 4.4), facecolor=SURFACE)
    _style(axis)
    model = ledger["pre_close"][PRIMARY]
    days = sorted(model)
    returns = np.asarray([model[s]["ret"] for s in days]) * 100
    quantile = np.asarray([model[s]["q_0.05"] for s in days]) * 100
    shortfall = np.asarray([model[s]["es_0.05"] for s in days]) * 100
    gaps = [i for i in range(1, len(days)) if (days[i] - days[i - 1]).days > 7]
    line_q, line_es = quantile.copy(), shortfall.copy()
    for index in gaps:
        line_q[index] = np.nan
        line_es[index] = np.nan
    axis.vlines(days, 0, returns, color="#b9b8b2", linewidth=0.8, label="Realized return")
    axis.plot(days, line_q, color=BLUE, linewidth=1.6, label="95% VaR")
    axis.plot(days, line_es, color=ORANGE, linewidth=1.3, label="Expected shortfall")
    hits = returns < quantile
    axis.scatter(
        np.asarray(days)[hits],
        returns[hits],
        s=30,
        facecolor=SURFACE,
        edgecolor=INK,
        linewidth=1.2,
        zorder=3,
        label=f"Breach ({int(hits.sum())})",
    )
    axis.set_ylabel("Close-to-close return (%)")
    axis.set_title(
        "Holdout: pre-close 95% VaR and expected shortfall from the text model",
        loc="left",
        fontsize=12,
        pad=26,
    )
    axis.legend(frameon=False, ncols=4, loc="lower left", bbox_to_anchor=(0.0, 1.0), fontsize=9)
    figure.tight_layout()
    paths["var"] = figure_dir / "vol_var_forecasts.png"
    figure.savefig(paths["var"], dpi=170)
    plt.close(figure)

    # 4. Largest term weights (descriptive, full-sample fit).
    if terms:
        figure, axes = plt.subplots(1, 2, figsize=(10.5, 4.8), facecolor=SURFACE)
        for axis, contract in zip(axes, ("pre_close", "at_open"), strict=True):
            _style(axis)
            axis.grid(axis="x", color=GRID, linewidth=0.8)
            axis.grid(axis="y", visible=False)
            items = list(terms[contract])
            labels = [name for name, _ in items]
            weights = [weight for _, weight in items]
            axis.barh(
                range(len(items)),
                weights,
                height=0.62,
                color=[ORANGE if w > 0 else BLUE for w in weights],
            )
            axis.axvline(0, color=INK, linewidth=0.8)
            axis.set_yticks(range(len(items)), labels, fontsize=9)
            axis.invert_yaxis()
            axis.set_xlabel("Weight on log variance (per standard deviation of the term)")
            axis.set_title(CONTRACT_LABEL[contract], loc="left", fontsize=11)
        figure.suptitle(
            "Terms that raise (orange) or lower (blue) forecast volatility; "
            "descriptive fit on all data",
            x=0.01,
            ha="left",
            fontsize=12,
        )
        figure.tight_layout()
        paths["terms"] = figure_dir / "vol_term_weights.png"
        figure.savefig(paths["terms"], dpi=170)
        plt.close(figure)
    return paths


def term_weights(
    rows: Sequence[Mapping[str, Any]], text: Mapping[str, np.ndarray], *, top: int = 10
) -> dict[str, list[tuple[str, float]]]:
    """Largest positive and negative stacked ridge weights from one fit on every eligible row."""
    from newsvar.study import volatility as study
    from newsvar.volatility.har import fit_log_variance
    from newsvar.volatility.text_ridge import fit_text_residual

    output: dict[str, list[tuple[str, float]]] = {}
    vocabulary = [str(term) for term in text["terms"]]
    for contract in study.CONTRACTS:
        names = [f"{name}_{contract}" for name in study.BASE_FEATURES[contract]]
        usable = [i for i, row in enumerate(rows) if study.ineligibility(row, contract) is None]
        design = np.asarray([[float(rows[i][name]) for name in names] for i in usable])
        target = np.asarray([rows[i][f"var_{contract}"] for i in usable])
        fitted = fit_log_variance(names, design, target)
        residual = np.log(target) - np.asarray([fitted.log_forecast(row) for row in design])
        text_fit = fit_text_residual(text[contract][usable], residual)
        weights = text_fit.stacking * text_fit.weights
        order = np.argsort(weights)
        chosen = [*order[::-1][:top], *order[:top][::-1]]
        output[contract] = [(vocabulary[i], float(weights[i])) for i in chosen]
    return output


def _fmt(value: float | None, digits: int = 2, percent: bool = False) -> str:
    if value is None:
        return "n/a"
    return f"{100 * value:+.{digits}f}%" if percent else f"{value:.{digits}f}"


def summary(
    ledger: Mapping[str, Mapping[str, Mapping[date, Mapping[str, Any]]]],
    evaluation: Mapping[str, Any],
    registration: Mapping[str, Any],
) -> dict[str, Any]:
    """Headline numbers, including pooled tests on the fresh and previously used slices."""
    start, end = (date.fromisoformat(value) for value in registration["holdout"])
    fresh = date.fromisoformat(registration["fresh_slice_start"])
    slices = {
        "holdout": (start, end),
        "fresh": (fresh, end),
        "earlier": (start, date.fromordinal(fresh.toordinal() - 1)),
    }
    pooled = {
        name: {
            kind: slice_test(pooled_series(ledger, kind), *bounds)
            for kind in ("qlike", "pinball", "fz0")
        }
        for name, bounds in slices.items()
    }
    recorded = evaluation["decisions"]["pooled"]["qlike"]["mean_improvement"]
    if abs(pooled["holdout"]["qlike"]["mean"] - recorded) > 1e-9:
        raise ValueError("Ledger losses do not reproduce the evaluation record.")
    return {
        "pooled": pooled,
        "slices": {k: [a.isoformat(), b.isoformat()] for k, (a, b) in slices.items()},
    }


def markdown(
    evaluation: Mapping[str, Any], registration: Mapping[str, Any], extra: Mapping[str, Any]
) -> str:
    decisions = evaluation["decisions"]
    lines = [
        "# Volatility study: generated result tables",
        "",
        "Generated by `newsvar vol report` from the registration, the evaluation record and the "
        "private forecast ledger. A positive improvement favors the text model.",
        "",
        f"- Preregistration: `{registration['preregistration_id']}`",
        f"- Holdout: {registration['holdout'][0]} to {registration['holdout'][1]}; "
        f"never-evaluated slice from {registration['fresh_slice_start']}",
        f"- Verdict under the registered rule: **{decisions['verdict']}**",
        "",
        "## Pooled tests of the text model against the HAR baseline",
        "",
        "| Period | Loss | Sessions | Mean improvement | t | One-sided p | 95% interval |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    label = {"holdout": "Whole holdout", "earlier": "2023-12-14 to 2025", "fresh": "2026 slice"}
    for name in ("holdout", "earlier", "fresh"):
        for kind in ("qlike", "pinball", "fz0"):
            item = extra["pooled"][name][kind]
            scale = 1e4 if kind == "pinball" else 1.0
            unit = " bp" if kind == "pinball" else ""
            lines.append(
                f"| {label[name]} | {kind} | {item['n']} | {item['mean'] * scale:.4f}{unit} "
                f"| {item['t']:.2f} | {item['p']:.4f} "
                f"| {item['interval'][0] * scale:.4f} to {item['interval'][1] * scale:.4f} |"
            )
    for part, title in (
        ("holdout", "Whole holdout"),
        ("previously_used_slice", "2023-12-14 to 2025 (test period of the first study)"),
        ("fresh_slice", "2026 slice (never evaluated before)"),
    ):
        for contract in ("pre_close", "at_open"):
            section = evaluation[part]["contracts"][contract]
            lines += [
                "",
                f"## {title}: {CONTRACT_LABEL[contract].lower()} contract "
                f"({section['common_forecasts']} common forecasts)",
                "",
                "| Model | QLIKE | 5% breaches (expected) | 5% pinball (bp) | 5% FZ0 "
                "| Kupiec p | 1% breaches (expected) |",
                "|---|---:|---:|---:|---:|---:|---:|",
            ]
            for model, item in section["models"].items():
                five, one = item["tail_0.05"], item["tail_0.01"]
                lines.append(
                    f"| {MODEL_LABEL.get(model, model)} | {_fmt(item.get('mean_qlike'), 4)} "
                    f"| {five['breaches']} ({five['expected']:.1f}) "
                    f"| {five['mean_pinball'] * 1e4:.3f} | {five['mean_fz0']:.4f} "
                    f"| {five['kupiec']['p_value']:.2f} "
                    f"| {one['breaches']} ({one['expected']:.1f}) |"
                )
            lines += [
                "",
                "| Comparison with HAR | QLIKE gain | t | One-sided p | 5% pinball gain "
                "| 5% FZ0 improvement | 1% pinball gain |",
                "|---|---:|---:|---:|---:|---:|---:|",
            ]
            for name, item in section["comparisons"].items():
                if "qlike" not in item:
                    continue
                test = item["qlike"]["diebold_mariano"]
                lines.append(
                    f"| {MODEL_LABEL.get('har+' + name[:-7], name)} "
                    f"| {_fmt(item['qlike']['relative_gain'], 2, True)} | {test['statistic']:.2f} "
                    f"| {test['p_value_challenger_better']:.3f} "
                    f"| {_fmt(item['pinball_0.05']['relative_gain'], 2, True)} "
                    f"| {item['fz0_0.05']['mean_improvement']:+.4f} "
                    f"| {_fmt(item['pinball_0.01']['relative_gain'], 2, True)} |"
                )
            versus = section["comparisons"]["har_vs_historical_simulation"]
            lines += [
                "",
                "HAR baseline against historical simulation: 5% pinball gain "
                f"{_fmt(versus['pinball_0.05']['relative_gain'], 2, True)} "
                f"(t = {versus['pinball_0.05']['diebold_mariano']['statistic']:.2f}).",
            ]
    return "\n".join(lines) + "\n"


def latex_macros(
    evaluation: Mapping[str, Any], registration: Mapping[str, Any], extra: Mapping[str, Any]
) -> str:
    """Key numbers as LaTeX macros so the report text cannot drift from the records."""
    decisions = evaluation["decisions"]
    macros: dict[str, str] = {
        "Verdict": decisions["verdict"].replace("_", " "),
        "HoldoutStart": registration["holdout"][0],
        "HoldoutEnd": registration["holdout"][1],
        "FreshStart": registration["fresh_slice_start"],
        "RegistrationId": registration["preregistration_id"][:12],
        "HOneP": f"{decisions['h1_pooled_qlike_one_sided_p']:.3f}",
        "HTwoP": f"{decisions['h2_pooled_fz0_5pct_one_sided_p']:.3f}",
    }
    for name, tag in (("holdout", "Hold"), ("fresh", "Fresh"), ("earlier", "Earlier")):
        for kind, label in (("qlike", "Qlike"), ("pinball", "Pin"), ("fz0", "Fz")):
            item = extra["pooled"][name][kind]
            macros[f"Pooled{tag}{label}T"] = f"{item['t']:.2f}"
            macros[f"Pooled{tag}{label}P"] = f"{item['p']:.3f}"
            macros[f"Pooled{tag}{label}N"] = str(item["n"])
    for part, tag in (
        ("holdout", "Hold"),
        ("fresh_slice", "Fresh"),
        ("previously_used_slice", "Earlier"),
    ):
        for contract, label in (("pre_close", "Pre"), ("at_open", "Open")):
            section = evaluation[part]["contracts"][contract]
            item = section["comparisons"]["text_ridge_vs_har"]
            macros[f"{tag}{label}N"] = str(section["common_forecasts"])
            macros[f"{tag}{label}QlikeGain"] = f"{100 * item['qlike']['relative_gain']:+.1f}\\%"
            macros[f"{tag}{label}QlikeT"] = f"{item['qlike']['diebold_mariano']['statistic']:.2f}"
            macros[f"{tag}{label}QlikeP"] = (
                f"{item['qlike']['diebold_mariano']['p_value_challenger_better']:.3f}"
            )
            macros[f"{tag}{label}PinGain"] = (
                f"{100 * item['pinball_0.05']['relative_gain']:+.1f}\\%"
            )
            macros[f"{tag}{label}PinT"] = (
                f"{item['pinball_0.05']['diebold_mariano']['statistic']:.2f}"
            )
            macros[f"{tag}{label}FzGain"] = f"{item['fz0_0.05']['mean_improvement']:+.4f}"
            macros[f"{tag}{label}GwP"] = f"{item['qlike']['giacomini_white']['p_value']:.3f}"
            for model, short in (
                ("har", "Har"),
                ("har+text_ridge", "Text"),
                ("historical_simulation", "Hs"),
            ):
                tail = section["models"][model]["tail_0.05"]
                macros[f"{tag}{label}{short}Breaches"] = str(tail["breaches"])
                macros[f"{tag}{label}{short}Pin"] = f"{tail['mean_pinball'] * 1e4:.2f}"
                macros[f"{tag}{label}{short}Fz"] = f"{tail['mean_fz0']:.3f}"
                macros[f"{tag}{label}{short}Kupiec"] = f"{tail['kupiec']['p_value']:.2f}"
                one = section["models"][model]["tail_0.01"]
                macros[f"{tag}{label}{short}BreachesOne"] = str(one["breaches"])
                if "mean_qlike" in section["models"][model]:
                    macros[f"{tag}{label}{short}Qlike"] = (
                        f"{section['models'][model]['mean_qlike']:.4f}"
                    )
            macros[f"{tag}{label}Expected"] = (
                f"{section['models']['har']['tail_0.05']['expected']:.1f}"
            )
            macros[f"{tag}{label}ExpectedOne"] = (
                f"{section['models']['har']['tail_0.01']['expected']:.1f}"
            )
            versus = section["comparisons"]["har_vs_historical_simulation"]
            macros[f"{tag}{label}HarVsHsPin"] = (
                f"{100 * versus['pinball_0.05']['relative_gain']:+.1f}\\%"
            )
            for key, short in (
                ("count_surprise", "Count"),
                ("negative_share_surprise", "ShareSurprise"),
                ("negative_share_level", "ShareLevel"),
                ("negative_mean_surprise", "MeanSurprise"),
            ):
                other = section["comparisons"][f"{key}_vs_har"]
                macros[f"{tag}{label}{short}Gain"] = (
                    f"{100 * other['qlike']['relative_gain']:+.1f}\\%"
                )
                macros[f"{tag}{label}{short}T"] = (
                    f"{other['qlike']['diebold_mariano']['statistic']:.2f}"
                )
                macros[f"{tag}{label}{short}Pin"] = (
                    f"{100 * other['pinball_0.05']['relative_gain']:+.1f}\\%"
                )
    for contract, label in (("pre_close", "Pre"), ("at_open", "Open")):
        item = decisions["per_contract"][contract]
        macros[f"Holm{label}"] = f"{item['holm_adjusted_p']:.3f}"
    lines = ["% Generated by `newsvar vol report`; do not edit."]
    lines += [f"\\newcommand{{\\{name}}}{{{value}}}" for name, value in sorted(macros.items())]
    return "\n".join(lines) + "\n"
