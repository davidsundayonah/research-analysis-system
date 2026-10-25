import pandas as pd
import pytest
import sqlite3

from app.database.database import Database
from app.statistics.statistical_workflow import (
    StatisticalWorkflow,
    TestRecommendationEngine,
)


@pytest.fixture
def setup_workflow(tmp_path):
    database_path = tmp_path / "workflow.db"
    database = Database(database_path)
    project_id = database.create_project("Study")
    dataset_id = database.create_dataset(
        project_id,
        "study.csv",
        str(tmp_path / "study.csv"),
        "csv",
        8,
        3,
    )
    question_id = database.create_research_question(
        project_id,
        "Does group affect the score?",
        design_type="comparison",
        proposed_test="Mann-Whitney U",
    )
    hypothesis_id = database.create_hypothesis(
        project_id,
        question_id,
        null_hypothesis="Group means are equal.",
        alternative_hypothesis="Group means differ.",
    )
    dataframe = pd.DataFrame({
        "score": [2, 3, 4, 5, 7, 8, 9, 11],
        "group": ["A"] * 4 + ["B"] * 4,
        "predictor": [1, 2, 3, 4, 5, 6, 7, 8],
    })
    database.replace_dataset_variables(
        dataset_id,
        [(str(name), str(dtype)) for name, dtype in dataframe.dtypes.items()],
    )
    database.set_question_variable(
        project_id,
        question_id,
        dataset_id,
        "score",
        "outcome",
    )
    database.set_question_variable(
        project_id,
        question_id,
        dataset_id,
        "group",
        "grouping",
    )

    yield {
        "path": database_path,
        "database": database,
        "project_id": project_id,
        "dataset_id": dataset_id,
        "question_id": question_id,
        "hypothesis_id": hypothesis_id,
        "dataframe": dataframe,
    }
    database.close()


def test_linked_analysis_persists_settings_decision_and_dataset_snapshot(setup_workflow):
    context = setup_workflow
    workflow = StatisticalWorkflow(context["database"])
    question_id = context["question_id"]
    result = workflow.run_analysis(
        context["project_id"],
        question_id,
        context["hypothesis_id"],
        context["dataset_id"],
        context["dataframe"],
        "independent_t_test",
        {
            "outcome_variable": "score",
            "grouping_variable": "group",
            "equal_var": False,
            "confidence_level": 0.9,
            "alpha": 0.01,
        },
    )

    assert result.status == "ok"
    run = context["database"].get_question_analysis_runs(
        context["project_id"], question_id
    )[0]
    decoded = context["database"].decode_analysis_run(run)
    assert decoded["actual_test"] == "independent_t_test"
    assert decoded["settings"]["parameters"]["alpha"] == 0.01
    assert decoded["settings"]["test"] == "independent_t_test"
    assert decoded["settings"]["parameters"]["missing_policy"] == "listwise"
    assert "scipy" in decoded["settings"]["software"]
    assert decoded["dataset_signature"] == workflow.dataset_signature(
        context["dataframe"]
    )
    assert decoded["hypothesis_decision"] == result.decision
    assert decoded["result"]["details"]["decision_scope"].startswith("Decision uses")

    changed = context["dataframe"].copy()
    changed.loc[0, "score"] = 99
    assert not workflow.is_snapshot_current(decoded, changed)
    assert workflow.is_snapshot_current(decoded, context["dataframe"])
    with pytest.raises(sqlite3.IntegrityError):
        context["database"].delete_dataset(context["dataset_id"])
    assert len(context["database"].get_question_analysis_runs(
        context["project_id"], question_id
    )) == 1

    context["database"].close()
    reopened = Database(context["path"])
    stored = reopened.decode_analysis_run(
        reopened.get_question_analysis_runs(context["project_id"], question_id)[0]
    )
    assert stored["settings"]["parameters"]["confidence_level"] == 0.9
    assert stored["result"]["p_value"] == pytest.approx(result.p_value)
    assert reopened.get_research_question(
        context["project_id"], question_id
    )["proposed_test"] == "Mann-Whitney U"
    reopened.delete_project(context["project_id"])
    assert reopened.get_question_analysis_runs(
        context["project_id"],
        question_id,
    ) == []
    assert reopened.get_dataset(context["dataset_id"]) is None
    reopened.close()
    context["database"] = Database(context["path"])


