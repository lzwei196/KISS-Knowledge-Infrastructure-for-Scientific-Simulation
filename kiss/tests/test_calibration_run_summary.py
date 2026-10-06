"""Saved calibration evidence must remain distinct from inferred scientific claims."""
import json
from pathlib import Path

import pytest

from kiss_cli import calibration


def saved_summary(tmp_path, report, **payload):
    path = tmp_path / "calibration/runs/run-1/report.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"run_id": "run-1", "budget": 8,
                                "report": report, **payload}), encoding="utf-8")
    return calibration._run_summaries(tmp_path)[0]


def test_summary_exposes_failed_gate_and_raw_metrics_without_inventing_native_count(tmp_path):
    metrics = {"Q": {"nse": -1.84, "r": 0.906, "pbias": 27.61},
               "__kdt__": {"n_pairs": 365, "activation_only": True}}
    objective = {"objective": "Q:magnitude_accuracy", "ok": False,
                 "calibration_loss": 0.2761, "holdout_loss": 0.2847,
                 "baseline_holdout_loss": 0.2817, "beats_baseline": False}
    holdout = {"passed": False, "per_objective": [objective]}
    summary = saved_summary(tmp_path, {"status": "completed", "promotable": False,
        "n_evaluations": 8, "train_metrics": metrics, "holdout": holdout})

    assert summary["requested_optimizer_budget"] == summary["budget"] == 8
    assert summary["optimizer_evaluations"] == 8
    assert summary["native_launch_count"] is None
    assert summary["train_metrics"] == metrics
    assert summary["holdout"] == holdout
    assert summary["promotable"] is False
    check = summary["objective_checks"][0]
    assert {key: check[key] for key in objective} == objective
    assert check["absolute_criterion"] == {
        "available": None, "source": None, "max_loss": None}


def test_recorded_absolute_criteria_preserve_comparison_evidence(tmp_path):
    objectives = [
        {"objective": "Q:magnitude_accuracy", "band_ceiling": 0.25,
         "meets_band": False, "holdout_loss": 0.28, "ok": False},
        {"objective": "ET:magnitude_accuracy", "mag_backstop": 0.3,
         "mag_backstop_loss": 0.5, "ok": False},
        # A recorded correlation check does not establish an absolute loss band.
        {"objective": "Q:temporal_pattern_match", "corr_floor": 0.5,
         "corr_floor_r": 0.2, "ok": False},
    ]
    summary = saved_summary(tmp_path, {"holdout": {"per_objective": objectives}})
    checks = summary["objective_checks"]
    assert checks[0]["absolute_criterion"] == {
        "available": True, "source": "band_ceiling", "max_loss": 0.25}
    assert checks[1]["absolute_criterion"] == {
        "available": True, "source": "mag_backstop", "max_loss": 0.3}
    assert checks[2]["absolute_criterion"]["available"] is None
    for original, check in zip(objectives, checks):
        assert all(check[key] == value for key, value in original.items())


def test_legacy_failure_keeps_missing_evidence_unknown(tmp_path):
    summary = saved_summary(tmp_path, {"status": "failed_no_finite_solution"}, budget=None)
    assert summary["requested_optimizer_budget"] is None
    assert summary["optimizer_evaluations"] is None
    assert summary["native_launch_count"] is None
    assert summary["train_metrics"] is None
    assert summary["objective_checks"] == []
    assert summary["status"] == "failed_no_finite_solution"


@pytest.mark.parametrize("value", [True, -1, 1.5, "15", None])
def test_invalid_recorded_counts_are_not_displayed_as_native_execution(tmp_path, value):
    summary = saved_summary(tmp_path, {"native_launch_count": value, "n_evaluations": value})
    assert summary["native_launch_count"] is None
    assert summary["optimizer_evaluations"] is None


@pytest.mark.parametrize("native_count", [0, 15])
def test_explicit_native_count_is_independent_of_optimizer_count(tmp_path, native_count):
    summary = saved_summary(tmp_path, {"native_launch_count": native_count, "n_evaluations": 8})
    assert summary["native_launch_count"] == native_count
    assert summary["optimizer_evaluations"] == 8


def test_summary_reads_only_saved_report_not_native_artifacts(tmp_path, monkeypatch):
    read_text = Path.read_text

    def report_only(path, *args, **kwargs):
        assert path.name == "report.json", "summary must not rescan evaluation files"
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", report_only)
    summary = saved_summary(tmp_path, {"n_evaluations": 8,
        "train_metrics": {"__kdt__": {"evaluation_dir": "unavailable/external/path"}},
        "holdout": {"per_objective": [None, "bad", {"band_ceiling": True}]}})
    assert summary["optimizer_evaluations"] == 8
    assert len(summary["objective_checks"]) == 1
    assert summary["objective_checks"][0]["absolute_criterion"]["available"] is None
