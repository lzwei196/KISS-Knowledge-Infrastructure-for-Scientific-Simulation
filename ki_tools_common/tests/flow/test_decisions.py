"""flow.decisions — the one decision schema shared by the web chat and the desktop."""
import pytest

from ki_tools_common.flow import decisions


def test_schema_accepts_the_three_sources_and_refuses_everything_else():
    for src in decisions.SOURCES:
        ok, why = decisions.validate_record({"input_id": "forcing", "source": src, "value": "CMFD"})
        assert ok, why
    for bad in ({}, {"input_id": "f", "value": "x"}, {"input_id": "f", "source": "USER", "value": "x"},
                {"input_id": " f", "source": "user", "value": "x"}, {"input_id": "f", "source": "user"},
                {"input_id": "f", "source": "user", "value": ""}, {"input_id": "f", "source": "user", "value": {}}):
        ok, why = decisions.validate_record(bad)
        assert not ok and why


@pytest.mark.parametrize("value,ok", [
    ({"lat": 32.9, "lon": 117.4}, True), ({"location_name": "Bengbu"}, True),
    ({"lat": 99, "lon": 0}, False), ({"lat": "x", "lon": 1}, False), ({}, False)])
def test_site_needs_a_real_point_or_a_name(value, ok):
    assert decisions.validate_record({"input_id": "site", "source": "user", "value": value})[0] is ok


@pytest.mark.parametrize("value,ok", [
    ({"start_year": 2003, "end_year": 2005}, True), ({"start_year": 2005, "end_year": 2003}, False),
    ({"start_year": 1800, "end_year": 2005}, False), ({"start_year": "x", "end_year": 2005}, False)])
def test_period_years_must_be_plausible_and_ordered(value, ok):
    assert decisions.validate_record({"input_id": "period", "source": "user", "value": value})[0] is ok


def test_the_last_valid_record_per_input_wins_and_malformed_rows_never_block_it():
    rows = [(1, "decision_pinned", {"input_id": "f", "source": "user", "value": "A"}),
            (2, "decision_pinned", {"input_id": "f", "source": "nope", "value": "junk"}),
            (3, "decision_pinned", {"input_id": "f", "source": "user", "value": "B"})]
    eff = decisions.fold_rows(rows)
    assert eff["f"]["value"] == "B" and eff["f"]["event_id"] == 3


def test_supersession_retires_only_the_named_event():
    rows = [(1, "decision_pinned", {"input_id": "f", "source": "user", "value": "A"}),
            (2, "decision_pinned", {"input_id": "g", "source": "user", "value": "G"}),
            (3, "decision_superseded", {"supersedes_event_id": 2})]
    eff = decisions.fold_rows(rows)
    assert "g" not in eff and eff["f"]["value"] == "A"
    rows.append((4, "decision_superseded", {"input_id": "F"}))
    assert decisions.fold_rows(rows) == {}


def test_revision_follows_source_and_value_only():
    a = decisions.fold_payloads([{"input_id": "f", "source": "user", "value": "A", "rationale": "because"}])
    b = decisions.fold_payloads([{"input_id": "f", "source": "user", "value": "A", "rationale": "other"}])
    c = decisions.fold_payloads([{"input_id": "f", "source": "ki_default", "value": "A"}])
    assert decisions.revision_of(a) == decisions.revision_of(b)
    assert decisions.revision_of(a) != decisions.revision_of(c)
    assert len(decisions.revision_of(a)) == 16


def test_open_inputs_are_listed_by_name():
    eff = decisions.fold_payloads([{"input_id": "forcing", "source": "user", "value": "CMFD"},
                                   {"input_id": "gauge", "source": "open", "value": "which gauge?"}])
    assert decisions.open_inputs(eff) == ["gauge"]
    assert decisions.open_inputs({}) == []
