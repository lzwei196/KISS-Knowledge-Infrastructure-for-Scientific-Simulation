"""Original model media are visible without copying or claiming scientific truth."""
import hashlib
import io
import json
import os
from http.client import HTTPMessage
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from kiss_cli import flowgate, gui, projectview


@pytest.fixture
def media(tmp_path):
    project = tmp_path / "project"
    output = project / "outputs" / "Model" / "fresh run"
    output.mkdir(parents=True)
    (output / "profile.png").write_bytes(b"fixture image bytes")
    (output / "series.csv").write_bytes(b"time,value\r\n1,2\r\n2,3\r\n")
    (output / "process.webm").write_bytes(b"fixture video bytes")
    return project, output


def _spec(relative, kind="image"):
    return {"version": 1, "panels": [{"id": "result", "kind": kind, "path": relative}]}


def test_automatic_view_and_inline_discovery_find_original_outputs(media):
    project, output = media
    before = {path: path.read_bytes() for path in output.iterdir()}
    view = projectview.load(project)
    assert view["available"] and not view["customized"]
    assert {panel["kind"] for panel in view["panels"]} == {"image", "table", "animation"}
    assert {panel["path"] for panel in view["panels"]} == {
        path.relative_to(project).as_posix() for path in before}
    for panel in view["panels"]:
        assert panel["evidence"] == "unvalidated"
        assert panel["file_provenance"]["scope"] == "technical-file-association"
    table = next(panel for panel in view["panels"] if panel["kind"] == "table")
    assert table["table"]["columns"] == ["time", "value"]
    assert table["table"]["rows"] == [["1", "2"], ["2", "3"]]
    assert list(gui._artifact_state(project)) == ["outputs/Model/fresh run/profile.png"]
    assert not (project / "artifacts").exists()
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize("filename,kind,mime", [("profile.png", "image", "image/png"),
    ("series.csv", "table", "text/csv; charset=utf-8"), ("process.webm", "animation", "video/webm")])
