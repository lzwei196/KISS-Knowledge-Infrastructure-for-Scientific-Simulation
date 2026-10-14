"""Host search facts guide existing-software setup without becoming verification."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from kiss_cli import setup


def report(state="complete", candidates=None, **extra):
    return {
        "schema_version": 1, "request_id": "host-owned-attempt", "model": "Demo",
        "candidates": candidates if candidates is not None else [r"C:\Models\Demo\demo.exe"],
        "scope": {"recursive": False, "indexed": False, "hints": ["demo.exe"],
                  "sources": ["exact PATH names", "direct conventional-location entries", "exact selected paths"]},
        "limits": {"timeout_seconds": 8.0, "entries": 512, "results": 24, "hints": 12,
                   "roots": 64, "document_bytes": 65536},
        "stats": {"entries_checked": 12, "roots_checked": 3, "candidates_found": 1,
                  "elapsed_seconds": 0.2},
        "state": state, "complete": state == "complete", "reason": "Finite scope exhausted",
        "checked_at": 1791619200, **extra,
    }


def facts_from(text):
    start = text.index("[HOST DISCOVERY EVIDENCE — NOT SOFTWARE VERIFICATION]\n")
    payload = text[start:].split("\n", 1)[1]
    return json.JSONDecoder().raw_decode(payload)[0]


def task(tmp_path, **kwargs):
    return setup.agent_task(SimpleNamespace(name="Demo"), SimpleNamespace(), tmp_path, **kwargs)


@pytest.mark.parametrize("state,reason", [
    ("complete", "Finite scope exhausted"),
    ("limited", "Entry limit reached"),
    ("limited", "Discovery timed out"),
    ("failed", "Discovery worker failed"),
])
def test_report_preserves_host_facts_and_marks_every_hit_unverified(state, reason):
    source = report(state, reason=reason)
    previous = deepcopy(source)
    text = setup.discovery_guidance(source)
    facts = facts_from(text)
    for key in ("state", "complete", "reason", "candidates", "scope", "limits", "stats"):
        assert facts[key] == source[key]
    assert facts["candidate_status"] == "unverified"
    assert "not proof of a usable installation" in text
    assert "scientific pass" in text and "finite search scope" in text
    assert "does not establish a security sandbox" in text
    assert source == previous


@pytest.mark.parametrize("state", ["complete", "limited", "failed"])
def test_empty_report_never_claims_machine_wide_absence(state):
    text = setup.discovery_guidance(report(state, candidates=[]))
    assert facts_from(text)["candidates"] == []
    assert "an empty candidate list never proves the software is absent" in text
    assert "one structured setup request for a concrete installation directory or executable path" in text
    assert "Do not guess a path or expand the search scope yourself" in text
    assert "whole-drive find commands" in text and "recursive globs" in text


def test_inconsistent_complete_flag_is_not_upgraded_to_complete():
    facts = facts_from(setup.discovery_guidance(report("complete", complete=False)))
    assert facts["state"] == "limited" and facts["complete"] is False


def test_invalid_report_fields_fail_closed_and_cannot_inject_arbitrary_payloads():
    text = setup.discovery_guidance({
        "state": [], "complete": True, "candidates": [{"path": "not-a-string"}],
        "scope": {"sources": ["AUTH_TOKEN=do-not-print"], "recursive": "false"},
        "limits": {"entries": float("inf"), "results": True, "roots": -1},
        "stats": {"entries_checked": float("nan"), "elapsed_seconds": {"secret": "do-not-print"}},
        "environment": {"AUTH_TOKEN": "do-not-print"}, "stdout": "do-not-print",
    })
    facts = facts_from(text)
    assert facts["state"] == "failed" and facts["complete"] is False
    assert facts["candidates"] == [] and facts["limits"] == {} and facts["stats"] == {}
    assert "do-not-print" not in text and "NaN" not in text and "Infinity" not in text


def test_unknown_fields_and_diagnostic_payloads_are_not_copied_to_prompt():
    source = report()
    source.update(environment={"TOKEN": "report-secret"}, stderr="report-secret", command="report-secret")
    for section in ("scope", "limits", "stats"):
        source[section]["extra"] = "report-secret"
    text = setup.discovery_guidance(source)
    assert "report-secret" not in text
    assert "host-owned-attempt" not in text  # metadata is not needed to guide candidate checks


def test_candidate_paths_remain_exact_and_omissions_are_explicit():
    paths = ["C:/" + "x" * 20000, r"C:\Model Assets\模型\bin\demo.exe"]
    paths.extend(f"C:/other/{i}/demo.exe" for i in range(30))
    text = setup.discovery_guidance(report(candidates=paths))
    facts = facts_from(text)
    assert paths[0] not in facts["candidates"]
    assert facts["candidates"][0] == paths[1]
    assert set(facts["candidates"]).issubset(set(paths))
    assert len(facts["candidates"]) <= 24
    assert facts["presentation_omissions"]["candidates"] == len(paths) - len(facts["candidates"])
    assert "Presentation omissions are not negative search results" in text
    assert len(text) < 16000


def test_optional_report_has_no_output_when_not_supplied():
    assert setup.discovery_guidance(None) == ""


def test_existing_mode_uses_selected_path_and_host_evidence_without_rediscovery(tmp_path):
    selected = r"C:\Already Installed\Demo\demo.exe"
    text = task(tmp_path, installation_mode="existing", existing_paths=[selected],
                discovery_report=report("limited", reason="Entry limit reached"))
    assert json.dumps([selected], ensure_ascii=False, indent=2) in text
    assert facts_from(text)["state"] == "limited"
    assert "named installation trees" in text and "do not repeat a full-drive search" in text
    assert "Do not download, clone" in text and "resolved_existing_path" in text
    assert "unless the user explicitly switches modes" in text
    assert "then run the KI's real preflight" in text


@pytest.mark.parametrize("installation_only", [False, True])
def test_new_install_mode_is_unchanged_when_discovery_report_is_supplied(tmp_path, installation_only):
    original = task(tmp_path, installation_only=installation_only)
    with_report = task(tmp_path, installation_only=installation_only, discovery_report=report("failed"))
    assert original == with_report
    assert "HOST DISCOVERY" not in with_report


def test_existing_mode_without_report_still_respects_exact_path_scope(tmp_path):
    text = task(tmp_path, installation_mode="existing", existing_paths=["C:/Models/Demo"])
    assert "HOST DISCOVERY" not in text and "C:/Models/Demo" in text
    assert "unverified" in text and "do not repeat a full-drive search" in text


def test_installation_only_existing_mode_uses_startup_probe_and_keeps_restrictions(tmp_path):
    text = task(tmp_path, installation_mode="existing", installation_only=True,
                existing_paths=["C:/Models/Demo"], discovery_report=report())
    assert "then use only the permitted cheap startup or declared Python import probe" in text
    assert "then run the KI's real preflight" not in text
    for restriction in (
            "Do NOT run the KI preflight, examples, reference cases, simulations",
            "Do NOT download", "Do not bypass", "or auto-accept an installer licence",
            "Do not substitute a toy implementation", "Do not create or overwrite GeoForge's",
            "installation-test.json", "not a scientific verification"):
        assert restriction in text


def test_regular_existing_setup_keeps_licence_and_scientific_verification_gates(tmp_path):
    text = task(tmp_path, installation_mode="existing", discovery_report=report())
    assert "Read SKILL.md first" in text and "complete KDT loop" in text
    assert "The only successful outcome is a passing preflight" in text
    assert "If a licence, login, protected download, system privilege" in text
    assert "Do not pretend that blocked work passed" in text
    assert "placeholder scientific/model file" in text


def test_resume_message_default_retains_its_existing_contract(tmp_path):
    resumed = {"user_note": "Ready", "resume_hint": "Continue the blocked build"}
    expected = (
        "The user has completed the request you made.\n"
        "User note: Ready\nFiles supplied: []\nYour resume hint: Continue the blocked build\n"
        "Continue exactly where you stopped. Do not re-read the KI, re-run the diagnosis or "
        "repeat installation steps that already succeeded; verify only the step that was "
        "blocked, then finish the setup and run the KI preflight."
    )
    assert setup.resume_message(resumed, tmp_path) == expected


def test_resumed_existing_setup_receives_current_exact_path_without_discovery(tmp_path):
    selected = r"C:\Newly Selected\模型\model.exe"
    resumed = {"resume_hint": "Use the selected path"}
    text = setup.resume_task(resumed, tmp_path, installation_mode="existing", existing_paths=[selected])
    binding = json.JSONDecoder().raw_decode(text.split("[CURRENT SETUP BINDING]\n", 1)[1])[0]
    assert binding["installation_mode"] == "existing"
    assert binding["candidate_paths"] == [selected]
    assert binding["candidate_status"] == "unverified"
    assert "HOST DISCOVERY" not in text
    assert "supersedes any earlier setup mode or installation path" in text
    assert "Do not repeat a full-drive search" in text
    assert "Do not download, clone" in text
    assert "request one concrete installation directory or executable path" in text


def test_resumed_existing_setup_includes_current_discovery_limits(tmp_path):
    text = setup.resume_task({}, tmp_path, installation_mode="existing",
                             discovery_report=report("limited", reason="Entry limit reached"))
    assert facts_from(text)["state"] == "limited"
    assert facts_from(text)["reason"] == "Entry limit reached"
    assert "not proof of a usable installation" in text


@pytest.mark.parametrize("mode", ["existing", "new"])
def test_installation_only_resume_cannot_instruct_scientific_preflight(tmp_path, mode):
    text = setup.resume_task({}, tmp_path, installation_mode=mode, installation_only=True,
                             existing_paths=["C:/Models/Demo"], discovery_report=report())
    assert "then finish the setup and run the KI preflight" not in text
    assert "cheap executable startup or declared Python import probe" in text
    assert "Do NOT run the KI preflight, examples, reference cases, simulations" in text
    assert "calibration, data preparation, or result-generation tools" in text
    assert "Do NOT acquire scientific/project datasets" in text
    assert "Installation success is not scientific KI verification" in text
    assert "Do not bypass or auto-accept a licence" in text
    assert "status.json or installation-test.json" in text
    assert "Do not re-read the KI" in text


def test_resumed_new_mode_does_not_restore_old_discovery_or_candidate_paths(tmp_path):
    text = setup.resume_task({"resume_hint": "Continue the old install"}, tmp_path,
                             installation_mode="new", existing_paths=["C:/Old/External"],
                             discovery_report=report())
    binding = json.JSONDecoder().raw_decode(text.split("[CURRENT SETUP BINDING]\n", 1)[1])[0]
    assert binding["installation_mode"] == "new" and binding["candidate_paths"] == []
    assert "C:/Old/External" not in text and "HOST DISCOVERY" not in text
    assert "Install or build a new copy" in text
    assert "inside the configured setup workspace" in text
    assert "then finish the setup and run the KI preflight" in text
