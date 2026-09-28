"""Check a Windows bundle outside the checkout, without keys or model installs.

Run this against both the portable bundle and the silent install destination.
It uses the frozen executable for HTTP, harness and calibration import checks;
the host Python only drives the checks. It does not exercise paid AI providers.
"""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import threading
import urllib.request

import yaml


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
    packages = sorted(p for p in (internal / "models").iterdir() if p.is_dir())
    assert len(packages) == 127, f"Expected 127 KI directories, got {len(packages)}"
    assert all((p / "SKILL.md").is_file() for p in packages)
    assert all((p / "docs" / "install.windows.md").is_file() for p in packages)
    recipes = [p for p in packages if (p / "kiss.windows.yaml").is_file()]
    assert len(recipes) == 23, f"Expected 23 Windows recipes, got {len(recipes)}"
    for package in recipes:
        embedded = yaml.safe_load((package / "kiss.windows.yaml").read_text("utf-8"))
        shared = yaml.safe_load((internal / "kiss" / "manifests" /
                                 f"{package.name}.yaml").read_text("utf-8"))
        assert embedded == shared, f"Conflicting recipe copies: {package.name}"
    report.update(ki_count=len(packages), windows_notes=len(packages),
                  windows_recipes=len(recipes), python_dll="python311.dll")
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
                   GEOFORGE_KI_UPDATE_HOME=str(isolated / "ki-updates"))
        for key in list(env):
            if key.startswith("GEOFORGE_AGENT_"):
                env.pop(key, None)
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
            routes = ["/", "/setup", "/library", "/i18n.js", "/clipboard.js"]
            for route in routes:
                assert len(fetch(route)) > 100, f"Empty asset: {route}"
            models = json.loads(fetch("/api/models"))
            assert {m["name"] for m in models} == {p.name for p in packages}
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
    args = parser.parse_args()
    report = {"bundle": str(args.bundle.resolve()), "passed": False}
    try:
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