def test_published_panels_keep_original_media_and_safe_route(media, monkeypatch, filename, kind, mime):
    project, output = media
    path = output / filename
    relative = path.relative_to(project).as_posix()
    panel = projectview.publish(project, _spec(relative, kind))["panels"][0]
    assert panel["path"] == relative and panel["mime"] == mime
    assert panel["file_provenance"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(gui.sessions, "load", lambda *a: {"id": "b8b03523f587"})
    monkeypatch.setattr(gui.sessions, "project_path", lambda *a: project)
    actual, actual_mime = gui._resolve_project_view_asset(project.parent, "b8b03523f587", relative)
    assert actual == path and actual_mime == mime
    if kind == "image":
        assert gui._resolve_artifact(project.parent, "b8b03523f587", relative) == (path, mime)
    else:
        with pytest.raises(ValueError):
            gui._resolve_artifact(project.parent, "b8b03523f587", relative)


def test_existing_http_route_serves_output_image_with_sandbox(media, monkeypatch):
    project, output = media
    monkeypatch.setattr(gui.sessions, "load", lambda *a: {"id": "b8b03523f587"})
    monkeypatch.setattr(gui.sessions, "project_path", lambda *a: project)
    handler = object.__new__(gui.Handler)
    handler.headers = HTTPMessage()
    handler.workroot = project.parent
    handler.server = SimpleNamespace(server_port=12345)
    handler.csrf_token = "isolated-fixture"
    handler.path = "/api/session/b8b03523f587/artifact?path=outputs%2FModel%2Ffresh%20run%2Fprofile.png"
    handler.wfile = io.BytesIO()
    codes, headers = [], {}
    handler.send_response = codes.append
    handler.send_header = lambda key, value: headers.update({key: value})
    handler.end_headers = lambda: None
    handler.do_GET()
    assert codes == [200] and handler.wfile.getvalue() == (output / "profile.png").read_bytes()
    assert headers["Content-Type"] == "image/png" and headers["X-Content-Type-Options"] == "nosniff"
    assert "sandbox" in headers["Content-Security-Policy"]


@pytest.mark.parametrize("relative", ["outputs/../secret.png", "outputs/.private/image.png",
    "outputs//image.png", "outputs/a/./image.png", "outputs/trailing /image.png",
    "outputs/image.png:stream", "outputs\\image.png", "C:/private.png", "runs/secret.png",
    "models/KI/private.png", "outputs/image.svg", "outputs/result.html", "outputs/result.py",
    "outputs/model.gltf", "outputs/document.pdf"])
def test_output_media_do_not_expand_private_or_active_file_scope(media, relative):
    project, _ = media
    with pytest.raises((ValueError, OSError)):
        projectview.resolve_asset(project, relative)
    with pytest.raises((ValueError, OSError)):
        projectview.publish(project, _spec(relative))


@pytest.mark.parametrize("alias", ["file", "directory", "output_root", "hardlink"])
def test_output_aliases_are_neither_discovered_nor_served(media, tmp_path, alias):
    project, _ = media
    external = tmp_path / "private"; external.mkdir()
    secret = external / "secret.png"; secret.write_bytes(b"private bytes")
    relative = "outputs/linked/secret.png"
    try:
        if alias == "hardlink":
            relative = "outputs/secret.png"; os.link(secret, project / relative)
        elif alias == "file":
            relative = "outputs/secret.png"; (project / relative).symlink_to(secret)
        elif alias == "directory":
            (project / "outputs/linked").symlink_to(external, target_is_directory=True)
        else:
            project = tmp_path / "another-project"; project.mkdir()
            (project / "outputs").symlink_to(external, target_is_directory=True)
            relative = "outputs/secret.png"
    except OSError as error:
        pytest.skip(f"Host cannot create this alias fixture: {error}")
    with pytest.raises(ValueError):
        projectview.resolve_asset(project, relative)
    assert relative not in {panel["path"] for panel in projectview.load(project)["panels"]}
    assert relative not in gui._artifact_state(project)


def test_output_size_limit_applies_to_discovery_and_download(media, monkeypatch):
    project, _ = media
    monkeypatch.setattr(projectview, "MAX_ASSET_BYTES", 1)
    assert not projectview.load(project)["panels"]
    with pytest.raises(ValueError, match="larger"):
        projectview.resolve_asset(project, "outputs/Model/fresh run/profile.png")


def test_shipped_chat_renderer_displays_output_png_but_keeps_forbidden_paths_literal():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required for shipped Markdown renderer")
    source = (Path(__file__).parents[1] / "kiss_cli/web/app.html").read_text(encoding="utf-8")
    image = source[source.index("function artifactImage("):source.index("const TOOL_LABELS=")]
    markdown = source[source.index("function renderMarkdownTables("):source.index("let SESSIONS=[]")]
    program = r'''const CUR={id:"fixture"}; const extractWork=t=>({body:t,html:""});
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
''' + image + markdown + r'''
const paths=JSON.parse(require('fs').readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify(paths.map(path=>md('![<script>bad</script>]('+path+')','a/b?c'))));'''
    paths = ["outputs/Model/fresh run/profile.png", "artifacts/legacy.svg", "outputs/image.svg",
             "outputs/../secret.png", "outputs/.private/secret.png", "https://example.com/image.png"]
    result = subprocess.run([node, "-e", program], input=json.dumps(paths), capture_output=True,
                            text=True, encoding="utf-8", check=True, timeout=10)
    rendered = json.loads(result.stdout)
    assert all('<img ' in item and '<script>' not in item for item in rendered[:2])
    assert all('<img ' not in item for item in rendered[2:])
    assert '/api/session/a%2Fb%3Fc/artifact?path=outputs%2FModel%2Ffresh%20run%2Fprofile.png' in rendered[0]


@pytest.mark.parametrize("change", [None, "bytes", "later_failure", "approval", "plan", "inventory"])
def test_output_media_association_uses_current_exact_receipt(media, tmp_path, monkeypatch, change):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    project, output = media
    path = output / "profile.png"
    ki = tmp_path / "ki"; (ki / "tools").mkdir(parents=True)
    tool = ki / "tools/read.py"; tool.write_text("raise AssertionError('not executed')")
    fs = flowgate.FlowSession.open(project, {"Demo": ki})
    fs.move("task_received"); fs.move("kis_resolved", {"selected_kis": ["Demo"]})
    step = {"id": "Demo:plot", "ki": "Demo", "kind": "check", "tool": str(tool),
            "command": [], "cwd": ".", "inputs": [], "outputs": ["plot"], "status": "planned"}
    plan = {"schema_version": "1.0", "goal": "Display fixture", "created_at": "fixture",
            "selected_kis": ["Demo"], "scientific_choices": [], "unresolved_questions": [], "steps": [step]}
    inventory = {"schema_version": "1.0", "items": [{"id": "plot", "required_by": ["Demo"],
        "status": "resolved", "acceptable_sources": [], "local_paths": [path.relative_to(project).as_posix()],
        "agent_resolvable": True, "needs_user": False}]}
    assert fs.write_plan(plan, inventory) == []
    flow = fs.flow
    flow.approval.approve(project, by="user")
    def record(finished=2, passed=True):
        from ki_tools_common.flow import declared_outputs
        return flow.receipts.record_run(project, ki="Demo", executable=str(tool), command=[str(tool)],
            cwd=str(project), started_at=finished-1, finished_at=finished, exit_code=0 if passed else 1,
            execution_status="succeeded" if passed else "failed", process_started=True, inputs=[], outputs=[path],
            approval_sha256=flow.approval.approval_id(flow.approval.read(project)), plan_step_id=step["id"],
            validation={"status": "passed" if passed else "failed", "checks": []},
            declared_outputs=declared_outputs.binding(project, step, inventory))
    record()
    if change == "bytes": path.write_bytes(b"changed bytes")
    elif change == "later_failure": record(5, False)
    elif change == "approval": flow.approval.approve(project, by="user")
    elif change in {"plan", "inventory"}:
        target = project / "runs" / ("plan.json" if change == "plan" else "data-inventory.json")
        document = json.loads(target.read_text(encoding="utf-8"))
        document["unapproved_change"] = True
        target.write_text(json.dumps(document), encoding="utf-8")
    panel = next(item for item in projectview.load(project)["panels"] if item["path"].endswith("profile.png"))
    assert panel["evidence"] == ("receipt_bound" if change is None else "unvalidated")
    assert "verified" not in panel["evidence"]
