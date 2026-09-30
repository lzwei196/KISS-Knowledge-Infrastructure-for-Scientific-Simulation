"""Named project creation and read-only previews, with no provider or server."""
from __future__ import annotations

import io
import json
from pathlib import Path
from urllib.parse import urlencode

import pytest

from kiss_cli import flowrun, gui, sessions


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.setenv("GEOFORGE_FLOW_REGISTRY", str(tmp_path / "registry.json"))
    monkeypatch.setattr(gui.settings, "load", lambda: {})


def handler(workroot, route, payload=None):
    instance = object.__new__(gui.Handler)
    instance.workroot = workroot
    instance.path = route
    encoded = json.dumps(payload or {}).encode()
    instance.headers = {"Content-Length": str(len(encoded))}
    instance.rfile = io.BytesIO(encoded)
    instance._browser_write_allowed = lambda: (True, "")
    responses = []
    instance._json = lambda body, status=200: responses.append((body, status))
    return instance, responses


def test_default_location_preview_creates_nothing(tmp_path, monkeypatch):
    stamp = 1750000000
    monkeypatch.setattr(sessions.time, "time", lambda: stamp)
    workroot = tmp_path / "missing" / "app"
    result = sessions.project_location(workroot)
    assert result["project_name"] == "Project " + sessions.time.strftime(
        "%Y-%m-%d %H%M%S", sessions.time.localtime(stamp))
    assert result["default_parent"] == result["project_parent"] == str(workroot / "projects")
    assert result["creates_child_folder"] is True
    assert result["project_path_preview"].endswith("--{id}")
    assert not workroot.parent.exists()


def test_explicit_name_preview_matches_creation_with_missing_external_parent(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions.time, "time", lambda: 1750000000)
    workroot, parent = tmp_path / "app", tmp_path / "new" / "research"
    name = "  华北平原 VIC + CaMa  "
    preview = sessions.project_location(workroot, name, parent)
    assert not parent.exists() and not workroot.exists()
    session = sessions.create(workroot, ["VIC", "CaMa-Flood"], "cli:kimi",
                              project_parent=parent, project_name=name)
    project = sessions.project_path(workroot, session)
    assert session["project_name"] == session["title"] == name.strip()
    assert session["project_named"] is True
    assert project == Path(preview["project_path_preview"].replace("{id}", session["id"]))
    assert project.parent == parent.resolve()
    assert (project / "inputs" / "uploads").is_dir()
    assert (project / "README.md").read_text(encoding="utf-8").startswith(f"# {name.strip()}\n")
    loaded = sessions.load(workroot, session["id"])
    assert loaded["project_name"] == name.strip()
    assert sessions.project_path(workroot, loaded) == project


def test_equal_project_names_have_unique_folders(tmp_path):
    first = sessions.create(tmp_path, project_name="Same project")
    second = sessions.create(tmp_path, project_name="Same project")
    a, b = (sessions.project_path(tmp_path, item) for item in (first, second))
    assert a != b and a.is_dir() and b.is_dir()
    assert a.name.endswith("--" + first["id"])
    assert b.name.endswith("--" + second["id"])


def test_external_pointer_keeps_exact_title_without_opening_project(tmp_path, monkeypatch):
    workroot, parent = tmp_path / "app", tmp_path / "external"
    name = "华北平原：大豆 / VIC + CaMa（跨模型项目） " + "长期研究" * 16
    session = sessions.create(workroot, project_parent=parent, project_name=name)
    project = sessions.project_path(workroot, session)
    pointer = workroot / "sessions" / f"{session['id']}.json"
    assert json.loads(pointer.read_text(encoding="utf-8"))["title"] == name
    real_read = Path.read_text

    def no_external_read(path, *args, **kwargs):
        assert not path.is_relative_to(parent), "listing must not open an external project"
        return real_read(path, *args, **kwargs)

    def no_load(*_args, **_kwargs):
        pytest.fail("listing must use its pointer, not load the external session")

    monkeypatch.setattr(Path, "read_text", no_external_read)
    monkeypatch.setattr(sessions, "load", no_load)
    listed = sessions.list_all(workroot)
    assert len(listed) == 1
    assert listed[0]["title"] == name
    assert listed[0]["project_path"] == str(project)
    assert listed[0]["external"] is True


@pytest.mark.parametrize("title", [None, "", "   ", 17, []])
def test_external_pointer_invalid_title_uses_legacy_folder_label(tmp_path, title):
    index = tmp_path / "sessions"
    index.mkdir()
    sid = "abcdef123456"
    # No external folder needs to exist or be opened to list this older pointer.
    (index / f"{sid}.json").write_text(json.dumps({
        "kind": "geoforge-project-pointer-v1", "id": sid,
        "project_root": f"/not-opened/2026-09-28-Harbin-soybean--{sid}",
        "title": title,
    }))
    assert sessions.list_all(tmp_path)[0]["title"] == "Harbin soybean"


