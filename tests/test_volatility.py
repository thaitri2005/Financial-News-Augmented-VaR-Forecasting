"""Synthetic fixtures for the volatility-first models, losses and tests."""

import math
from datetime import date, timedelta

import numpy as np
import pytest

from newsvar.evaluation import inference
from newsvar.features.intervals import expanding_surprise
from newsvar.study import volatility as study
from newsvar.volatility import har, proxies, tail, text_ridge


def test_range_variance_matches_hand_calculation() -> None:
    value = proxies.garman_klass(100.0, 102.0, 99.0, 101.0)
    expected = 0.5 * math.log(102 / 99) ** 2 - (2 * math.log(2) - 1) * math.log(101 / 100) ** 2
    assert value == pytest.approx(expected)
    assert proxies.garman_klass(100.0, 100.0, 100.0, 100.0) == proxies.VARIANCE_FLOOR
    total = proxies.close_to_close_variance(98.0, 100.0, 102.0, 99.0, 101.0)
    assert total == pytest.approx(value + math.log(100 / 98) ** 2)
    with pytest.raises(ValueError):
        proxies.garman_klass(100.0, 99.0, 101.0, 100.0)


def test_log_variance_fit_recovers_coefficients_and_corrects_the_mean() -> None:
    rng = np.random.default_rng(1)
    features = rng.normal(size=(4000, 2))
    log_variance = -9.0 + 0.6 * features[:, 0] - 0.2 * features[:, 1] + rng.normal(0, 0.5, 4000)
    fit = har.fit_log_variance(("a", "b"), features, np.exp(log_variance))
    assert fit.coefficients == pytest.approx([-9.0, 0.6, -0.2], abs=0.05)
    assert fit.residual_variance == pytest.approx(0.25, abs=0.03)
    assert fit.variance_forecast([0.0, 0.0]) == pytest.approx(math.exp(-9.0 + 0.125), rel=0.05)
    with pytest.raises(har.HarError):
        har.fit_log_variance(("a", "b"), features[:5], np.exp(log_variance[:5]))
    with pytest.raises(har.HarError):
        har.fit_log_variance(("a", "b"), features, -np.exp(log_variance))


def test_standardized_tail_scales_with_volatility_and_orders_es_below_var() -> None:
    rng = np.random.default_rng(2)
    volatility = rng.uniform(0.005, 0.03, 5000)
    fitted = tail.standardized_tail(rng.standard_normal(5000) * volatility, volatility, alpha=0.05)
    assert fitted.quantile == pytest.approx(-1.645, abs=0.08)
    quantile, shortfall = fitted.forecast(0.02)
    assert shortfall < quantile < 0 and quantile == pytest.approx(0.02 * fitted.quantile)
    with pytest.raises(ValueError):
        tail.standardized_tail([0.01] * 50, [0.01] * 50, alpha=0.05)


def test_losses_reward_the_true_forecast() -> None:
    assert inference.qlike(2e-4, 2e-4) == pytest.approx(0.0)
    assert inference.qlike(2e-4, 1e-4) > 0 and inference.qlike(2e-4, 4e-4) > 0
    rng = np.random.default_rng(3)
    returns = rng.standard_normal(20000) * 0.01
    true_q, true_es = -0.01645, -0.02063
    good = np.mean([inference.fz0(r, true_q, true_es, 0.05) for r in returns])
    tight = np.mean([inference.fz0(r, 0.5 * true_q, 0.5 * true_es, 0.05) for r in returns])
    wide = np.mean([inference.fz0(r, 2 * true_q, 2 * true_es, 0.05) for r in returns])
    assert good < tight and good < wide
    with pytest.raises(inference.InferenceError):
        inference.fz0(0.0, -0.01, 0.01, 0.05)


def test_diebold_mariano_and_holm() -> None:
    rng = np.random.default_rng(4)
    noise = rng.standard_normal(600)
    null = inference.diebold_mariano(noise)
    shifted = inference.diebold_mariano(noise + 0.3)
    assert null["p_value_two_sided"] > 0.01
    assert shifted["p_value_challenger_better"] < 0.001 and shifted["statistic"] > 3
    assert inference.diebold_mariano(-noise - 0.3)["p_value_challenger_better"] > 0.99
    adjusted = study.holm({"a": 0.01, "b": 0.04})
    assert adjusted == pytest.approx({"a": 0.02, "b": 0.04})


def test_conditional_test_detects_state_dependence_and_allows_longer_horizons() -> None:
    rng = np.random.default_rng(5)
    state = rng.standard_normal(800)
    flat = inference.giacomini_white(rng.standard_normal(800), state)
    dependent = inference.giacomini_white(0.5 * state + rng.standard_normal(800), state)
    assert flat["degrees_of_freedom"] == 2 and flat["p_value"] > 0.01
    assert dependent["p_value"] < 1e-6
    shocks = rng.standard_normal(801)
    moving_average = shocks[1:] + 0.9 * shocks[:-1]
    one_step = inference.giacomini_white(moving_average, state, horizon=1)
    two_step = inference.giacomini_white(moving_average, state, horizon=2)
    assert two_step["horizon"] == 2 and two_step["statistic"] != one_step["statistic"]


