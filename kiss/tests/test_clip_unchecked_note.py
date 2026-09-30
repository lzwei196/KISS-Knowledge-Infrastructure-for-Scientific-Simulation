"""Bug #3 (live Mac test, 2026-09-29): the agent offered CMFD 3-hourly only as a 604 GB
national package without checking whether GeoForge could clip it, as it had for daily CMFD.
The catalogue lists both as 'manual' at full size; clipping is known only from an estimate.
Desktop now says so wherever it shows such a product without a saved clip estimate.
"""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from kiss_cli import flowrun, obs_access, obs_subset, plan_review

CATALOGUE = {"ok": True, "datasets": [
    {"id": "cmfd_china_3hr_010", "name": "CMFD 3-hourly", "delivery": "manual", "size": 649142267059},
    {"id": "cmfd_china_daily_010", "name": "CMFD daily", "delivery": "manual", "size": 242207573601},
    {"id": "nasa_power_daily", "name": "NASA POWER", "delivery": "served", "size": 1000},
]}


@pytest.fixture
def planning(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.setattr(obs_access, "load_catalogue", lambda *a, **k: CATALOGUE)
    project = tmp_path / "project"
    (project / "runs").mkdir(parents=True)
    root = tmp_path / "kis" / "M"
    (root / "tools").mkdir(parents=True)
    (root / "SKILL.md").write_text("# M\n")
    (root / "dag.yaml").write_text("outputs:\n- var: q\n  validation_rank: 1\n  unit: m3/s\n")
    flowrun.pre(project, "run M for 2003", ["M"], [SimpleNamespace(name="M", root=root)], None, None)
    return project


def _estimated(project, dataset_id):
    folder = project / ".geoforge" / "subsets"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / (f"{abs(hash(dataset_id)):032d}"[:32] + ".json")).write_text(json.dumps(
        {"request": {"dataset_id": dataset_id}, "estimate": {"subsettable": True}, "status": "awaiting_approval"}))


def _question(message, *labels):
    return {"kind": "choice", "title": "Forcing source?", "message": message,
            "options": [{"id": f"o{i}", "label": label} for i, label in enumerate(labels)]}


def test_a_whole_product_offer_without_a_clip_check_is_labelled(planning):
    _estimated(planning, "cmfd_china_daily_010")
    card = flowrun.request_planning_question(planning, _question(
        "Pick the forcing.", "A. clip cmfd_china_daily_010 (317 MB)",
        "C. download cmfd_china_3hr_010 national package (604 GB)"))
    note = card["message"].split("GeoForge note:", 1)[1]
    assert "cmfd_china_3hr_010" in note and "whole product" in note
    assert "cmfd_china_daily_010" not in note          # its clip was estimated


def test_a_chinese_question_gets_the_note_in_chinese(planning):
    card = flowrun.request_planning_question(planning, _question(
        "请选择气象驱动。", "C. 下载 cmfd_china_3hr_010 全国整包（约 604 GB）"))
    assert "GeoForge 提示" in card["message"] and "cmfd_china_3hr_010" in card["message"]


@pytest.mark.parametrize("label", ["Use nasa_power_daily", "Use my own station file"])
def test_no_note_for_served_products_or_no_database_product(planning, label):
    card = flowrun.request_planning_question(planning, _question("Pick the forcing.", label))
    assert "GeoForge note" not in card["message"]


def test_asking_the_same_question_again_is_still_idempotent(planning):
    q = _question("Pick the forcing.", "C. download cmfd_china_3hr_010 (604 GB)")
    first = flowrun.request_planning_question(planning, q)
    assert flowrun.request_planning_question(planning, q)["id"] == first["id"]


def test_the_approval_card_marks_manual_options_whose_clipping_was_not_checked(planning):
    _estimated(planning, "cmfd_china_daily_010")
    plan = {"scientific_choices": [{"id": "data:forcing", "kind": "data_source", "item": "forcing",
                                    "options": ["cmfd_china_daily_010", "cmfd_china_3hr_010", "nasa_power_daily"],
                                    "picked": "cmfd_china_daily_010"}]}
    inv = {"items": [{"id": "forcing"}]}
    options = {o["dataset_id"]: o for o in plan_review._data_choices(plan, inv, project=planning)[0]["options"]}
    assert options["cmfd_china_3hr_010"]["clip_checked"] is False
    assert options["cmfd_china_daily_010"].get("clip_checked") is not False
    assert "clip_checked" not in options["nasa_power_daily"]


def test_the_card_ui_shows_the_unchecked_label():
    from pathlib import Path
    html = (Path(plan_review.__file__).parent / "web" / "app.html").read_text(encoding="utf-8")
    assert "o.clip_checked===false" in html
