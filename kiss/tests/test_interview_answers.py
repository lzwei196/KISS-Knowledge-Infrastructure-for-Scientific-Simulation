"""Issue #3: interview answers are recorded host-side, fed back to planning and credited at signing.

Reproduced 2026-09-28: the user picked "5 years" spin-up in the interview, yet approval signed it
as a KI protocol default and the execution turn was told "the user was not asked about these".
"""
from __future__ import annotations

import json

from kiss_cli import flowrun, plan_review


def _question(qid="q1", title="How long should the spin-up be?"):
    return {"id": qid, "kind": "choice", "status": "waiting", "title": title,
            "options": [{"id": "ki-default", "label": "1 year (KI default)"},
                        {"id": "five", "label": "5 years"}]}


def test_an_option_click_is_saved_in_the_answer_store(tmp_path):
    plan_review.record_interview_answer(tmp_path, _question(), {"id": "five", "label": "5 years"})
    rec = plan_review.load_user_answers(tmp_path)["interview:q1"]
    assert rec["value"] == "5 years"
    assert rec["question"] == "How long should the spin-up be?"


def test_a_custom_answer_is_saved_verbatim_with_its_note(tmp_path):
    plan_review.record_interview_answer(
        tmp_path, _question("q2", "Study period?"),
        {"id": "__custom_answer__", "label": "Custom answer", "response": "2003–2005"})
    assert plan_review.load_user_answers(tmp_path)["interview:q2"]["value"] == "2003–2005"


def test_an_option_note_survives_in_settled_answers_and_signed_provenance(tmp_path):
    plan_review.record_interview_answer(
        tmp_path, _question(), {"id": "five", "label": "5 years"},
        note="Use the same forcing cycle each year")
    answers = plan_review.load_user_answers(tmp_path)
    assert answers["interview:q1"]["note"] == "Use the same forcing cycle each year"
    assert "Use the same forcing cycle each year" in plan_review.settled_answers_block(tmp_path)
    records, _ = plan_review.decision_records(flowrun._flow(), _spinup_plan(), {"items": []}, answers)
    assert "Use the same forcing cycle each year" in records["choice:spinup"]["rationale"]


def test_interview_answers_survive_approval_card_writes(tmp_path):
    plan_review.record_interview_answer(tmp_path, _question(), {"id": "five", "label": "5 years"})
    plan_review.record_user_answers(tmp_path, {"suggested": {"c": "a"}, "options": {"c": ["a", "b"]}},
                                    {"c": "b"})
    answers = plan_review.load_user_answers(tmp_path)
    assert answers["interview:q1"]["value"] == "5 years" and answers["choice:c"]["value"] == "b"


def test_every_answer_reaches_the_planning_prompt_however_long_the_interview(tmp_path):
    for n in range(12):     # more than the 20-message chat window holds as Q/A pairs
        plan_review.record_interview_answer(tmp_path, _question(f"q{n}", f"Question {n}?"),
                                            {"id": "x", "label": f"answer {n}"})
    block = plan_review.settled_answers_block(tmp_path)
    assert "[ANSWERS THE USER ALREADY GAVE" in block
    for n in range(12):
        assert f"interview:q{n} — Question {n}? → answer {n}" in block
    assert plan_review.settled_answers_block(tmp_path / "empty") == ""


def test_an_unreadable_store_is_named_in_the_prompt_not_hidden(tmp_path):
    p = tmp_path / ".geoforge" / "user-answers.json"
    p.parent.mkdir()
    p.write_text("{broken", encoding="utf-8")
    assert "cannot be read" in plan_review.settled_answers_block(tmp_path)


def _spinup_plan(cited="interview:q1", decision="5 years"):
    return {"scientific_choices": [{"id": "spinup", "kind": "spin-up", "options": ["1 year", "5 years"],
                                    "decision": decision, "high_impact": True, "answered_by": cited}]}


def test_a_choice_citing_a_real_answer_is_signed_as_the_users(tmp_path):
    plan_review.record_interview_answer(tmp_path, _question(), {"id": "five", "label": "5 years"})
    recs, invalid = plan_review.decision_records(flowrun._flow(), _spinup_plan(), {"items": []},
                                                 plan_review.load_user_answers(tmp_path))
    assert not invalid
    rec = recs["choice:spinup"]
    assert rec["source"] == "user" and rec["value"] == "5 years"
    assert "How long should the spin-up be?" in rec["rationale"] and "5 years" in rec["rationale"]


def test_a_citation_of_an_answer_the_user_never_gave_is_not_credited(tmp_path):
    recs, _ = plan_review.decision_records(flowrun._flow(), _spinup_plan("interview:made-up"),
                                           {"items": []}, {})
    assert recs["choice:spinup"]["source"] == "ki_default"


def test_a_citation_must_name_an_interview_answer_not_an_approval_pick(tmp_path):
    recs, _ = plan_review.decision_records(flowrun._flow(), _spinup_plan("choice:other"), {"items": []},
                                           {"choice:other": {"value": "5 years"}})
    assert recs["choice:spinup"]["source"] == "ki_default"


def test_the_card_shows_which_answer_a_choice_came_from(tmp_path):
    plan_review.record_interview_answer(tmp_path, _question(), {"id": "five", "label": "5 years"})
    cited = plan_review.cited_answers(_spinup_plan(), plan_review.load_user_answers(tmp_path))
    assert cited == {"spinup": "How long should the spin-up be? → 5 years"}
    assert plan_review.cited_answers(_spinup_plan("interview:nope"), {}) == {}


def test_the_planning_turn_carries_the_settled_answers(tmp_path, monkeypatch):
    """The block is appended in flowrun.turn's planning branch (source check: turn needs a live KI)."""
    import inspect
    src = inspect.getsource(flowrun.turn)
    assert "plan_review.settled_answers_block(project)" in src


def test_stored_file_is_plain_json(tmp_path):
    plan_review.record_interview_answer(tmp_path, _question(), {"id": "five", "label": "5 years"})
    doc = json.loads((tmp_path / ".geoforge" / "user-answers.json").read_text(encoding="utf-8"))
    assert doc["schema"] == 1 and "interview:q1" in doc["answers"]
