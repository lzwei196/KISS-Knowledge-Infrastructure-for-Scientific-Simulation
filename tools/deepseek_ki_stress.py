#!/usr/bin/env python3
"""Resumable, sequential DeepSeek setup stress test for every bundled KI."""

from __future__ import annotations

import argparse
from http.cookiejar import CookieJar
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import platform
import stat
import socket
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener


OPENER = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))


def preserve_native_evidence(target: Path, evidence: Path, model: str) -> None:
    """Retain bounded provenance, never follow a product outside its workspace."""
    target = target.resolve()
    installation = target / "installation-test.json"
    if not installation.is_file() or not installation.resolve().is_relative_to(target):
        return
    try:
        result = json.loads(installation.read_text())
        if not isinstance(result, dict):
            return
        raw = result.get("binary")
        if not raw:
            return
        binary = Path(raw)
        if not binary.is_absolute():
            return
        binary = binary.resolve()
        if not binary.is_relative_to(target) or not binary.is_file():
            return
        digest = hashlib.sha256()
        with binary.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / "native-product.json").write_text(json.dumps({
            "path": str(binary), "relative_path": binary.relative_to(target).as_posix(),
            "size_bytes": binary.stat().st_size, "sha256": digest.hexdigest(),
            "source": "independently resolved installation-test executable; identity hash only",
        }, indent=2))
        known = target / "binaries/PHREEQC/source/phreeqc-3.8.6-17100"
        receipt = known / "macos-build-receipt.json"
        if (model == "PHREEQC" and binary == (known / "build/phreeqc").resolve()
                and receipt.is_file() and not receipt.is_symlink()
                and receipt.resolve().is_relative_to(known.resolve())
                and receipt.stat().st_size <= 65536):
            # This helper-authored record is provenance, not an independent source audit.
            shutil.copy2(receipt, evidence / "helper-macos-build-receipt.json")
    except (OSError, ValueError, TypeError):
        # Evidence enrichment must not invalidate an already recorded test result.
        return