def test_project_multiplicity_correction_preserves_raw_and_adjusted_p_values(setup_workflow):
    context = setup_workflow
    workflow = StatisticalWorkflow(context["database"])
    settings = {
        "outcome_variable": "score",
        "grouping_variable": "group",
        "equal_var": False,
        "confidence_level": 0.95,
    }
    for _ in range(2):
        workflow.run_analysis(
            context["project_id"],
            context["question_id"],
            context["hypothesis_id"],
            context["dataset_id"],
            context["dataframe"],
            "independent_t_test",
            settings,
        )

    runs = context["database"].get_project_analysis_runs(context["project_id"])
    assert len(runs) == 2
    for run in runs:
        result = context["database"].decode_analysis_run(run)["result"]
        assert result["details"]["multiplicity_method"] == "holm"
        assert result["details"]["multiplicity_family_size"] == 2
        assert result["details"]["raw_p_value"] <= result["details"]["adjusted_p_value"]
        assert result["p_value"] == result["details"]["adjusted_p_value"]


def test_linked_analysis_rejects_unlinked_variables_and_incomplete_hypotheses(
    setup_workflow,
):
    context = setup_workflow
    workflow = StatisticalWorkflow(context["database"])

    unlinked = workflow.run_analysis(
        context["project_id"],
        context["question_id"],
        context["hypothesis_id"],
        context["dataset_id"],
        context["dataframe"],
        "linear_regression",
        {"predictor_variable": "predictor", "outcome_variable": "score"},
    )
    assert unlinked.error.code == "VARIABLE_ROLE_MISMATCH"

    incomplete_id = context["database"].create_hypothesis(
        context["project_id"],
        context["question_id"],
        null_hypothesis="",
        alternative_hypothesis="An effect exists.",
    )
    incomplete = workflow.run_analysis(
        context["project_id"],
        context["question_id"],
        incomplete_id,
        context["dataset_id"],
        context["dataframe"],
        "independent_t_test",
        {"outcome_variable": "score", "grouping_variable": "group"},
    )
    assert incomplete.error.code == "INCOMPLETE_HYPOTHESIS"


def test_analysis_run_rejects_cross_project_ownership(setup_workflow, tmp_path):
    context = setup_workflow
    other_project_id = context["database"].create_project("Other")
    result = StatisticalWorkflow(context["database"]).run_analysis(
        other_project_id,
        context["question_id"],
        context["hypothesis_id"],
        context["dataset_id"],
        context["dataframe"],
        "independent_t_test",
        {"outcome_variable": "score", "grouping_variable": "group"},
    )
    assert result.error.code == "OWNERSHIP_MISMATCH"


def test_run_uses_project_significance_level_unless_alpha_is_overridden(setup_workflow):
    context = setup_workflow
    context["database"].connection.execute(
        "UPDATE projects SET significance_level = ? WHERE id = ?",
        (0.1, context["project_id"]),
    )
    context["database"].connection.commit()
    workflow = StatisticalWorkflow(context["database"])

    inherited = workflow.run_analysis(
        context["project_id"],
        context["question_id"],
        context["hypothesis_id"],
        context["dataset_id"],
        context["dataframe"],
        "independent_t_test",
        {"outcome_variable": "score", "grouping_variable": "group"},
    )
    inherited_run = context["database"].get_question_analysis_runs(
        context["project_id"],
        context["question_id"],
    )[0]
    saved_inherited = context["database"].decode_analysis_run(inherited_run)

    overridden = workflow.run_analysis(
        context["project_id"],
        context["question_id"],
        context["hypothesis_id"],
        context["dataset_id"],
        context["dataframe"],
        "independent_t_test",
        {
            "outcome_variable": "score",
            "grouping_variable": "group",
            "alpha": 0.01,
        },
    )
    saved_override = context["database"].decode_analysis_run(
        context["database"].get_question_analysis_runs(
            context["project_id"],
            context["question_id"],
        )[0]
    )

    assert inherited.status == overridden.status == "ok"
    assert saved_inherited["settings"]["parameters"]["alpha"] == 0.1
    assert saved_inherited["result"]["details"]["alpha"] == 0.1
    assert saved_override["settings"]["parameters"]["alpha"] == 0.01
    assert saved_override["result"]["details"]["alpha"] == 0.01