@pytest.mark.parametrize("name", ["../outside/Harbin", r"..\outside\Harbin", "CON", "大豆 项目"])
def test_display_name_cannot_escape_project_parent(tmp_path, name):
    parent = tmp_path / "research"
    session = sessions.create(tmp_path / "app", project_parent=parent, project_name=name)
    project = sessions.project_path(tmp_path / "app", session)
    assert project.parent == parent.resolve()
    assert project.name.endswith("--" + session["id"])
    assert session["project_name"] == name


INVALID_NAMES = ["", "   ", "...---___", "🌧️", "a" * 121,
                 "name\n", "\tname", "name\x00", "name\u200b", 12, True, [], {}]


@pytest.mark.parametrize("name", INVALID_NAMES)
def test_invalid_explicit_name_fails_before_any_files_are_created(tmp_path, name):
    for operation in (sessions.create, sessions.project_location):
        workroot = tmp_path / "app"
        with pytest.raises(ValueError, match="project name"):
            operation(workroot, project_name=name)
        assert not workroot.exists()


def test_name_length_boundary_and_legacy_omission(tmp_path):
    named = sessions.create(tmp_path, project_name="字" * 120)
    assert named["project_name"] == "字" * 120
    assert len(sessions.project_path(tmp_path, named).name.encode()) < 255
    legacy = sessions.create(tmp_path)
    assert legacy["title"] == "New session" and "project_name" not in legacy
    assert "new-session--" in sessions.project_path(tmp_path, legacy).name


@pytest.mark.parametrize("parent", ["relative/path", "../outside"])
def test_location_preview_rejects_relative_parent_without_writes(tmp_path, parent):
    with pytest.raises(ValueError, match="absolute"):
        sessions.project_location(tmp_path / "app", "Project", parent)
    assert not (tmp_path / "app").exists()


def test_location_preview_reports_file_parent_without_writes(tmp_path):
    parent = tmp_path / "file"
    parent.write_text("keep")
    with pytest.raises(ValueError, match="not a folder"):
        sessions.project_location(tmp_path / "app", "Project", parent)
    assert parent.read_text() == "keep" and not (tmp_path / "app").exists()


def test_real_get_and_post_handlers_use_same_name_and_preview(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions.time, "time", lambda: 1750000000)
    workroot, parent = tmp_path / "app", tmp_path / "user" / "projects"
    request = {"project_name": "Harbin 大豆", "project_parent": str(parent)}
    get, responses = handler(workroot, "/api/project-location?" + urlencode(request))
    get.do_GET()
    preview, status = responses.pop()
    assert status == 200 and not workroot.exists() and not parent.exists()
    post, responses = handler(workroot, "/api/sessions", {**request, "provider": "cli:kimi"})
    post.do_POST()
    session, status = responses.pop()
    assert status == 200
    assert session["project_name"] == session["title"] == "Harbin 大豆"
    assert session["project_path"] == preview["project_path_preview"].replace("{id}", session["id"])
    assert Path(session["project_path"]).is_dir()


@pytest.mark.parametrize("name", ["", "bad\nname", "---", "x" * 121])
def test_real_handlers_return_name_validation_errors_without_writes(tmp_path, name):
    workroot = tmp_path / "app"
    get, responses = handler(workroot, "/api/project-location?" + urlencode({"project_name": name}))
    get.do_GET()
    assert responses[-1][1] == 400 and "project name" in responses[-1][0]["error"]
    post, responses = handler(workroot, "/api/sessions", {"project_name": name})
    post.do_POST()
    assert responses[-1][1] == 400 and "project name" in responses[-1][0]["error"]
    assert not workroot.exists()


class ReachedFlow(BaseException):
    """Stop the real chat handler after saving its first message, before providers."""


@pytest.mark.parametrize("name", ["Harbin soybean", "New session", None])
def test_first_chat_keeps_explicit_name_and_folder_but_autotitles_legacy(tmp_path, monkeypatch, name):
    session = sessions.create(tmp_path, provider="cli:kimi", project_name=name)
    initial = sessions.project_path(tmp_path, session)
    (initial / "inputs" / "uploads" / "kept.csv").write_bytes(b"actual user data")
    chat, _responses = handler(tmp_path, "/unused")
    chat.catalog = []
    chat._open_stream = lambda: None
    chat._chunk = lambda _text: None
    chat._end_stream = lambda: None

    def stop(*_args, **_kwargs):
        raise ReachedFlow

    monkeypatch.setattr(flowrun, "pre", stop)
    message = "Please simulate soybean growth near Harbin."
    with pytest.raises(ReachedFlow):
        chat._stream_session_chat(session["id"], {"message": message})
    loaded = sessions.load(tmp_path, session["id"])
    current = sessions.project_path(tmp_path, loaded)
    if name is None:
        assert loaded["title"] == message[:48]
        assert "project_name" not in loaded and current != initial
    else:
        assert loaded["title"] == loaded["project_name"] == name
        assert current == initial
    assert (current / "inputs" / "uploads" / "kept.csv").read_bytes() == b"actual user data"
    loaded["title"] = "A later display-title edit"
    sessions.save(tmp_path, loaded)
    assert sessions.project_path(tmp_path, loaded) == current
    assert not (current / "runs" / "approval.json").exists()
