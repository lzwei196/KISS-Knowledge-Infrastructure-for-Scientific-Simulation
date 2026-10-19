"""Read-only context using authentic signatures over synthetic file fixtures.

These prove context/currentness plumbing, not native Linux functionality.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

from kiss_cli import dependency_capabilities as cap, flowgate, gui, native_dependency_gate as gate
from kiss_cli import paths, runtime_backend, runtime_context, runtime_facts as facts


def row(path, *, package="fixture"):
    data = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "package": package}


@dataclass(frozen=True)
class FixtureBinding:
    distro: str
    user: str
    workspace: str
    workspace_id: str
    python: str = "/usr/bin/python3"


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    authority = tmp_path / "authority"
    authority.mkdir()
    guest = tmp_path / "guest"
    root = guest / "shared-install"
    root.mkdir(parents=True)
    cfg = paths.KissConfig.default(root)
    cfg.python = sys.executable
    config = root / paths.CONFIG_NAME
    config.write_text(cfg.dumps(), encoding="utf-8")
    manifest = {"model": "Demo", "acquire": {"produces": "engine.exe"},
                "system_deps": ["mpif90", "nf-config"]}
    engine = cfg.roles["binaries"] / "Demo" / "engine.exe"
    engine.parent.mkdir(parents=True)
    engine.write_bytes(b"synthetic model bytes, never executed")
    binding = FixtureBinding("Ubuntu", "fixture", str(guest), "a" * 32)
    runtime = {"kind": "wsl", "distro": "Ubuntu", "user": "fixture", "guest_identity": "b" * 64}
    monkeypatch.setattr(runtime_context, "identity", lambda: runtime)
    monkeypatch.setattr(gate, "_context", lambda: (binding, authority, runtime_backend.LocalExecutor))
    tools, system = {}, {}
    for name in facts._PROFILE_TOOLS:
        tool = guest / (name + ".exe")
        tool.write_bytes((name + " official fixture").encode())
        tools[name] = str(tool)
        system[str(tool)] = row(tool)
    monkeypatch.setattr(facts, "_PROFILE_TOOLS", tools)
    monkeypatch.setattr(facts, "_ROLE_TARGETS", {
        name: (re.escape(Path(path).as_posix()), "fixture") for name, path in tools.items()})
    probe = guest / "probe"
    probe.mkdir()
    artifacts = {}
    for name in cap.ARTIFACTS:
        path = probe / name
        path.write_bytes(b"" if name.endswith(".stderr") else (name + " fixture").encode())
        artifacts[name] = {key: value for key, value in row(path).items() if key in {"bytes", "sha256"}}
    report = {"policy": cap.POLICY, "profile": cap.PROFILE, "implementation": cap._implementation(),
              "binding": asdict(binding), "backend_identity": runtime["guest_identity"],
              "model_readiness": False, "relative": "probe",
              "evidence": {"system_files": system, "workspace": str(probe), "artifacts": artifacts}}
    signer = flowgate.load().receipts
    signer.sign(authority, report)
    binary = {"policy": cap.BINARY_POLICY, "implementation": cap._implementation(),
              "binding": asdict(binding), "backend_identity": runtime["guest_identity"],
              "model_readiness": False, "executable": str(engine),
              "capability_sha256": cap._hash(cap._json(report)),
              "evidence": {**row(engine), "executable": str(engine), "libraries": system}}
    signer.sign(authority, binary)
    saved = {"capabilities": report, "binary": binary}
    location = gate._record_path(authority, cfg)
    location.write_text(json.dumps(saved), encoding="utf-8")
    return SimpleNamespace(root=root, cfg=cfg, config=config, manifest=manifest, saved=saved,
        location=location, authority=authority, engine=engine, tools=tools, probe=probe, runtime=runtime)


def test_exact_runtime_facts_without_processes_or_writes(case, monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: pytest.fail("planning cannot run a process"))
    monkeypatch.setattr(runtime_backend.LocalExecutor, "inspect", lambda *a: pytest.fail("no backend probe"))
    monkeypatch.setattr(cap, "verify", lambda *a, **kw: pytest.fail("no synthetic probe"))
    before = {p: p.read_bytes() for p in case.root.parent.rglob("*") if p.is_file()}
    value = facts.context(case.manifest, case.root)
    assert value["state"] == "authenticated_bytes_current"
    assert value["tools"]["mpi_launcher"]["invoke"] == case.tools["mpi_launcher"]
    assert value["executable"]["path"] == str(case.engine)
    assert value["model_readiness"] is False
    assert before == {p: p.read_bytes() for p in case.root.parent.rglob("*") if p.is_file()}
    text = facts.prompt(case.manifest, case.root)
    assert "last verified" in text and "grants no command permission" in text
    assert "official reference case match" in text
    assert str(case.authority) not in text and "signature" not in text


@pytest.mark.parametrize("target", ["model", "tool", "probe", "empty_stderr"])
def test_same_path_changed_bytes_are_not_context_facts(case, target):
    path = {"model": case.engine, "tool": Path(case.tools["mpi_launcher"]),
            "probe": case.probe / "mpi.stdout", "empty_stderr": case.probe / "mpi.stderr"}[target]
    old = path.stat()
    data = path.read_bytes()
    path.write_bytes((b"x" + data[1:]) if data else b"x")
    import os
    os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
    assert facts.context(case.manifest, case.root)["state"] == "unavailable"


@pytest.mark.parametrize("change", ["signature", "link", "implementation", "binding", "readiness", "missing"])
def test_unauthenticated_or_stale_record_is_explicitly_unavailable(case, change):
    if change == "missing":
        case.location.unlink()
    else:
        document = case.saved
        if change == "signature": document["capabilities"]["profile"] = "other"
        else:
            binary = document["binary"]
            if change == "link": binary["capability_sha256"] = "0" * 64
            if change == "implementation": binary["implementation"] = "0" * 64
            if change == "binding": binary["binding"] = {"workspace": "other"}
            if change == "readiness": binary["model_readiness"] = True
            flowgate.load().receipts.sign(case.authority, binary)
        case.location.write_text(json.dumps(document), encoding="utf-8")
    value = facts.context(case.manifest, case.root)
    assert value["state"] == "unavailable" and "tools" not in value


def test_tool_alias_must_resolve_to_a_signed_file(case, monkeypatch):
    guessed = case.root / "guessed-mpirun"
    guessed.write_bytes(b"plausible but unverified")
    monkeypatch.setattr(facts, "_PROFILE_TOOLS", {**case.tools, "mpi_launcher": str(guessed)})
    assert facts.context(case.manifest, case.root)["state"] == "unavailable"


def test_tool_alias_cannot_change_roles_to_another_signed_tool(case, monkeypatch):
    monkeypatch.setattr(facts, "_PROFILE_TOOLS", {
        **case.tools, "mpi_launcher": case.tools["netcdf_format_reader"]})
    assert facts.context(case.manifest, case.root)["state"] == "unavailable"


def test_malformed_saved_config_is_never_repaired(case):
    raw = b'[kiss]\nroot = "C:\\Users\\bad"\n'
    case.config.write_bytes(raw)
    assert facts.context(case.manifest, case.root)["state"] == "unavailable"
    assert case.config.read_bytes() == raw


def test_other_profiles_do_not_invent_dependency_facts(tmp_path):
    assert facts.prompt({"model": "Other"}, tmp_path / "absent") == ""


def test_gui_shared_api_cli_context_uses_each_ki_installation_not_project_defaults(case, monkeypatch):
    calls = []
    def context(manifest, root):
        calls.append((manifest["model"], root))
        return "[FACT " + manifest["model"] + "]"
    monkeypatch.setattr(facts, "prompt", context)
    roots = {"First": case.root, "Second": case.root.parent / "second-install"}
    handler = SimpleNamespace(
        _status_for=lambda _: {"can_run": True, "steps": []},
        _manifest=lambda ki: {"model": ki.name}, _workdir=lambda ki: roots[ki.name])
    project_cfg = SimpleNamespace(roles={"binaries": case.root.parent / "unrelated-project"})
    text = gui.Handler._software_status_prompt(handler,
        [SimpleNamespace(name=name) for name in roots], project_cfg)
    assert calls == list(roots.items())
    assert "[FACT First]" in text and "[FACT Second]" in text
