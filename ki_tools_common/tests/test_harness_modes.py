"""The shared contract remains loaded and does not override the host's plan gate."""
import re

import pytest

from ki_tools_common.harness import ki_harness as harness


def test_all_modes_load_real_harness_and_expose_their_role(tmp_path):
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools/run.py").write_text("pass\n")
    (tmp_path / "SKILL.md").write_text("# KI\n> **MANDATORY EXECUTION POLICY**\n> Never substitute a toy model.\n\n")
    (tmp_path / "dag.yaml").write_text("outputs:\n- var: q\n  validation_rank: 1\n  unit: m3/s\n")
    (tmp_path / "preflight_check.py").write_text("pass\n")
    for mode, marker in (("execute", "TOOLS (validated)"), ("inspect", "INSPECT mode"), ("edit", "EDIT mode")):
        text = harness.contract(tmp_path, mode=mode)
        harness.assert_injected(text)
        assert marker in text and "rank 1: q [m3/s]" in text
    inspect = harness.contract(tmp_path, mode="inspect")
    assert "NOT inherently read-only" in inspect
    assert "explicit driver authorization" in inspect
    assert "Non-mutating probes ARE allowed" not in inspect
    with pytest.raises(harness.KiHarnessError):
        harness.assert_injected("four-line fallback")
    execution = harness.contract(tmp_path, mode="execute")
    # The repair must not remove core scientific obligations from execution.
    for key in ("policy_no_surrogates", "protocol_in_order", "tools_absolute_path",
                "know_the_outputs", "verify_units_from_files", "preflight_first", "failure_ladder"):
        assert re.search(harness.OBLIGATIONS[key]["contract"], execution, re.S | re.I), key