def test_news_surprise_uses_only_rows_known_at_each_refit() -> None:
    rng = np.random.default_rng(6)
    size = 400
    controls = rng.standard_normal((size, 2))
    tone = list(0.5 * controls[:, 0] + rng.standard_normal(size) * 0.1)
    refit = [index % 20 == 0 for index in range(size)]
    known = [index - 2 for index in range(size)]
    first = expanding_surprise(tone, controls, refit, known)
    changed = tone.copy()
    for index in range(300, size):
        changed[index] += 5.0
    second = expanding_surprise(changed, controls, refit, known)
    # Rows refitted before the change see identical surprises; nothing leaks backwards.
    assert first[:300] == second[:300]
    assert first[50] is None and first[200] is not None
    assert abs(np.nanmean([value for value in first[200:300] if value is not None])) < 0.5


def test_text_model_contributes_only_when_it_predicts_out_of_fold() -> None:
    rng = np.random.default_rng(7)
    shares = rng.uniform(0, 0.02, size=(600, 300))
    signal = text_ridge._transform(shares)[:, 0]
    target = 2.0 * (signal - signal.mean()) + rng.standard_normal(600) * 0.3
    informative = text_ridge.fit_text_residual(shares, target)
    assert informative.stacking > 0.5
    assert np.corrcoef(informative.out_of_fold, target)[0, 1] > 0.4
    noise = text_ridge.fit_text_residual(shares, rng.standard_normal(600))
    assert abs(noise.predict(shares[:50])).mean() < 0.1


def _synthetic_rows(seed: int = 8, size: int = 700) -> list[dict[str, object]]:
    rng = np.random.default_rng(seed)
    rows: list[dict[str, object]] = []
    day = date(2020, 1, 1)
    log_variance = -9.0
    for _ in range(size):
        log_variance = -0.9 + 0.9 * log_variance + rng.normal(0, 0.3)
        variance = math.exp(log_variance)
        row: dict[str, object] = {"session": day, "month": (day.year, day.month)}
        for contract in study.CONTRACTS:
            row[f"ret_{contract}"] = float(rng.standard_normal() * math.sqrt(variance))
            row[f"var_{contract}"] = variance * float(rng.chisquare(4) / 4)
            for name in study.BASE_FEATURES[contract]:
                row[f"{name}_{contract}"] = log_variance + float(rng.normal(0, 0.2))
            for name in study.NEWS_VARIANTS:
                row[f"{name}_{contract}"] = float(rng.standard_normal())
            row[f"complete_{contract}"] = True
            row[f"covered_{contract}"] = True
            row[f"scored_{contract}"] = 300
        rows.append(row)
        day += timedelta(days=1)
    return rows


@pytest.mark.parametrize("contract", study.CONTRACTS)
@pytest.mark.parametrize("with_text", [False, True])
def test_forecasts_ignore_outcomes_not_yet_known(contract: str, with_text: bool) -> None:
    rows = _synthetic_rows()
    lag = study.LAG[contract]
    text = np.random.default_rng(9).uniform(0, 0.02, size=(len(rows), 40)) if with_text else None
    refit = next(i for i, row in enumerate(rows) if i > 560 and row["session"].day == 1)
    news = () if with_text else (study.NEWS_VARIANTS[0],)

    def run(changed_index: int | None) -> dict[date, dict[str, float]]:
        changed = [dict(row) for row in rows]
        if changed_index is not None:
            # A large loss moves the lower tail, so a leak into the tail history would show.
            changed[changed_index][f"ret_{contract}"] = -0.5
            changed[changed_index][f"var_{contract}"] = 0.25
        return study.forecast_all(changed, contract, news, text=text)

    clean = run(None)
    for target in (refit, refit + 9):
        session = rows[target]["session"]
        # The newest outcome a forecast may use is `lag` sessions back.
        assert run(target - lag + 1)[session] == clean[session]
        assert run(target)[session] == clean[session]
        assert run(target - lag)[session] != clean[session]
    # With out-of-sample tails active, an outcome first matters exactly `lag` sessions later.
    position = refit + 3
    shocked = run(position)
    sessions = [row["session"] for row in rows]
    assert all(shocked[s] == clean[s] for s in sessions[position : position + lag] if s in clean)
    assert shocked[sessions[position + lag]] != clean[sessions[position + lag]]