def test_recommender_explains_design_and_group_count():
    question = {"design_type": "comparison"}
    dataframe = pd.DataFrame({
        "score": [1, 2, 3, 4, 5, 6],
        "group": ["A", "A", "B", "B", "C", "C"],
    })
    linked = [
        {"variable_name": "score", "role": "outcome", "variable_exists": 1},
        {"variable_name": "group", "role": "grouping", "variable_exists": 1},
    ]

    recommendation = TestRecommendationEngine().recommend(
        question,
        dataframe,
        linked,
    )[0]

    assert recommendation["test"] == "one_way_anova"
    assert "3 independent groups" in recommendation["reason"]
    assert recommendation["settings"]["outcome_variable"] == "score"


def test_recommender_selects_saved_descriptive_analysis_without_hypothesis():
    question = {"design_type": "descriptive"}
    dataframe = pd.DataFrame({"score": [1, 2, 2, 3], "group": ["A", "A", "B", "B"]})
    links = [
        {"variable_name": "score", "role": "outcome", "variable_exists": 1},
    ]

    recommendation = TestRecommendationEngine().recommend(
        question,
        dataframe,
        links,
    )[0]

    assert recommendation["test"] == StatisticalWorkflow.DESCRIPTIVE_TEST
    assert recommendation["settings"] == {"variables": ["score"]}
    assert "no inferential test" in recommendation["reason"].lower()


def test_descriptive_analysis_saves_report_without_hypothesis(setup_workflow):
    context = setup_workflow
    question_id = context["database"].create_research_question(
        context["project_id"],
        "What are the observed score summaries?",
        design_type="descriptive",
    )
    context["database"].set_question_variable(
        context["project_id"],
        question_id,
        context["dataset_id"],
        "score",
        "outcome",
    )

    result = StatisticalWorkflow(context["database"]).run_analysis(
        context["project_id"],
        question_id,
        None,
        context["dataset_id"],
        context["dataframe"],
        StatisticalWorkflow.DESCRIPTIVE_TEST,
        {"variables": ["score"]},
    )

    assert result.status == "ok"
    assert result.decision == "descriptive_only"
    run = context["database"].get_question_analysis_runs(
        context["project_id"], question_id
    )[0]
    assert run["hypothesis_id"] is None
    saved = context["database"].decode_analysis_run(run)
    assert saved["result"]["details"]["report"]["numeric_summary"]
    assert "frequency_tables" in saved["result"]["details"]["report"]


def test_recommender_offers_rank_alternative_and_warns_when_links_are_stale():
    question = {"design_type": "association"}
    dataframe = pd.DataFrame({
        "x": list(range(12)),
        "y": list(reversed(range(12))),
    })
    links = [
        {"variable_name": "x", "role": "predictor", "variable_exists": 1},
        {"variable_name": "y", "role": "outcome", "variable_exists": 1},
        {"variable_name": "old", "role": "outcome", "variable_exists": 0},
    ]

    recommendations = TestRecommendationEngine().recommend(
        question,
        dataframe,
        links,
    )

    assert [item["settings"]["method"] for item in recommendations] == [
        "pearson",
        "spearman",
    ]
    assert all(any("stale" in warning for warning in item["warnings"]) for item in recommendations)
    assert all(item["reason"] for item in recommendations)


