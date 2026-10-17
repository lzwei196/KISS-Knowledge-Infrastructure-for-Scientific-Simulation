"""Check a Windows bundle outside the checkout, without keys or model installs.

Run this against both the portable bundle and the silent install destination.
It uses the frozen executable for HTTP, harness and calibration import checks.
An isolated host-source check also projects the actual bundled WOFOST package;
that check is explicitly separate from frozen-code or native-model validation.
It does not exercise paid AI providers.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import threading
import urllib.request

import yaml


BUNDLED_DATA_KIS = {"Agrometeo_Quebec_Observations", "HYDAT_Observations"}


def check_catalogue(rows: list[dict], scientific: set[str], data: set[str]) -> None:
    names = [row["name"] for row in rows]
    expected = scientific | data
    assert len(names) == len(set(names)), "Bundled catalogue contains duplicate KI names"
    assert set(names) == expected, (
        f"Bundled catalogue mismatch: missing={sorted(expected - set(names))}, "
        f"unexpected={sorted(set(names) - expected)}")


def check_investigation_assets(app: str, script: str, bundled_script: str) -> None:
    assert 'id="openinvestigation"' in app, "Main chat investigation control missing"
    assert 'id="investigation-title"' in app, "Investigation panel header missing"
    assert '<script src="/investigation.js"></script>' in app, "Investigation script reference missing"
    assert script == bundled_script, "Investigation script payload differs from bundled asset"
    assert "global.GeoForgeInvestigation={create}" in script, "Investigation UI entrypoint missing"


def check_investigation_asset_file(app: str, script: str, bundled_path: Path) -> None:
    # HTTP decoding preserves CRLF. read_text() performs universal-newline
    # translation, so it cannot establish equality with the served payload.
    # Decode the actual file bytes without normalizing either side.
    check_investigation_assets(app, script, bundled_path.read_bytes().decode("utf-8"))


def guide_edition(manifest: dict) -> str:
    """Documentation can retain its reviewed edition across app-only releases."""
    edition = manifest.get("guides", {}).get("edition", manifest["version"])
    if not isinstance(edition, str) or not edition.strip():
        raise AssertionError("The release manifest must name a nonempty guide edition")
    return edition


def check_wofost_projection(library: Path, destination: Path, python: Path) -> dict:
    """Exercise real setup/project seams with actual release KI/helper files.

    No fixture KI, preflight, interpreter probe, model or provider is executed.
    The caller supplies a fresh workspace and isolated host-authority homes.
    Release CI installs this host application from the same validated tag;
    its identity is reported rather than described as frozen-code coverage.
    """
    from kiss_cli import gui, ki_adaptations, ki_fresh_paths, ki_guard
    from kiss_cli import paths, project_verification, setup
    from kiss_cli.catalog import KI

    library = library.resolve()
    destination = destination.resolve()
    if destination.exists():
        raise AssertionError("Projection smoke requires a new empty workspace")
    source = library / "models" / "WOFOST"
    assert (source / "SKILL.md").is_file(), "Actual WOFOST package missing"
    before = ki_fresh_paths.tree_files(source)
    shared = paths.KissConfig.default(destination / "work" / "wofost")
    shared.root.mkdir(parents=True)
    shared.python = str(python.resolve())
    shared.relocation = "none"
    setup.prepare_common(shared, library)
    (shared.root / paths.CONFIG_NAME).write_text(shared.dumps(), encoding="utf-8")

    handler = object.__new__(gui.Handler)
    handler.repo_root = handler.library_root = library
    handler.workroot = destination / "work"
    ki = KI("WOFOST", source)
    materialized = setup.materialise_active(source, shared.root / "ki", shared,
        manifest=handler._manifest(ki), library_root=library)
    assert not materialized.unresolved and not materialized.corrupted
    setup_lineage = ki_adaptations.projection(shared.root / "ki", shared)
    ki_fresh_paths.require_fresh_current(setup_lineage["path_projection"],
                                        candidate_root=shared.root / "ki")

    # Deliberately do not pass cfg: GUI must choose the saved runtime and prepare
    # its project-owned helpers before first KI materialisation, just as chat does.
    project = destination / "project \u4e2d\u6587"
    working, cfg = handler._session_workspace(project, ki)
    assert working.root == project / "models" / "WOFOST" / "ki"
    assert cfg.python == shared.python
    assert cfg.roles["binaries"] == shared.roles["binaries"]
    assert cfg.roles["ki_tools_common"].is_relative_to(project / "models" / "WOFOST")
    lineage = ki_adaptations.projection(working.root, cfg)
    proof = lineage["path_projection"]
    ki_fresh_paths.require_fresh_current(proof, candidate_root=working.root)
    saved = paths.KissConfig.load(working.root.parent)
    assert saved.python == cfg.python and saved.roles == cfg.roles
    assert proof["logical_target"] == str(working.root)
    assert proof["runtime"]["selected_python"]["path"] == str(Path(cfg.python))
    def assignments(path):
        return {node.targets[0].id: node.value
                for node in ast.parse(path.read_text(encoding="utf-8")).body
                if isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)}
    original = assignments(source / "preflight_check.py")
    projected_preflight = assignments(working.root / "preflight_check.py")
    assert ast.literal_eval(projected_preflight["PYTHON"]) == cfg.python.replace("\\", "/")
    assert ast.literal_eval(projected_preflight["KI_TOOLS_COMMON"]) == str(
        cfg.roles["ki_tools_common"]).replace("\\", "/")
    assert ast.literal_eval(projected_preflight["TOOL_FILES"]) == ast.literal_eval(original["TOOL_FILES"])
    assert ast.dump(projected_preflight["MODEL_ENTRYPOINT"]) == ast.dump(
        ast.parse('os.path.join(KI_DIR, "run_and_score.py")', mode="eval").body)
    projected_manifest = yaml.safe_load((working.root / "knowledge_infrastructure.yaml").read_text("utf-8"))
    assert projected_manifest["package"]["binary"]["path"] == str(
        working.root / "run_and_score.py").replace("\\", "/")
    assert (working.root / "run_and_score.py").is_file()
    assert all(proof[key] is False for key in
        ("runtime_bound", "native_execution", "model_execution", "preflight_passed", "scientific_validation"))
    assert ki_guard.is_managed(working.root)
    assert project_verification.status(project, working)["can_run"] is False
    assert not (project / ".geoforge" / "receipts").exists()

    # Continuation must retain the pair; bootstrap is not permission to rewrite
    # a saved project or issue execution readiness.
    projected = ki_fresh_paths.tree_files(working.root)
    saved_bytes = (working.root.parent / paths.CONFIG_NAME).read_bytes()
    reopened, reopened_cfg = handler._session_workspace(project, ki)
    assert reopened.root == working.root and reopened_cfg.roles == cfg.roles
    assert ki_fresh_paths.tree_files(working.root) == projected
    assert (working.root.parent / paths.CONFIG_NAME).read_bytes() == saved_bytes
    assert ki_adaptations.projection(reopened.root, reopened_cfg) == lineage
    assert ki_fresh_paths.tree_files(source) == before

    return {
        "passed": True, "scope": "host-source static setup and GUI projection of actual bundled KI",
        "host_application_module": str(Path(gui.__file__).resolve()),
        "host_python": str(Path(sys.executable).resolve()),
        "host_path_policy_sha256": ki_fresh_paths.source_digest(),
        "host_source_files_sha256": {
            name: hashlib.sha256(Path(sys.modules["kiss_cli." + name].__file__).read_bytes()).hexdigest()
            for name in ("gui", "setup", "ki_adaptations", "ki_path_contracts", "ki_fresh_paths", "port")
        },
        "library": str(library), "model": ki.name,
        "library_manifest_sha256": hashlib.sha256((library / "release-manifest.json").read_bytes()).hexdigest(),
        "source_files": before,
        "recognized_ast_sha256": proof["recognized_ast_sha256"],
        "shared_setup_projection": True, "fresh_gui_project_projection": True,
        "retained_project_reopen": True, "saved_runtime_and_helpers_bound": True,
        "source_unchanged": True, "preflight_passed": False,
        "model_execution": False, "scientific_validation": False,
        "frozen_code_execution": False,
    }


def stop(process: subprocess.Popen) -> None:
    if process.poll() is None:
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       capture_output=True, timeout=20,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        process.wait(timeout=20)


def check(bundle: Path, report: dict) -> None:
    if os.name != "nt":
        raise RuntimeError("Run this release check on Windows")
    executable = bundle / "GeoForge Desktop.exe"
    internal = bundle / "_internal"
    for path in (executable, internal / "python311.dll",
                 internal / "release-manifest.json",
                 bundle / "geoforge-agent-bridge.exe",
                 internal / "system_kis" / "GeoForge_Database" / "SKILL.md"):
        if not path.is_file():
            raise AssertionError(f"Required release file missing: {path}")
    manifest = json.loads((internal / "release-manifest.json").read_text("utf-8"))
    report["version"] = manifest["version"]
    expected_guide_edition = guide_edition(manifest)
    packages = sorted(p for p in (internal / "models").iterdir() if p.is_dir())
    assert len(packages) == 127, f"Expected 127 KI directories, got {len(packages)}"
    assert all((p / "SKILL.md").is_file() for p in packages)
    assert all((p / "docs" / "install.windows.md").is_file() for p in packages)
    data_packages = sorted(p for p in (internal / "data_kis").iterdir() if p.is_dir())
    data_names = {p.name for p in data_packages}
    assert data_names == BUNDLED_DATA_KIS, f"Unexpected bundled data KIs: {sorted(data_names)}"
    assert all((p / "SKILL.md").is_file() for p in data_packages)
    recipes = [p for p in packages if (p / "kiss.windows.yaml").is_file()]
    assert len(recipes) == 23, f"Expected 23 Windows recipes, got {len(recipes)}"
    for package in recipes:
        embedded = yaml.safe_load((package / "kiss.windows.yaml").read_text("utf-8"))
        shared = yaml.safe_load((internal / "kiss" / "manifests" /
                                 f"{package.name}.yaml").read_text("utf-8"))
        assert embedded == shared, f"Conflicting recipe copies: {package.name}"
    report.update(ki_count=len(packages), windows_notes=len(packages),
                  windows_recipes=len(recipes), python_dll="python311.dll",
                  data_ki_count=len(data_packages), data_kis=sorted(data_names))
    with tempfile.TemporaryDirectory(prefix="geoforge-release-smoke-") as temporary:
        isolated = Path(temporary)
        env = os.environ.copy()
        for key in list(env):
            if key.endswith("_API_KEY") or key in ("PYTHONPATH", "PYTHONHOME",
                                                  "GEOFORGE_KI_UPDATE_BRANCH"):
                env.pop(key, None)
        env.update(APPDATA=str(isolated / "roaming"),
                   LOCALAPPDATA=str(isolated / "local"),
                   USERPROFILE=str(isolated / "home"), HOME=str(isolated / "home"),
                   GEOFORGE_FLOW_KEYS=str(isolated / "flow-keys"),
                   GEOFORGE_FLOW_REGISTRY=str(isolated / "flow-registry"),
                   GEOFORGE_DATABASE_OFFLINE="1",
                   GEOFORGE_KI_UPDATE_HOME=str(isolated / "ki-updates"),
                   GEOFORGE_KI_GUARD_HOME=str(isolated / "ki-guard"),
                   GEOFORGE_KI_ADAPTATION_HOME=str(isolated / "ki-adaptations"),
                   GEOFORGE_KI_VERIFICATION_HOME=str(isolated / "ki-verification"))
        for key in list(env):
            if key.startswith("GEOFORGE_AGENT_"):
                env.pop(key, None)
        projection_report = isolated / "wofost-projection.json"
        projection = subprocess.run([
            sys.executable, "-B", str(Path(__file__).resolve()), str(bundle),
            "--projection-worker", str(isolated / "wp"),
            "--report", str(projection_report),
        ], cwd=isolated, env=env, capture_output=True, encoding="utf-8",
            timeout=180, creationflags=subprocess.CREATE_NO_WINDOW)
        assert projection.returncode == 0, (projection.stdout, projection.stderr)
        projected = json.loads(projection_report.read_text(encoding="utf-8"))
        assert projected["passed"], projected
        report["bundled_wofost_host_projection"] = projected
        # No Python/py on PATH: the console helper must use the bundled DLL.
        helper_env = {**env, "PATH": str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32")}
        helper = bundle / "geoforge-agent-bridge.exe"
        for mode in ("flow", "database"):
            result = subprocess.run([str(helper), mode], cwd=isolated, env=helper_env,
                                    capture_output=True, text=True, timeout=60,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            assert result.returncode == 3, (mode, result.stdout, result.stderr)
            assert "session" in result.stderr.lower(), result.stderr
        report["self_contained_agent_bridge"] = "passed without Python on PATH"
        seen = []

        class BridgeFixture(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def respond(self, body):
                encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def do_GET(self):
                seen.append(("database", self.headers.get("X-GeoForge-Agent-Token")))
                self.respond({"ok": True, "datasets": [{"id": "fixture", "name": "测试资料"}]})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                seen.append(("flow", self.headers.get("X-GeoForge-Question-Token"), body))
                self.respond({"returncode": 0, "stdout": "已收到问题\n"})

        server = ThreadingHTTPServer(("127.0.0.1", 0), BridgeFixture)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            endpoint = f"http://127.0.0.1:{server.server_port}"
            transport_env = {**helper_env, "GEOFORGE_AGENT_DATABASE_TOKEN": "fixture-capability",
                             "GEOFORGE_AGENT_QUESTION_TOKEN": "fixture-question",
                             "GEOFORGE_AGENT_DATABASE_URL": endpoint + "/catalogue",
                             "GEOFORGE_AGENT_FLOW_URL": endpoint + "/flow"}
            question = json.dumps({"title": "选择气象资料"}, ensure_ascii=False)
            for arguments in (["database", "--query", "测试资料"],
                              ["flow", "ask-question", "--json", question]):
                result = subprocess.run([str(helper), *arguments], cwd=isolated,
                                        env=transport_env, capture_output=True,
                                        encoding="utf-8", timeout=60,
                                        creationflags=subprocess.CREATE_NO_WINDOW)
                assert result.returncode == 0, (arguments[0], result.stdout, result.stderr)
                assert ("测试资料" if arguments[0] == "database" else "已收到问题") in result.stdout
            assert seen[0] == ("database", "fixture-capability"), seen
            assert seen[1][0:2] == ("flow", "fixture-question"), seen
            assert seen[1][2]["argv"] == ["ask-question", "--json", question], seen
            report["frozen_bridge_unicode_ipc"] = "passed against a local fixture (no live provider)"
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)
        report["database_system_ki"] = "bundled separately from 127 scientific KIs"
        # Never pass --models: discovery must use the bundled library.
        for command in ("harness-status", "calibration-status"):
            process = subprocess.Popen([str(executable), command], cwd=isolated,
                                       env=env, creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                code = process.wait(timeout=120)
                assert code == 0, f"Frozen {command} exited {code}"
                report[command] = "passed"
            finally:
                stop(process)
        with socket.socket() as available:
            available.bind(("127.0.0.1", 0))
            port = available.getsockname()[1]
        process = subprocess.Popen(
            [str(executable), "gui", "--no-browser", "--desktop-server",
             "-p", str(port), "-w", str(isolated / "work")],
            cwd=isolated, env=env, creationflags=subprocess.CREATE_NO_WINDOW)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def fetch(route: str) -> str:
            with opener.open(f"http://127.0.0.1:{port}{route}", timeout=45) as response:
                assert response.status == 200, route
                return response.read().decode("utf-8")

        try:
            deadline = time.monotonic() + 90
            while True:
                assert process.poll() is None, "Frozen HTTP server exited during startup"
                try:
                    assert "GeoForge" in fetch("/")
                    break
                except (OSError, TimeoutError):
                    if time.monotonic() > deadline:
                        raise RuntimeError("Frozen HTTP server did not start in 90 seconds")
                    time.sleep(0.5)
            routes = ["/", "/setup", "/library", "/i18n.js", "/clipboard.js", "/investigation.js"]
            for route in routes:
                assert len(fetch(route)) > 100, f"Empty asset: {route}"
            check_investigation_asset_file(fetch("/"), fetch("/investigation.js"),
                internal / "kiss_cli/web/investigation.js")
            report["investigation_ui_assets"] = "passed; no reviewer or model was invoked"
            # These guides must work without GitHub or any network provider.
            guide_routes = []
            for kind in ("manual", "quickstart", "calibration"):
                for language in ("en", "zh-CN"):
                    for extension in ("html", "pdf"):
                        route = f"/guide/{kind}/{language}.{extension}"
                        with opener.open(f"http://127.0.0.1:{port}{route}", timeout=10) as response:
                            content = response.read()
                            content_type = response.headers.get_content_type()
                        expected = internal / "kiss_cli" / "web" / "guides" / f"{kind}-{language}.{extension}"
                        assert content == expected.read_bytes(), f"Guide payload mismatch: {route}"
                        if extension == "pdf":
                            assert content_type == "application/pdf" and content.startswith(b"%PDF-"), route
                        else:
                            assert content_type == "text/html", route
                            assert expected_guide_edition in content.decode("utf-8"), route
                        assert len(content) > 1000, f"Incomplete guide: {route}"
                        guide_routes.append(route)
            report["offline_usage_guides"] = {
                "passed": True, "edition": expected_guide_edition, "routes": guide_routes,
            }
            models = json.loads(fetch("/api/models"))
            check_catalogue(models, {p.name for p in packages}, data_names)
            report["catalogue_count"] = len(models)
            assert "KI HARNESS v1" in fetch("/api/prompt/MODFLOW6")
            flow = json.loads(fetch("/api/flow-status"))
            assert flow.get("ready"), flow
            assert "_internal" in flow["source"], flow
            updates = json.loads(fetch("/api/ki-updates"))
            assert updates["branch"] == "main", updates
            database = json.loads(fetch("/api/obs/status"))
            assert isinstance(database, dict), database
            settings = json.loads(fetch("/api/settings"))
            assert settings["platform"] == "windows", settings
            report.update(http_routes=routes + ["/api/models", "/api/prompt/MODFLOW6",
                          "/api/flow-status", "/api/ki-updates", "/api/obs/status",
                          "/api/settings"],
                          flow="passed", ki_update_branch=updates["branch"])
        finally:
            stop(process)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--projection-worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    report = {"bundle": str(args.bundle.resolve()), "passed": False}
    try:
        if args.projection_worker is not None:
            report.update(check_wofost_projection(args.bundle.resolve() / "_internal",
                                                 args.projection_worker, Path(sys.executable)))
        else:
            check(args.bundle.resolve(), report)
        report["passed"] = True
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
