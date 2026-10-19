"""Tiny public files and signed receipts only: no model, real network or live profile."""
import io
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import api, cli, flowgate, flowrun
from .test_flowgate import _ki, _cfg, _session, _review_plan, _approved_fetch_session

flowgate.load()
from ki_tools_common.flow import public_downloads as downloads


@pytest.fixture(autouse=True)
def isolated_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.setenv("GEOFORGE_FLOW_REGISTRY", str(tmp_path / "registry"))


def public_session(tmp_path, monkeypatch, count=5):
    ki = _ki(tmp_path)
    project, fs = _session(tmp_path, ki, [("task_received", None),
                          ("kis_resolved", {"selected_kis": ["M"]})])
    plan, inv = _review_plan(ki, [])
    plan["steps"] = [{"id": "download", "ki": "M", "kind": "download", "tool": None,
                      "inputs": [], "outputs": [f"table_{i}" for i in range(count)], "status": "planned"}]
    inv["items"] = [{"id": f"table_{i}", "status": "missing", "required_by": ["M"],
                     "acceptable_sources": [f"https://example.test/{i}.TBL"],
                     **downloads.target(f"table_{i}", f"https://example.test/{i}.TBL")["inventory"],
                     "needs_user": False, "agent_resolvable": True} for i in range(count)]
    calls = []
    class Response(io.BytesIO):
        status = 200
        url = "https://redirect.example.test/ignored-filename.bin"
    def open_url(req, **kwargs):
        calls.append(req.full_url)
        return Response(req.full_url.encode())
    monkeypatch.setattr("urllib.request.urlopen", open_url)
    return project, fs, ki, plan, inv, calls


def approve(fs, project, plan, inv):
    assert fs.write_plan(plan, inv) == []
    fs.flow.approval.approve(project, by="auto")
    fs.reload_artifacts()


@pytest.mark.parametrize("ident,url,filename,path", [
    ("table_a", "https://example.test/a.TBL", None, "inputs/raw/table_a/a.TBL"),
    ("a b", "https://example.test/x", "a b.TBL", "inputs/raw/a_b/a_b.TBL"),
    ("item", "https://example.test/", None, "inputs/raw/item/download.bin"),
    ("item", "https://example.test/a?name=b", None, "inputs/raw/item/a"),
    ("item", "https://example.test/a#b", "exact.TBL", "inputs/raw/item/exact.TBL"),
])
def test_exact_pure_target(ident, url, filename, path, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_k: pytest.fail("network"))
    assert downloads.target(ident, url, filename)["path"] == path
    assert downloads.target(ident, url, filename)["grants_readiness"] is False


@pytest.mark.parametrize("ident,url,filename", [
    ("..", "https://example.test/x", None), ("CON", "https://example.test/x", None),
    ("x", "file:///etc/passwd", None), ("x", "https://user:pass@example.test/x", None),
    ("x", "https://example.test/x", ".."), ("x", "https://example.test/x", "NUL.txt"),
    ("x", "http://", None), ("x", None, None), ([], "https://example.test/x", None),
])
def test_invalid_target_rejected(ident, url, filename):
    with pytest.raises(ValueError):
        downloads.target(ident, url, filename)


def test_actual_grouped_five_file_shape_rejected_before_plan_write(tmp_path, monkeypatch):
    project, fs, ki, plan, inv, calls = public_session(tmp_path, monkeypatch)
    plan["steps"][0]["outputs"] = ["tables"]
    inv["items"] = [{**inv["items"][0], "id": "tables",
                     "acceptable_sources": [i["chosen_source"] for i in inv["items"]],
                     "chosen_source": "download all five from manifest",
                     "local_paths": [f"inputs/raw/wrong/{i}.TBL" for i in range(5)]}]
    errors = fs.write_plan(plan, inv)
    assert any("one file per item" in e and "inputs/raw/tables/" in e for e in errors)
    assert not (project / "runs/plan.json").exists() and calls == []


def test_wrong_future_parent_rejected_in_review_and_execution(tmp_path, monkeypatch):
    project, fs, ki, plan, inv, _ = public_session(tmp_path, monkeypatch, 1)
    inv["items"][0]["local_paths"] = ["inputs/raw/wrong/0.TBL"]
    for mode in ("for_review", "for_execution"):
        errors = fs.flow.plan.validate(plan, inv, ["M"], {"M": ki.root}, project=project, **{mode: True})
        assert any("host download target 'inputs/raw/table_0/0.TBL'" in e for e in errors)


@pytest.mark.parametrize("delivery", ["served", "subset", "manual"])
def test_database_multi_file_contract_is_not_reinterpreted(tmp_path, monkeypatch, delivery):
    _, _, _, plan, inv, _ = public_session(tmp_path, monkeypatch, 1)
    inv["items"][0].update(delivery=delivery, dataset_id="database-id", chosen_source="database-id",
                           local_paths=["inputs/extracted/a", "inputs/extracted/b"])
    assert downloads.plan_errors(plan, inv) == []


def test_data_ki_step_not_reinterpreted(tmp_path, monkeypatch):
    _, _, _, plan, inv, _ = public_session(tmp_path, monkeypatch, 1)
    plan["steps"][0].update(kind="prepare", tool="/KI/tools/fetch.py")
    inv["items"][0]["local_paths"] = ["outputs/data/a", "outputs/data/b"]
    assert downloads.plan_errors(plan, inv) == []