def test_recommender_prioritizes_spearman_for_ordinal_variables():
    question = {"design_type": "association"}
    dataframe = pd.DataFrame({
        "rating": [1, 2, 3, 4, 5, 1, 2, 3, 4, 5, 1, 2],
        "rank": [2, 3, 4, 5, 1, 2, 3, 4, 5, 1, 2, 3],
    })
    links = [
        {"variable_name": "rating", "role": "predictor", "variable_exists": 1},
        {"variable_name": "rank", "role": "outcome", "variable_exists": 1},
    ]

    recommendations = TestRecommendationEngine().recommend(
        question,
        dataframe,
        links,
    )

    assert recommendations[0]["settings"]["method"] == "spearman"
    assert "ordinal" in recommendations[0]["reason"].lower()
    assert "interval-scale" in recommendations[1]["reason"]


def test_recommender_uses_sample_structure_for_paired_design():
    question = {"design_type": "comparison"}
    dataframe = pd.DataFrame({
        "before": [10, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22],
        "after": [11, 13, 12, 15, 16, 17, 18, 19, 20, 21, 22, 23],
    })
    links = [
        {"variable_name": "before", "role": "outcome", "variable_exists": 1},
        {"variable_name": "after", "role": "outcome", "variable_exists": 1},
    ]

    recommendation = TestRecommendationEngine().recommend(
        question,
        dataframe,
        links,
        sample_structure="paired",
    )[0]

    assert recommendation["test"] == "paired_t_test"
    assert "within-unit differences" in recommendation["reason"]


def test_recommender_lists_all_independent_comparison_role_combinations():
    question = {"design_type": "comparison"}
    dataframe = pd.DataFrame({
        "score_a": list(range(12)),
        "score_b": list(range(12, 24)),
        "group_a": ["A"] * 6 + ["B"] * 6,
        "group_b": ["X"] * 4 + ["Y"] * 4 + ["Z"] * 4,
    })
    links = [
        {"variable_name": "score_a", "role": "outcome", "variable_exists": 1},
        {"variable_name": "score_b", "role": "outcome", "variable_exists": 1},
        {"variable_name": "group_a", "role": "grouping", "variable_exists": 1},
        {"variable_name": "group_b", "role": "grouping", "variable_exists": 1},
    ]

    candidates = TestRecommendationEngine().recommend(question, dataframe, links)

    assert len(candidates) == 4
    assert {candidate["settings"]["outcome_variable"] for candidate in candidates} == {
        "score_a",
        "score_b",
    }
    assert {candidate["settings"]["grouping_variable"] for candidate in candidates} == {
        "group_a",
        "group_b",
    }
    assert all("choose the intended comparison" in item["reason"] for item in candidates)


def test_recommender_paired_candidates_and_low_pair_warning():
    question = {"design_type": "comparison"}
    dataframe = pd.DataFrame({
        "before_a": [1, 2, 3, 4],
        "after_a": [2, 3, 4, 5],
        "before_b": [3, 4, 5, 6],
    })
    links = [
        {"variable_name": name, "role": "outcome", "variable_exists": 1}
        for name in dataframe.columns
    ]

    candidates = TestRecommendationEngine().recommend(
        question,
        dataframe,
        links,
        sample_structure="paired",
    )

    assert len(candidates) == 3
    assert all(candidate["test"] == "paired_t_test" for candidate in candidates)
    assert all("Multiple outcome pairs" in candidate["reason"] for candidate in candidates)
    assert all(any("Small paired samples" in item for item in candidate["warnings"]) for candidate in candidates)


