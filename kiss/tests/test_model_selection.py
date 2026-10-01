"""Pinned KI selection must not expand from VIC driver names or input paths."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import flowrun, projectrun


@pytest.mark.parametrize("text", [
    "Run the genuine installed native VIC classic driver on the official Stehekin example. "
    "Inspect global_param.classic.STEHE.feb.txt and run "
    "D:/VIC/binaries/VIC-5.1.0/vic/drivers/classic/vic_classic.exe. "
    "No CaMa-Flood routing run is requested.",
    "Run VIC 5.1.0 classic driver with the original inputs.",
    "Run VIC's classic driver with the original inputs.",
    "Run VIC using the classic driver with the original inputs.",
    "Run the classic driver of VIC with the original inputs.",
    "Run VIC (CLASSIC driver) with the original inputs.",
    "Run VIC with C:\\models\\CLASSIC\\forcing.txt and no CLASSIC model.",
    "Run VIC and inspect CLASSIC.exe plus global_param.CLASSIC.txt.",
    "Run VIC; the word classic describes the VIC driver.",
    "Run VIC; the term 'CLASSIC' refers to its driver.",
    "Run VIC; classic here means the VIC driver.",
    "Run VIC; the label `classic` identifies its native driver.",
    (Path(__file__).parent / "fixtures/vic_model_selection_prompt.txt").read_text(encoding="utf-8"),
])
def test_vic_driver_and_references_do_not_add_classic(tmp_path, text):
    project = tmp_path / "project"
    project.mkdir()
    catalogue = [SimpleNamespace(name=name, root=tmp_path / name)
                 for name in ("VIC", "CLASSIC", "CaMa_Flood")]
    result = flowrun.pre(project, text, ["VIC"], catalogue, None, None)
    assert result.gated and result.names == ["VIC"]
    state = json.loads((project / "runs/flow-state.json").read_text(encoding="utf-8"))
    assert state["selected_kis"] == ["VIC"]
    assert projectrun.load(project)["selected_kis"] == ["VIC"]


@pytest.mark.parametrize("text, extra", [
    ("Run VIC and CLASSIC.", "CLASSIC"),
    ("Run VIC classic driver; also run the CLASSIC model.", "CLASSIC"),
    ("The word classic describes the VIC driver; also run CLASSIC.", "CLASSIC"),
    ("Prepare VIC-CaMa, input data", "CaMa_Flood"),
    ("Run VIC and CaMa_Flood.", "CaMa_Flood"),
])
def test_positive_model_requests_and_coupling_remain_supported(tmp_path, text, extra):
    project = tmp_path / "project"
    project.mkdir()
    catalogue = [SimpleNamespace(name=name, root=tmp_path / name)
                 for name in ("VIC", "CLASSIC", "CaMa_Flood")]
    result = flowrun.pre(project, text, ["VIC"], catalogue, None, None)
    assert result.names == ["VIC", extra]
