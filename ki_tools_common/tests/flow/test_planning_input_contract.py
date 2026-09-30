"""Planning-prompt regressions, not model runs or proof of agent compliance.

Exercise the shared planning entry point with a real, small KI contract. These
tests intentionally need no provider, database credential, download or model.
"""
from __future__ import annotations

from copy import deepcopy

import pytest

from ki_tools_common.flow import contracts
from ki_tools_common.harness import ki_harness


@pytest.fixture
def planning_case(tmp_path, monkeypatch):
    monkeypatch.setenv("KI_HARNESS_FULL", "0")
    ki = tmp_path / "KI"
    (ki / "tools").mkdir(parents=True)
    (ki / "SKILL.md").write_text(
        "# Example KI\n> **MANDATORY EXECUTION POLICY**\n"
        "> Use the declared tools; never substitute a toy model.\n\n"
        "## Execution protocol\n"
        "Read docs/deck.md, prepare a deck, then run tools/run.py.\n",
        encoding="utf-8",
    )
    (ki / "dag.yaml").write_text(
        "inputs:\n- name: custom_deck\n  source_kind: user_provided\n"
        "outputs:\n- var: discharge\n  unit: m3/s\n",
        encoding="utf-8",
    )
    (ki / "tools" / "run.py").write_text(
        "raise RuntimeError('planning must never execute this tool')\n",
        encoding="utf-8",
    )
    (ki / "docs").mkdir()
    (ki / "docs" / "deck.md").write_text(
        "The deck contains user geometry and a coefficient with a documented default.\n",
        encoding="utf-8",
    )
    project = tmp_path / "project"
    plan = {
        "selected_kis": ["Example"],
        "ki_internal": {"Example": [{"name": "custom_deck"}]},
        "steps": [],
        "scientific_choices": [],
    }
    inventory = {"schema_version": "1.0", "items": []}
    return {"Example": ki}, plan, inventory, project


def test_existing_planning_mode_injects_shared_inspect_contract_without_writes(planning_case):
    kis, plan, inventory, project = planning_case
    before = deepcopy((plan, inventory))
    text = contracts.planning_block(kis, plan, inventory, project)
    shared = ki_harness.contract(kis["Example"], mode="inspect")
    assert shared in text
    assert "[KI HARNESS v1]" in text and "INSPECT mode" in text
    assert "do NOT run the model pipeline" in text
    assert "Do NOT prepare inputs, do NOT compile, do NOT download" in text
    assert "Approval and execution happen in a LATER, separate session" in text
    assert "never manufacture acquisition/approval files" in text.lower()
    assert (plan, inventory) == before
    assert not project.exists()


def test_inventory_review_includes_noncanonical_files_and_five_links(planning_case):
    text = contracts.planning_block(*planning_case)
    for evidence in (
        "Review ALL relevant declarations",
        "format specifications and linked preparation/workflow docs, including ki_internal",
        "not only the draft's existing rows",
        "Canonical vocabulary is a discovery aid, not an inclusion requirement",
        "Include applicable FILE and input-deck requirements",
        "requirement -> selected source or value -> actual/planned files -> preparation -> consuming step",
        "use the same inventory ID in that step's outputs and the consumer's inputs",
        "Do not merge inputs just because their labels or canonical quantities match",
    ):
        assert evidence in text
    assert "Do not mark inputs missing or needs_user by yourself" not in text
    assert "decides on the card whether" not in text


def test_defaults_and_presence_are_not_claimed_as_scientific_readiness(planning_case):
    text = contracts.planning_block(*planning_case)
    assert "cite the KI file/section declaring the value, method" in text
    assert "source_kind alone, a vocabulary match" in text
    assert "Mark an unknown source 'missing'" in text
    assert "needs_user means a real user decision/input is needed" in text
    assert "NOT that its scientific suitability is validated" in text
    assert "state checks that still need to run after approval" in text
    assert "with their producer/source and missing status until they exist" in text
    assert "not a full-document audit" in text
    assert "Do not rewrite both draft files" in text
    assert "before FINAL submission" in text
    assert "an example, not an applicable default for this project" in text
    assert "On EVERY interview turn" in text
    assert "Do NOT rebuild the full drafts before asking the next question" in text
    assert "FINALIZATION ONLY" in text


def test_scalar_guidance_uses_existing_choices_and_config_preparation(planning_case):
    text = contracts.planning_block(*planning_case)
    assert "file-based, not a scalar-value schema" in text
    assert "existing scientific_choices (picked and rationale)" in text
    assert "include that file and its KI-supported preparation step" in text
    assert "Never invent a local file to make a scalar 'ready'" in text
    assert "or fabricate a user decision. The host records approval" in text
    assert "a critical parameter SET as one coherent decision" in text
    assert "expand its individual values, units, origins and overrides" in text
    assert "do not ask the user about every coefficient separately" in text
    assert "never invent numerical defaults or mark a computed default ready" in text
    assert "to be computed during KI execution" in text


