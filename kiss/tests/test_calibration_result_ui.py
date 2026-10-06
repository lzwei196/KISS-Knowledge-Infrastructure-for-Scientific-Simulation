"""Render actual calibration UI code against recorded-report shapes, offline."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node is required")
PAGE = Path(__file__).parents[1] / "kiss_cli/web/app.html"


def render(latest, zh=False):
    page = PAGE.read_text(encoding="utf-8")
    start = page.index("function calibrationResultCard(")
    source = page[start:page.index("function renderData(", start)]
    program = r"""
const input=JSON.parse(require('fs').readFileSync(0,'utf8'));
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
""" + source + "process.stdout.write(calibrationResultCard(input.latest,input.zh));"
    return subprocess.run([NODE, "-e", program], input=json.dumps({"latest": latest, "zh": zh}),
                          capture_output=True, text=True, encoding="utf-8", check=True, timeout=10).stdout


def crowsnest():
    return {
        "ki": "CRHM", "status": "completed", "algorithm": "dds", "promotable": False,
        "requested_optimizer_budget": 8, "optimizer_evaluations": 8, "native_launch_count": None,
        "best_loss": [1.5599773967057795], "report_path": "calibration/runs/run/report.json",
        "train_metrics": {"basinflow_s": {"nse": -1.8438621457072752, "kge": -.534937908649,
            "r": .906047529707, "pbias": 27.609264770428, "rmse": 5.26416332552},
            "__kdt__": {"activation_only": True, "temporal_check_previously_inspected": True,
                        "native_sha256": "private-long-hash-not-for-summary", "n_pairs": 365}},
        "objective_checks": [
            {"objective": "basinflow_s:magnitude_accuracy", "calibration_loss": .276092647704,
             "holdout_loss": .28470846829, "baseline_holdout_loss": .281678411869,
             "ok": False, "beats_baseline": False,
             "absolute_criterion": {"available": None, "source": None, "max_loss": None}},
            {"objective": "basinflow_s:temporal_pattern_match", "calibration_loss": 2.8438621457,
             "holdout_loss": 1.8011876883, "baseline_holdout_loss": 7.8197157787,
             "ok": True, "beats_baseline": True,
             "absolute_criterion": {"available": None, "source": None, "max_loss": None}},
        ],
    }


@pytest.mark.parametrize("zh", [False, True])
def test_real_report_shape_separates_fit_failure_and_unrecorded_native_count(zh):
    out = render(crowsnest(), zh)
    assert ("未提升为正式配置" if zh else "Not promoted") in out
    assert "NSE -1.8439" in out and "r 0.90605" in out and "PBIAS (%) 27.609" in out
    assert ("模型启动次数: 未记录" if zh else "Native model launches: not recorded") in out
    assert ("优化评估: 8" if zh else "Optimizer evaluations: 8") in out
    assert "0.28471" in out and "0.28168" in out and "7.8197" in out
    assert ("基线比较未通过" if zh else "Baseline comparison failed") in out
    assert ("绝对损失阈值未记录" if zh else "Absolute loss threshold not recorded") in out
    assert ("检查期数据此前已查看，不是独立验证" if zh else "check period was previously inspected") in out
    assert "private-long-hash" not in out and "__kdt__" not in out
    assert "Validated" not in out


@pytest.mark.parametrize("zh", [False, True])
def test_promotable_means_configured_checks_passed_not_automatic_validation(zh):
    report = crowsnest()
    report.update(promotable=True, native_launch_count=15, train_metrics={"nse": .7})
    out = render(report, zh)
    assert ("配置检查已通过" if zh else "Configured checks passed") in out
    assert ("并不自动证明" if zh else "does not establish independent scientific validation") in out
    assert ("模型启动次数: 15" if zh else "Native model launches: 15") in out
    assert "Validated" not in out


def test_old_server_summary_remains_useful_without_inventing_counts_or_thresholds():
    out = render({"ki": "CRHM", "budget": 8, "status": "completed", "best_loss": [1.56],
                  "holdout": {"per_objective": [{"objective": "flow:magnitude_accuracy", "ok": False,
                      "calibration_loss": .27, "holdout_loss": .28, "baseline_holdout_loss": .26}]}})
    assert "Requested optimizer budget: 8" in out
    assert "Optimizer evaluations: not recorded" in out and "Native model launches: not recorded" in out
    assert "flow · Magnitude" in out and ">Fail<" in out
    assert "Absolute loss threshold not recorded" in out
    assert "not configured" not in out


@pytest.mark.parametrize("criterion", [
    {"absolute_criterion": {"available": True, "source": "band_ceiling", "max_loss": .2}},
    {"band_ceiling": .2}, {"mag_backstop": .2},
])
def test_recorded_absolute_and_correlation_thresholds_are_visible(criterion):
    out = render({"objective_checks": [{"objective": "flow:temporal_pattern_match", "ok": True,
                   "calibration_loss": .1, "holdout_loss": .15, "corr_floor": .5, **criterion}]})
    assert "Loss ≤ 0.2" in out and "r ≥ 0.5" in out
    assert "Absolute loss threshold not recorded" not in out


def test_summary_escapes_report_text_and_does_not_render_non_numeric_metrics():
    attack = '<img src=x onerror="attack()">'
    out = render({"ki": attack, "reason": attack, "report_path": attack,
                  "train_metrics": {attack: {"nse": attack, "r": .8}},
                  "objective_checks": [{"objective": attack, "calibration_loss": attack, "ok": None}]})
    assert "<img" not in out and "&lt;img" in out
    assert "NSE &lt;img" not in out and "r 0.8" in out
    assert "Unconfirmed" in out


def test_no_run_does_not_render_an_empty_success_card():
    assert render(None) == ""