def test_recommender_uses_measure_level_for_numeric_codes_and_mixed_associations():
    question = {"design_type": "association"}
    nominal_frame = pd.DataFrame({
        "gender_code": [1, 2] * 6,
        "education_code": [1, 2, 3] * 4,
    })
    nominal_links = [
        {"variable_name": name, "role": role, "variable_exists": 1}
        for name, role in [("gender_code", "predictor"), ("education_code", "outcome")]
    ]
    nominal = TestRecommendationEngine().recommend(
        question,
        nominal_frame,
        nominal_links,
    )

    mixed_frame = pd.DataFrame({
        "group": ["A", "B"] * 6,
        "score": list(range(12)),
    })
    mixed_links = [
        {"variable_name": "group", "role": "predictor", "variable_exists": 1},
        {"variable_name": "score", "role": "outcome", "variable_exists": 1},
    ]
    mixed = TestRecommendationEngine().recommend(
        question,
        mixed_frame,
        mixed_links,
    )

    assert len(nominal) == 1
    assert nominal[0]["test"] == "chi_square_test"
    assert mixed[0]["test"] is None
    assert "incompatible measurement levels" in mixed[0]["reason"]


def test_recommender_honors_saved_variable_measurement_metadata():
    question = {"design_type": "association"}
    dataframe = pd.DataFrame({
        "coded_score": [1, 2] * 6,
        "outcome": list(range(12)),
    })
    links = [
        {"variable_name": "coded_score", "role": "predictor", "variable_exists": 1},
        {"variable_name": "outcome", "role": "outcome", "variable_exists": 1},
    ]

    recommendations = TestRecommendationEngine().recommend(
        question,
        dataframe,
        links,
        variable_metadata=[
            {"name": "coded_score", "measure": "nominal"},
            {"name": "outcome", "measure": "scale"},
        ],
    )

    assert recommendations[0]["test"] is None
    assert "incompatible measurement levels" in recommendations[0]["reason"]


def test_recommender_warns_on_small_correlation_samples():
    question = {"design_type": "association"}
    dataframe = pd.DataFrame({"x": [1, 2, 3, 4], "y": [2, 4, 1, 3]})
    links = [
        {"variable_name": "x", "role": "predictor", "variable_exists": 1},
        {"variable_name": "y", "role": "outcome", "variable_exists": 1},
    ]

    candidates = TestRecommendationEngine().recommend(question, dataframe, links)

    assert all(any("Small samples" in item for item in candidate["warnings"]) for candidate in candidates)


def test_recommender_requires_explicit_pairing_structure_and_distinct_measures():
    question = {"design_type": "comparison"}
    dataframe = pd.DataFrame({
        "first": [1, 2, 3, 4],
        "second": [2, 3, 4, 5],
        "group": ["A", "A", "B", "B"],
    })
    pair_links = [
        {"variable_name": "first", "role": "outcome", "variable_exists": 1},
        {"variable_name": "second", "role": "outcome", "variable_exists": 1},
        {"variable_name": "group", "role": "grouping", "variable_exists": 1},
    ]
    paired = TestRecommendationEngine().recommend(
        question,
        dataframe,
        pair_links,
        sample_structure="paired",
    )
    invalid_structure = TestRecommendationEngine().recommend(
        question,
        dataframe,
        pair_links,
        sample_structure="unknown",
    )

    assert len(paired) == 1
    assert paired[0]["settings"] == {
        "first_variable": "first",
        "second_variable": "second",
    }
    assert paired[0]["test"] == "paired_t_test"
    assert invalid_structure[0]["test"] is None
    assert "paired or independent" in invalid_structure[0]["reason"]


def test_recommender_requires_predictor_and_outcome_roles_for_association():
    question = {"design_type": "association"}
    dataframe = pd.DataFrame({"x": list(range(12)), "y": list(range(12, 24))})
    same_role_links = [
        {"variable_name": "x", "role": "predictor", "variable_exists": 1},
        {"variable_name": "y", "role": "predictor", "variable_exists": 1},
    ]

    result = TestRecommendationEngine().recommend(
        question,
        dataframe,
        same_role_links,
    )

    assert result[0]["test"] is None
    assert "predictor and one outcome" in result[0]["reason"]
