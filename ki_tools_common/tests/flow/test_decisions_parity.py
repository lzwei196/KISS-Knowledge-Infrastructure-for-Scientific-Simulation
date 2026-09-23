"""The shared schema must stay identical to the web chat's deployed one.

`flow.decisions` was ported from backend/services/flow_decisions.py (deployed 2026-09-15). The
web keeps its own module because the records live in the app DB and the simulation gate hook
loads that file by path under an isolated interpreter. This test is the anti-fork guard: when
the server tree is present, the two implementations must answer identically. It skips on a
desktop machine, exactly like test_bundled_harness does for the harness copy.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

from ki_tools_common.flow import decisions

WEB = Path("/mnt/disk1/Hydrocraft_server/Hydrocraft/hydrocraft-web/backend/services/flow_decisions.py")

RECORDS = [
    {}, {"input_id": "f"}, {"input_id": "f", "value": "x"},
    {"input_id": "forcing", "source": "user", "value": "CMFD"},
    {"input_id": "forcing", "source": "ki_default", "value": "the KI prepares it"},
    {"input_id": "forcing", "source": "open", "value": "which forcing?"},
    {"input_id": " forcing", "source": "user", "value": "x"},
    {"input_id": "forcing ", "source": "user", "value": "x"},
    {"input_id": "", "source": "user", "value": "x"},
    {"input_id": "f", "source": "USER", "value": "x"},
    {"input_id": "f", "source": "agent", "value": "x"},
    {"input_id": "f", "source": "user", "value": None},
    {"input_id": "f", "source": "user", "value": "   "},
    {"input_id": "f", "source": "user", "value": []},
    {"input_id": "f", "source": "user", "value": 0},
    {"input_id": "f", "source": "user", "value": False},
    {"input_id": "site", "source": "user", "value": {"lat": 32.9, "lon": 117.4}},
    {"input_id": "SITE", "source": "user", "value": {"lat": 32.9, "lon": 117.4}},
    {"input_id": "site", "source": "user", "value": {"lat": 91, "lon": 0}},
    {"input_id": "site", "source": "user", "value": {"lat": 0, "lon": 181}},
    {"input_id": "site", "source": "user", "value": {"lat": "x", "lon": 1}},
    {"input_id": "site", "source": "user", "value": {"location_name": "Bengbu"}},
    {"input_id": "site", "source": "user", "value": {"location_name": "  "}},
    {"input_id": "site", "source": "user", "value": "Bengbu"},
    {"input_id": "site", "source": "open", "value": "which basin?"},
    {"input_id": "period", "source": "user", "value": {"start_year": 2003, "end_year": 2005}},
    {"input_id": "period", "source": "user", "value": {"start_year": 2005, "end_year": 2003}},
    {"input_id": "period", "source": "user", "value": {"start_year": 1800, "end_year": 2005}},
    {"input_id": "period", "source": "user", "value": {"start_year": "2003", "end_year": "2005"}},
    {"input_id": "period", "source": "ki_default", "value": {"start_year": "x", "end_year": 2005}},
    {"input_id": "period", "source": "open", "value": "which years?"},
    {"input_id": "f", "source": "user", "value": {"a": 1}, "rationale": "r", "user_quote": "q"},
]

ROW_SETS = [
    [(1, "decision_pinned", {"input_id": "f", "source": "user", "value": "A"}),
     (2, "decision_pinned", {"input_id": "f", "source": "user", "value": "B"})],
    [(1, "decision_pinned", {"input_id": "f", "source": "user", "value": "A"}),
     (2, "decision_pinned", {"input_id": "f", "source": "bad", "value": "B"})],
    [(1, "decision_pinned", {"input_id": "f", "source": "user", "value": "A"}),
     (2, "decision_pinned", {"input_id": "g", "source": "open", "value": "?"}),
     (3, "decision_superseded", {"supersedes_event_id": 1})],
    [(1, "decision_pinned", {"input_id": "f", "source": "user", "value": "A"}),
     (2, "decision_pinned", {"input_id": "f", "source": "user", "value": "B"}),
     (3, "decision_superseded", {"supersedes_event_id": 1})],
    [(1, "decision_pinned", {"input_id": "f", "source": "user", "value": "A"}),
     (2, "decision_superseded", {"input_id": "F"})],
    [(1, "decision_superseded", {"supersedes_event_id": 99})],
    [(1, "decision_pinned", '{"input_id": "f", "source": "user", "value": "json-text"}')],
    [(1, "decision_pinned", "not json at all")],
    [],
]


def _web():
    if not WEB.is_file():
        pytest.skip("server tree not present (desktop machine)")
    spec = importlib.util.spec_from_file_location("_web_flow_decisions_parity", WEB)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_web_flow_decisions_parity"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_the_two_schemas_answer_identically():
    web = _web()
    assert decisions.SOURCES == web.SOURCES and decisions.SCOPE_IDS == web.SCOPE_IDS
    for rec in RECORDS:
        assert decisions.validate_record(rec) == web.validate_record(rec), rec
        assert decisions.is_input_record(rec) == web.is_input_record(rec), rec


def test_the_two_folds_and_revisions_agree():
    web = _web()
    slim = lambda eff: {k: (v["source"], v["value"], v.get("event_id")) for k, v in eff.items()}
    for rows in ROW_SETS:
        ours, theirs = decisions.fold_rows(rows), web.fold_rows(rows)
        assert slim(ours) == slim(theirs), rows
        assert decisions.revision_of(ours) == web.revision_of(theirs), rows