def test_text_rows_after_the_target_cannot_change_a_forecast() -> None:
    rows = _synthetic_rows()
    rng = np.random.default_rng(10)
    text = rng.uniform(0, 0.02, size=(len(rows), 40))
    clean = study.forecast_all(rows, "at_open", text=text)
    later = text.copy()
    later[600:] = rng.uniform(0, 0.02, size=(len(rows) - 600, 40))
    changed = study.forecast_all(rows, "at_open", text=later)
    sessions = [row["session"] for row in rows]
    assert all(clean[s] == changed[s] for s in sessions[:600] if s in clean)
    assert any("text_stacking" in record for record in clean.values())


def test_pooled_test_matches_a_hand_calculation() -> None:
    rows = _synthetic_rows(size=620)
    forecasts = study.all_forecasts(rows, (study.NEWS_VARIANTS[0],))
    name = f"har+{study.NEWS_VARIANTS[0]}"
    start, end = rows[300]["session"], rows[-1]["session"]
    pooled = study.pooled_test(rows, forecasts, name, "qlike", start=start, end=end)
    per_contract = [
        study.daily_differences(
            rows, contract, forecasts[contract]["har"], forecasts[contract][name], "qlike"
        )
        for contract in study.CONTRACTS
    ]
    common = [
        s for s in sorted(set(per_contract[0]).intersection(per_contract[1])) if start <= s <= end
    ]
    expected = np.mean([0.5 * (per_contract[0][s] + per_contract[1][s]) for s in common])
    assert pooled["pairs"] == len(common)
    assert pooled["mean_improvement"] == pytest.approx(expected)
    same = study.pooled_test(rows, forecasts, "har", "qlike", start=start, end=end)
    assert same["diebold_mariano"]["statistic"] == 0.0


def test_stacking_is_zero_when_text_cannot_beat_the_zero_predictor() -> None:
    rng = np.random.default_rng(11)
    shares = rng.uniform(0, 0.02, size=(500, 200))
    weights = [
        text_ridge.fit_text_residual(shares, rng.standard_normal(500)).stacking for _ in range(20)
    ]
    assert sum(weight == 0.0 for weight in weights) >= 5
    assert max(weights) <= text_ridge.STACKING_CAP


def test_registration_pins_constants_and_source(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class FakeInputs:
        def identity(self) -> dict[str, object]:
            return {"corpus_id": "c", "scores_sha256": "s"}

    development = tmp_path / "development.json"
    development.write_text('{"range": ["2021-01-04", "2023-12-13"]}', encoding="utf-8")
    source = {"src_tree": "t", "pyproject_sha256": "p", "lock_sha256": "l"}
    arguments = dict(
        development_end=date(2023, 12, 13),
        holdout_start=date(2023, 12, 14),
        holdout_end=date(2026, 11, 20),
        fresh_start=date(2026, 1, 2),
        source=source,
        holdout_rows={"pre_close": {"eligible_rows": 700}},
    )
    record = study.preregistration(FakeInputs(), development, **arguments)  # type: ignore[arg-type]
    study.verify_registration(FakeInputs(), record, source=source)  # type: ignore[arg-type]
    with pytest.raises(study.VolatilityStudyError, match="Source"):
        study.verify_registration(FakeInputs(), record, source={**source, "src_tree": "x"})  # type: ignore[arg-type]
    tampered = {**record, "fresh_slice_start": "2026-02-02"}
    with pytest.raises(study.VolatilityStudyError, match="identifier"):
        study.verify_registration(FakeInputs(), tampered, source=source)  # type: ignore[arg-type]
    monkeypatch.setattr(text_ridge, "ALPHAS", (1.0, 2.0))
    with pytest.raises(study.VolatilityStudyError, match="constants"):
        study.verify_registration(FakeInputs(), record, source=source)  # type: ignore[arg-type]
    monkeypatch.undo()
    with pytest.raises(study.VolatilityStudyError, match="order"):
        study.preregistration(
            FakeInputs(),
            development,
            **{**arguments, "fresh_start": date(2023, 1, 2)},  # type: ignore[arg-type]
        )


def test_range_report_pairs_models_and_flags_small_samples() -> None:
    rows = _synthetic_rows(size=620)
    forecasts = study.all_forecasts(rows, (study.NEWS_VARIANTS[0],))
    start, end = rows[300]["session"], rows[-1]["session"]
    report = study.run_range(rows, forecasts, start=start, end=end)
    section = report["contracts"]["pre_close"]
    counts = {model["forecasts"] for model in section["models"].values()}
    assert counts == {section["common_forecasts"]}
    comparison = section["comparisons"][f"{study.NEWS_VARIANTS[0]}_vs_har"]
    assert comparison["status"] == "estimated"
    # FZ0 means are negative, so no ratio is reported for them.
    assert comparison["fz0_0.05"]["relative_gain"] is None
    assert comparison["qlike"]["relative_gain"] is not None
    tiny = study.run_range(rows, forecasts, start=rows[-20]["session"], end=end)
    assert (
        tiny["contracts"]["pre_close"]["comparisons"]["har_vs_historical_simulation"]["status"]
        == "too_few_pairs"
    )