@pytest.mark.parametrize("names", [("a b", "a_b"), ("TABLE", "table"), ("x" * 80 + "a", "x" * 80 + "b")])
def test_portable_sanitized_target_collision_rejected(tmp_path, monkeypatch, names):
    _, _, _, plan, inv, _ = public_session(tmp_path, monkeypatch, 2)
    for index, (item, ident) in enumerate(zip(inv["items"], names)):
        item.update(id=ident, **downloads.target(ident, f"https://example.test/{index}.TBL")["inventory"])
    plan["steps"][0]["outputs"] = [i["id"] for i in inv["items"]]
    assert any("same portable target" in e for e in downloads.plan_errors(plan, inv))


def test_five_receipts_are_required_and_each_remains_current(tmp_path, monkeypatch):
    project, fs, _, plan, inv, calls = public_session(tmp_path, monkeypatch)
    approve(fs, project, plan, inv)
    paths = []
    for i, item in enumerate(inv["items"]):
        result = fs.fetch(item["chosen_source"], item["id"], plan_step_id="download")
        assert result["path"] == item["local_paths"][0]
        paths.append(Path(result["receipt"]))
        assert ("download" in fs.evidence()["steps_passed"]) is (i == 4)
    assert len(set(paths)) == 5 and len(calls) == 5
    for path, item in zip(paths, inv["items"]):
        receipt = json.loads(path.read_text())
        assert fs.flow.receipts.verify(project, receipt)
        assert receipt["request_url"] == item["chosen_source"]
    (project / inv["items"][0]["local_paths"][0]).write_bytes(b"changed")
    assert "download" not in fs.evidence()["steps_passed"]


@pytest.mark.parametrize("field,value", [("url", "https://example.test/alternate"),
                                        ("filename", "other.TBL"), ("plan_step_id", "other")])
def test_request_cannot_diverge_from_approved_target(tmp_path, monkeypatch, field, value):
    project, fs, _, plan, inv, calls = public_session(tmp_path, monkeypatch, 1)
    approve(fs, project, plan, inv)
    args = dict(url=inv["items"][0]["chosen_source"], item_id="table_0", plan_step_id="download")
    args[field] = value
    with pytest.raises(flowgate.FlowDenied):
        fs.fetch(**args)
    assert not calls


def test_same_request_retry_keeps_filename_and_failed_retry_preserves_old_bytes(tmp_path, monkeypatch):
    project, fs, _, plan, inv, calls = public_session(tmp_path, monkeypatch, 1)
    inv["items"][0]["local_paths"] = ["inputs/raw/table_0/custom.TBL"]
    approve(fs, project, plan, inv)
    first = fs.fetch(inv["items"][0]["chosen_source"], "table_0", plan_step_id="download")
    receipt = Path(first["receipt"]); before = receipt.read_bytes(); dest = project / first["path"]
    with pytest.raises(flowgate.FlowDenied, match="exceeds"):
        fs.fetch(inv["items"][0]["chosen_source"], "table_0", plan_step_id="download", max_bytes=1)
    assert receipt.read_bytes() == before and dest.read_bytes() == inv["items"][0]["chosen_source"].encode()
    assert not list(dest.parent.glob("*.part"))
    again = fs.fetch(inv["items"][0]["chosen_source"], "table_0", plan_step_id="download")
    assert again["path"] == first["path"] and "download" in fs.evidence()["steps_passed"]


@pytest.mark.parametrize("change", ["url", "filename", "unsigned"])
def test_legacy_same_item_cannot_silently_replace_another_receipt(tmp_path, monkeypatch, change):
    project, fs, calls = _approved_fetch_session(tmp_path, monkeypatch)
    first = fs.fetch("https://example.test/a", "forcing", filename="a.TBL")
    receipt = Path(first["receipt"])
    if change == "unsigned":
        doc = json.loads(receipt.read_text()); doc.pop("signature"); receipt.write_text(json.dumps(doc))
    before = receipt.read_bytes(); old_bytes = (project / first["path"]).read_bytes(); before_calls = len(calls)
    with pytest.raises(flowgate.FlowDenied, match="existing download evidence"):
        fs.fetch("https://example.test/b" if change == "url" else "https://example.test/a",
                 "forcing", filename="b.TBL" if change == "filename" else "a.TBL")
    assert receipt.read_bytes() == before and (project / first["path"]).read_bytes() == old_bytes
    assert len(calls) == before_calls


def test_api_and_cli_planning_query_use_same_pure_contract(tmp_path, monkeypatch, capsys):
    project, fs, ki, _, _, calls = public_session(tmp_path, monkeypatch, 1)
    before = sorted(p.relative_to(project).as_posix() for p in project.rglob("*"))
    names = {t["name"] for t in api.tool_schemas(ki, project_mode=True, flow=fs)}
    assert "describe_download_target" in names and "fetch_data" not in names
    args = {"item_id": "table", "url": "https://example.test/source", "filename": "x.TBL"}
    result = json.loads(api.execute_tool("describe_download_target", args, ki, _cfg(project), project_mode=True, flow=fs))
    assert cli.cmd_download_target(SimpleNamespace(item=args["item_id"], url=args["url"], filename=args["filename"])) == 0
    assert json.loads(capsys.readouterr().out) == result
    assert before == sorted(p.relative_to(project).as_posix() for p in project.rglob("*")) and calls == []
    with pytest.raises(api.ToolError):
        api.execute_tool("describe_download_target", {**args, "destination": "outside"}, ki, _cfg(project), project_mode=True, flow=fs)


def test_cli_planning_permission_is_only_query_not_download(tmp_path):
    policy = flowgate.load().policy
    tools = policy._claude_planning_tools(tmp_path, {}, "python", {
        "download_target": "geoforge download-target", "fetch": "geoforge fetch"})
    assert "Bash(geoforge download-target:*)" in tools
    assert "Bash(geoforge fetch:*)" not in tools
    text = flowgate.load().contracts._PLAN_SCHEMA_NOTE
    assert "one inventory item per required file" in text