def http_json(url: str, payload: dict | None = None, timeout: float = 30) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers={"Content-Type": "application/json"})
    with OPENER.open(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class Server:
    def __init__(self, repo: Path, workroot: Path, executable: Path | None = None):
        self.repo, self.workroot = repo, workroot
        self.executable = executable
        self.proc: subprocess.Popen | None = None
        self.base = ""

    def start(self) -> None:
        port = free_port()
        self.base = f"http://127.0.0.1:{port}"
        log = self.workroot.parent / "server.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        stream = log.open("ab")
        entry = ([str(self.executable)] if self.executable else
                 [sys.executable, str(self.repo / "kiss" / "kiss_entry.py")])
        cmd = [*entry, "gui", "--no-browser", "--port", str(port),
               "--workroot", str(self.workroot)]
        self.proc = subprocess.Popen(cmd, cwd=self.repo / "kiss", stdout=stream,
                                     stderr=subprocess.STDOUT, start_new_session=os.name != "nt")
        stream.close()
        deadline = time.time() + 90
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"GeoForge server exited with {self.proc.returncode}; see {log}")
            try:
                http_json(self.base + "/api/models", timeout=30)
                return
            except (OSError, ValueError):
                time.sleep(.25)
        self.stop()
        raise TimeoutError("GeoForge server did not become ready in 90 seconds")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            if os.name == "nt":
                # The server owns the agent CLI, which may own compilers and
                # model processes. Terminating only the HTTP parent leaves the
                # descendants alive and their build directories locked.
                subprocess.run(
                    ["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                    capture_output=True, timeout=30,
                )
                try:
                    self.proc.wait(5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
            else:
                try:
                    os.killpg(self.proc.pid, signal.SIGTERM)
                    self.proc.wait(10)
                except subprocess.TimeoutExpired:
                    pass
                except ProcessLookupError:
                    pass
                finally:
                    try:
                        os.killpg(self.proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    self.proc.wait(5)
        self.proc = None


def cleanup_target(target: Path, workroot: Path) -> str:
    """Best-effort bounded cleanup; return an error without aborting a matrix."""
    resolved = target.resolve(strict=False)
    if resolved.parent != workroot.resolve():
        raise RuntimeError(f"refusing cleanup outside stress workroot: {resolved}")
    if not resolved.exists():
        return ""

    def _remove_readonly(func, path, exc_info):
        # Agents may delete scratch files while the harness is walking the
        # tree. A vanished child is already clean and must not abort removal
        # of the remaining (often much larger) distribution.
        if not os.path.lexists(path):
            return
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except FileNotFoundError:
            return
        except OSError:
            raise exc_info[1]

    last = None
    for delay in (0, 1, 3):
        if delay:
            time.sleep(delay)
        try:
            shutil.rmtree(resolved, onerror=_remove_readonly)
            return "" if not resolved.exists() else "directory still exists"
        except OSError as exc:
            last = exc
    # Deep Windows source trees can leave a directory behind even after the
    # read-only retry (CE-QUAL-W2 has paths near the Win32 boundary). CMake's
    # native filesystem helper removes the same already-validated exact target
    # without crossing through cmd.exe or constructing a shell command.
    if os.name == "nt":
        cmake = shutil.which("cmake")
        if cmake:
            try:
                completed = subprocess.run(
                    [cmake, "-E", "remove_directory", str(resolved)],
                    capture_output=True, text=True, timeout=300,
                )
                if not resolved.exists():
                    return ""
                detail = (completed.stderr or completed.stdout).strip()
                if detail:
                    last = OSError(detail[-500:])
            except (OSError, subprocess.TimeoutExpired) as exc:
                last = exc
    return repr(last)


def run_setup(base: str, model: str, timeout_seconds: int) -> tuple[str, str]:
    result: list[tuple[str, str]] = []

    def request() -> None:
        try:
            req = Request(base + "/api/setup-agent",
                          data=json.dumps({"model": model, "provider": "api:deepseek",
                                           "llm_model": "deepseek-chat",
                                           "installation_only": True}).encode(),
                          headers={"Content-Type": "application/json"})
            with OPENER.open(req, timeout=300) as response:
                body = response.read().decode("utf-8", "replace")
            result.append(("completed", body[-8000:]))
        except Exception as exc:  # recorded per KI; the matrix continues
            result.append(("request-error", repr(exc)))

    thread = threading.Thread(target=request, daemon=True)
    thread.start()
    thread.join(timeout_seconds)
    return ("timeout", f"wall-clock timeout after {timeout_seconds}s") if thread.is_alive() else result[0]


def classify(state: dict, transport: str, installation: dict | None = None) -> str:
    software = state.get("software") or {}
    request = state.get("request") or {}
    if installation and installation.get("usable"):
        return "installed"
    if request.get("status") == "waiting":
        return "needs-user"
    if transport in {"timeout", "request-error"}:
        return "timeout"
    return "failed"


def write_csv(path: Path, rows: list[dict]) -> None:
    fields = ["model", "result", "seconds", "software_state", "request_kind",
              "request_title", "request_detail", "expected_path",
              "resolved_binary", "error", "finished_at", "implementation_id",
              "installation_scope", "official_upstream_verified"]
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(
        "_stress_deepseek_windows" if os.name == "nt" else "_stress_deepseek_macos"))
    parser.add_argument("--installs-root", type=Path, help="dedicated disposable installation directory; evidence remains under --root")
    parser.add_argument("--timeout-minutes", type=int, default=60)
    parser.add_argument("--limit", type=int, help="smoke-test only the first N pending KIs")
    parser.add_argument("--models", nargs="+",
                        help="run only these KI names (useful for targeted regressions)")
    parser.add_argument("--cleanup", action="store_true",
                        help="remove each dedicated install after its result is safely recorded")
    parser.add_argument("--executable", type=Path, help="test this compiled GeoForge executable")
    args = parser.parse_args()
    if args.timeout_minutes <= 0:
        parser.error("--timeout-minutes must be positive")
    if args.executable:
        args.executable = args.executable.resolve()
        if not args.executable.is_file():
            parser.error("compiled executable does not exist")
    repo = Path(__file__).resolve().parents[1]
    root = args.root.resolve(); workroot = (args.installs_root or root / "installs").resolve()
    root.mkdir(parents=True, exist_ok=True); workroot.mkdir(parents=True, exist_ok=True)
    jsonl, csv_path = root / "results.jsonl", root / "results.csv"
    rows = []
    if jsonl.exists():
        for line in jsonl.read_text(encoding="utf-8").splitlines():
            try: rows.append(json.loads(line))
            except ValueError: pass
    done = {row["model"] for row in rows}
    server = Server(repo, workroot, args.executable)
    try:
        server.start()
        models = [item["name"] for item in http_json(server.base + "/api/models")]
        (root / "models.json").write_text(json.dumps(models, indent=2), encoding="utf-8")
        if len(models) != 127:
            raise RuntimeError(f"expected 127 bundled KIs, API returned {len(models)}")
        pending = [name for name in models if name not in done]
        if args.models:
            requested = set(args.models)
            unknown = requested.difference(models)
            if unknown:
                raise ValueError("unknown KI names: " + ", ".join(sorted(unknown)))
            pending = [name for name in pending if name in requested]
        if args.limit is not None: pending = pending[:args.limit]
        print(f"DeepSeek KI stress: {len(done)}/127 recorded; running {len(pending)}", flush=True)
        for index, model in enumerate(pending, len(done) + 1):
            if (root / "PAUSE_AFTER_MODEL").exists():
                print("Paused at model boundary by PAUSE_AFTER_MODEL", flush=True)
                break
            if shutil.disk_usage(root).free < 12 * 1024**3:
                raise RuntimeError("Less than 12 GiB free: stopped before starting another install")
            started = time.time(); target = workroot / model
            print(f"[{index}/127] {model}: setup starting", flush=True)
            try:
                http_json(server.base + "/api/setup-location", {"model": model, "path": str(target)})
                transport, detail = run_setup(server.base, model, args.timeout_minutes * 60)
                if transport in {"timeout", "request-error"}:
                    server.stop(); server.start()
                state = http_json(server.base + "/api/setup/" + quote(model), timeout=30)
                installation_path = target / "installation-test.json"
                installation = (json.loads(installation_path.read_text(encoding="utf-8"))
                                if installation_path.is_file() else None)
                software, request = state.get("software") or {}, state.get("request") or {}
                primary = software.get("primary_error") or {}
                request_detail = "\n".join(filter(None, (
                    str(request.get("message") or "").strip(),
                    str(request.get("resume_hint") or "").strip(),
                )))
                error = (request_detail or (installation or {}).get("summary") or
                         (primary.get("detail") if isinstance(primary, dict)
                          else str(primary or detail)))
                agent_log = target / "setup-agent.log"
                try:
                    agent_tail = agent_log.read_text(
                        encoding="utf-8", errors="replace")[-8000:]
                except OSError:
                    agent_tail = ""
                row = {"model": model, "result": classify(state, transport, installation),
                       "seconds": round(time.time() - started, 1),
                       "software_state": ((installation or {}).get("state") or
                                          software.get("state", "")),
                       "request_kind": request.get("kind", ""),
                       "request_title": request.get("title", ""),
                       "request_detail": request_detail[-4000:],
                       "expected_path": request.get("expected_path", ""),
                       "resolved_binary": (installation or {}).get("binary", ""),
                       "agent_tail": agent_tail,
                       "error": (error or detail)[-2000:],
                       "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
                # Preserve the independently checked product identity. A declared
                # Python variant is not evidence of an official upstream install.
                for key in ("implementation_id", "installation_scope",
                            "official_upstream_verified"):
                    if key in (installation or {}):
                        row[key] = installation[key]
            except Exception as exc:
                row = {"model": model, "result": "harness-error",
                       "seconds": round(time.time() - started, 1), "software_state": "",
                       "request_kind": "", "request_title": "",
                       "request_detail": "", "expected_path": "",
                       "resolved_binary": "",
                       "agent_tail": "", "error": repr(exc),
                       "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
                # One model or one spawned installer must not invalidate every
                # later KI. A dead/refusing backend is infrastructure damage,
                # so restore it before recording and continuing the matrix.
                try:
                    server.stop()
                    server.start()
                except Exception as restart_exc:
                    row["error"] += f"; server restart failed: {restart_exc!r}"
            row["platform"] = platform.system()
            row["architecture"] = platform.machine()
            with jsonl.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            rows.append(row); write_csv(csv_path, rows)
            print(f"[{index}/127] {model}: {row['result']} ({row['seconds']}s)", flush=True)
            # Retain the complete evidence before deleting this disposable install.
            evidence = root / "evidence" / model
            evidence.mkdir(parents=True, exist_ok=True)
            for name in ("installation-test.json", "setup-agent.log", "kiss.toml"):
                source = target / name
                if source.is_file():
                    shutil.copy2(source, evidence / name)
            preserve_native_evidence(target, evidence, model)
            if args.cleanup:
                cleanup_error = cleanup_target(target, workroot)
                if cleanup_error:
                    message = f"{model}: {cleanup_error}\n"
                    with (root / "cleanup-errors.log").open("a", encoding="utf-8") as stream:
                        stream.write(message)
                    print(f"[{index}/127] {model}: cleanup deferred ({cleanup_error})",
                          flush=True)
        return 0
    finally:
        server.stop()


if __name__ == "__main__":
    raise SystemExit(main())
