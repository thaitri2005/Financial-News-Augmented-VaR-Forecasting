from newsvar.search_plan import gdelt_alternative_linear_plan, preferred_linear_plan


def test_preferred_plan_has_declared_equal_budget_for_all_feature_groups() -> None:
    plan = preferred_linear_plan()
    assert len(plan.runs) == 36
    assert {run.feature_group for run in plan.runs} == {"Q0", "Q1", "Q2"}
    assert len({run.fold for run in plan.runs}) == 2
    assert len(plan.identity) == 64


def test_gdelt_alternative_has_one_fold_and_eighteen_linear_runs() -> None:
    plan = gdelt_alternative_linear_plan()
    assert len(plan.runs) == 18
    assert all(run.fold == "development_2022" for run in plan.runs)