def test_three_phases_put_preprocessing_in_execution_after_acquisition(planning_case):
    text = contracts.planning_block(*planning_case)
    assert "[THREE PHASES]" in text
    assert "Planning settles the scientific choices with the user; no downloads or input preparation" in text
    assert "acquisition does download/import only" in text
    assert "KI execution then inspects the acquired files, preprocesses data" in text
    assert "parameter/config-file creation belong to KI execution AFTER acquisition" in text
    assert "File acquisition is not proof of model-ready input" in text
    assert "Manual links still require the user to supply the files" in text


def test_final_handoff_waits_for_settled_choices_and_preserves_prior_answers(planning_case):
    kis, plan, inventory, project = planning_case
    plan["scientific_choices"] = [{"id": "coefficients", "picked": "KI default set",
                                  "decision": "user's calibrated set"}]
    before = deepcopy((plan, inventory))
    text = contracts.planning_block(kis, plan, inventory, project)
    assert "Read prior answers and saved choices first: do not re-ask settled values" in text
    assert "or ask which KI when it is already selected" in text
    assert "the structured question and the host-recorded answer are the progress record" in text
    assert "Do NOT rebuild the full drafts before asking the next question" in text
    assert "Do not claim a final plan submission or say a question was issued before its handoff succeeds" in text
    assert "Once all required choices are settled, write BOTH" in text
    assert "downloads still wait for that approval" in text
    assert (plan, inventory) == before


@pytest.mark.parametrize("mode", ["off", "snapshot", "direct"])
def test_period_and_validation_are_separate_evidence_based_decisions(planning_case, mode):
    # The regression is missing instructions delivered to the agent, not a
    # claim that a provider will obey the contract without a live acceptance run.
    text = contracts.planning_block(*planning_case, database_access_mode=mode)
    for rule in (
        "[STUDY DESIGN — ONE DECISION]",
        "Ask the simulation period separately from the validation method/source",
        "Never bundle a date range and an evaluation dataset into one option",
        "A KI worked example is not a date-range recommendation",
        "Do not infer earliest/latest available years from an example",
        "requested period, forcing coverage, observation coverage and spin-up",
        "Offer a custom period",
        "do not silently shorten the simulation to the observation overlap",
        "national/regional statistics are not site-scale validation",
        "If coverage has not been checked, say it is unverified",
    ):
        assert rule in text


@pytest.mark.parametrize("mode", ["off", "disabled", "snapshot", "direct"])
def test_study_design_does_not_turn_database_metadata_into_consent(planning_case, mode):
    text = contracts.planning_block(*planning_case, database_access_mode=mode)
    assert "Offer GeoForge Database candidates only when the host says access is activated" in text
    assert "Public-source and user-provided alternatives remain valid without Database access" in text
    assert "Manual delivery does not change scientific coverage" in text
    assert "Do not fetch data to answer this question" in text


@pytest.mark.parametrize("database_mode,wrappers", [
    ("disabled", None),
    ("snapshot", None),
    ("direct", None),
    ("direct", {"obs_search": "geoforge obs-search"}),
])
def test_local_inputs_and_one_decision_apply_to_every_database_mode(
        planning_case, database_mode, wrappers):
    text = contracts.planning_block(
        *planning_case, database_access_mode=database_mode, wrappers=wrappers)
    assert "legitimate sources without GeoForge Database access" in text
    assert "Preserve the user's supplied files and chosen overrides" in text
    assert "Ask exactly ONE unresolved decision/question at a time, then STOP" in text
    assert "KI-supported recommended/default option with evidence" in text
    assert "if no applicable default is supported, say so rather than inventing a number" in text
    assert "Do not send a questionnaire or bundle unrelated decisions" in text
    assert "Do not send another request in the same turn" in text
    assert "ONE grouped summary" not in text
    assert "all relevant accessible candidates, not an arbitrary top-N shortlist" in text
    assert "Use available paging when needed" in text
    assert "disclose any incomplete search or inaccessible metadata" in text
    assert "they do not prove native variable names, file units, file contents or suitability" in text
    if database_mode == "disabled":
        assert "Database discovery is disabled" in text
        assert "Before asking the current dataset decision" not in text
    elif database_mode == "snapshot":
        assert "no live database query tool is available" in text
        assert "Inspect that file BEFORE asking the current dataset decision" in text
    else:
        assert "Respect user-supplied files and selections" in text
        assert "Manual delivery alone does not leave dataset selection unresolved" in text
        assert "inspect any provided cached GeoForge Database (Geo4DB) catalogue" in text
        assert "ONE current question, then stop" in text
        assert "do not silently turn a recommendation into consent" in text
        assert "describe_dataset then estimate_clip" in text
