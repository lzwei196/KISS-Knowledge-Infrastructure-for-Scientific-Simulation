#!/usr/bin/env python3
"""Sequentially exercise GeoForge's installation route for many KIs.

The controller deliberately talks to a running GeoForge HTTP service instead
of importing private setup helpers.  It therefore tests the same request,
streaming, tool-policy, installation probe, and path-recording used by the
desktop UI. It deliberately does not run KI preflights, reference cases,
simulations, project data preparation, or calibration. One model workspace
exists at a time. Evidence is copied out,
then the potentially large source/build/venv tree is removed before the next
model starts.

The evidence directory is never deleted by this program.  It contains the
stream transcript, deterministic status, structured user request (if any),
and one JSONL summary row per attempted KI.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


EVIDENCE_FILES = (
    "status.json",
    "setup-request.json",
    ".geoforge-install.json",
    "kiss.toml",
    "setup-agent.log",
    "installation-test.json",
)


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.+-]", "_", value)[:160] or "model"


def _json_request(url: str, payload: dict | None = None,
                  *, timeout: float = 120.0) -> dict:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        url, data=data, headers=headers,
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read())


def _stream_request(url: str, payload: dict, target: Path,
                    *, timeout: float = 3700.0) -> None:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response, \
            target.open("wb") as output:
        while True:
            block = response.read(65536)
            if not block:
                break
            output.write(block)
            output.flush()


def _directory_size(root: Path) -> int:
    total = 0
    if not root.exists():
        return total
    for path in root.rglob("*"):
        try:
            if path.is_file() and not path.is_symlink():
                total += path.stat().st_size
        except OSError:
            continue
    return total


def _copy_evidence(workspace: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for name in EVIDENCE_FILES:
        source = workspace / name
        if source.is_file():
            shutil.copy2(source, destination / name)


def _read_json_file(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _request_file_state(path: Path) -> tuple[dict, bool, bool]:
    """Return request, file-present, and valid-object flags."""
    if not path.is_file():
        return {}, False, False
    value = _read_json_file(path)
    return value, True, bool(value)


def _compact_error(value: object, limit: int = 1200) -> object:
    """Keep the batch ledger readable even when preflight embeds full JSON."""
    if not isinstance(value, dict):
        return value
    result = dict(value)
    detail = result.get("detail")
    if isinstance(detail, str) and len(detail) > limit:
        result["detail"] = detail[:limit] + "…"
    return result


def _safe_cleanup(workspace: Path, scratch: Path) -> None:
    """Remove exactly one scratch child, even if an agent made it a symlink."""
    scratch = scratch.absolute()
    workspace = workspace.absolute()
    if workspace.parent != scratch or workspace.name in {"", ".", ".."}:
        raise RuntimeError(f"refusing unsafe cleanup target: {workspace}")
    if workspace.is_symlink():
        workspace.unlink()
    elif workspace.exists():
        # Some scientific build tools briefly keep background workers alive
        # after their parent exits.  A worker can recreate a .deps entry while
        # rmtree is walking, yielding ENOTEMPTY.  Retry the same validated
        # scratch child; never broaden the deletion target.
        last_error: OSError | None = None
        for attempt in range(5):
            try:
                shutil.rmtree(workspace)
                return
            except OSError as error:
                last_error = error
                if not workspace.exists():
                    return
                if attempt < 4:
                    time.sleep(1.0)
        assert last_error is not None
        raise last_error


def _completed_models(path: Path) -> set[str]:
    """Return KIs with a scientific/setup result, not transport failures.

    A stopped local server can make every remaining request fail immediately.
    Those controller/HTTP rows are useful evidence, but must stay resumable.
    """
    latest: dict[str, dict] = {}
    terminal_outcomes = {
        "installed",
        "verified",
        "needs_user",
        "invalid_user_request",
        "failed",
    }
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if value.get("model") and value.get("finished_at"):
            latest[str(value["model"])] = value
    return {
        model
        for model, value in latest.items()
        if value.get("outcome") in terminal_outcomes
    }


def _provider_failure(workspace: Path) -> str | None:
    """Recognize when no agent turn actually occurred.

    A long repair can also lose connectivity near its end; that remains the
    scientific attempt's final result. Only an early failure before any tool
    invocation means the KI itself was never tested.
    """
    path = workspace / "setup-agent.log"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    markers = (
        "[DeepSeek (API) failed:",
        "cannot reach https://api.deepseek.com/chat/completions",
        "Kimi Code could not reach its sign-in service",
        "Kimi Code 无法连接认证服务",
    )
    lines = text.splitlines()
    marker_indexes = [
        index
        for index, line in enumerate(lines)
        if any(marker in line for marker in markers)
    ]
    if not marker_indexes:
        return None
    first_marker = marker_indexes[0]
    earlier = lines[:first_marker]
    if first_marker > 12 or any("`> " in line for line in earlier):
        return None
    return lines[first_marker].strip()[:1200]


def _provider_failure_models(evidence: Path) -> set[str]:
    failed = set()
    if not evidence.is_dir():
        return failed
    for model_dir in evidence.iterdir():
        if model_dir.is_dir() and _provider_failure(model_dir):
            failed.add(model_dir.name)
    return failed


def _append_jsonl(path: Path, value: dict) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + "\n")
        stream.flush()


def run(args: argparse.Namespace) -> int:
    models_root = args.models.expanduser().resolve()
    run_root = args.run_root.expanduser().resolve()
    scratch = run_root / "scratch"
    evidence = run_root / "evidence"
    results = run_root / "results.jsonl"
    scratch.mkdir(parents=True, exist_ok=True)
    evidence.mkdir(parents=True, exist_ok=True)

    discovered = sorted(
        path.name for path in models_root.iterdir()
        if path.is_dir() and (path / "SKILL.md").is_file()
    )
    if args.only:
        requested = {value for group in args.only for value in group.split(",") if value}
        lookup = {name.casefold(): name for name in discovered}
        missing = sorted(value for value in requested if value.casefold() not in lookup)
        if missing:
            raise SystemExit(f"unknown KI(s): {', '.join(missing)}")
        discovered = [lookup[value.casefold()] for value in requested]
    skipped = {
        value
        for group in args.skip
        for value in group.split(",")
        if value
    }
    already = set() if args.rerun else _completed_models(results)
    # Old controller versions could classify an unreachable provider as a KI
    # preflight failure. Evidence is authoritative: retry those models.
    already -= _provider_failure_models(evidence)
    queue = [name for name in discovered if name not in already and name not in skipped]
    metadata = {
        "schema_version": 1,
        "created_at": time.time(),
        "base_url": args.base_url,
        "models_root": str(models_root),
        "model_count": len(discovered),
        "queued_count": len(queue),
        "explicitly_skipped": sorted(skipped),
        "provider": args.provider,
        "llm_model": args.llm_model,
        "scope": "installation_only",
        "cleanup": not args.keep_workspaces,
        "minimum_free_gib": args.minimum_free_gib,
    }
    (run_root / "run.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"{args.provider} KI stress run: {len(queue)} queued / {len(discovered)} selected")
    print(f"Evidence: {run_root}")
    for index, model in enumerate(queue, 1):
        free_before = shutil.disk_usage(scratch).free
        if free_before < args.minimum_free_gib * 1024 ** 3:
            row = {
                "model": model,
                "outcome": "stopped_low_disk",
                "free_bytes": free_before,
                "finished_at": time.time(),
            }
            _append_jsonl(results, row)
            print(f"[{index}/{len(queue)}] STOP {model}: free disk below threshold", flush=True)
            return 2

        slug = _slug(model)
        workspace = scratch / slug
        model_evidence = evidence / slug
        model_evidence.mkdir(parents=True, exist_ok=True)
        # A resumed transport failure must not leave a stale error beside a
        # later successful attempt. The append-only JSONL ledger preserves the
        # original failure row.
        stale_controller_error = model_evidence / "controller-error.txt"
        if stale_controller_error.is_file():
            stale_controller_error.unlink()
        started = time.time()
        row: dict = {
            "model": model,
            "started_at": started,
            "free_bytes_before": free_before,
        }
        print(f"[{index}/{len(queue)}] START {model}", flush=True)
        try:
            _json_request(
                args.base_url + "/api/setup-location",
                {
                    "model": model,
                    "path": str(workspace),
                    "installation_mode": "new",
                },
            )
            _stream_request(
                args.base_url + "/api/setup-agent",
                {
                    "model": model,
                    "provider": args.provider,
                    "llm_model": args.llm_model,
                    "installation_only": True,
                },
                model_evidence / "setup-stream.log",
            )
            state = _json_request(
                args.base_url + "/api/setup/" + urllib.parse.quote(model, safe=""),
            )
            (model_evidence / "setup-state.json").write_text(
                json.dumps(state, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            software = state.get("software") or {}
            installation_test = _read_json_file(
                workspace / "installation-test.json"
            )
            # The setup agent writes the authoritative request directly into
            # the workspace.  Some final preflight responses omit it from the
            # immediately-following GET response, so consult both sources.
            file_request, request_file_present, request_file_valid = (
                _request_file_state(workspace / "setup-request.json")
            )
            request = state.get("request") or file_request
            provider_error = _provider_failure(workspace)
            if provider_error:
                outcome = "provider_error"
            elif installation_test.get("usable"):
                outcome = "installed"
            elif request.get("status") == "waiting":
                outcome = "needs_user"
            elif request_file_present and not request_file_valid:
                outcome = "invalid_user_request"
            else:
                outcome = "failed"
            row.update({
                "outcome": outcome,
                "software_state": software.get("state"),
                "installation_state": installation_test.get("state"),
                "installation_summary": installation_test.get("summary"),
                "installation_binary": installation_test.get("binary"),
                "primary_error": _compact_error(software.get("primary_error")),
                "request_kind": request.get("kind"),
                "request_title": request.get("title"),
                "request_file_present": request_file_present,
                "request_file_valid": request_file_valid,
                "provider_error": provider_error,
            })
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", "replace")[:4000]
            row.update({
                "outcome": "http_error",
                "http_status": error.code,
                "error": body,
            })
            (model_evidence / "controller-error.txt").write_text(
                body, encoding="utf-8")
        except Exception as error:  # the batch must continue after one KI
            row.update({
                "outcome": "controller_error",
                "error": f"{type(error).__name__}: {error}",
            })
            (model_evidence / "controller-error.txt").write_text(
                row["error"], encoding="utf-8")
        finally:
            _copy_evidence(workspace, model_evidence)
            row["workspace_bytes"] = _directory_size(workspace)
            row["elapsed_seconds"] = round(time.time() - started, 3)
            if not args.keep_workspaces:
                try:
                    _safe_cleanup(workspace, scratch)
                    row["cleanup"] = "removed"
                except Exception as error:
                    row["cleanup"] = f"failed: {type(error).__name__}: {error}"
            else:
                row["cleanup"] = "kept"
            row["free_bytes_after"] = shutil.disk_usage(scratch).free
            row["finished_at"] = time.time()
            _append_jsonl(results, row)
            print(
                f"[{index}/{len(queue)}] {row.get('outcome', 'unknown').upper()} "
                f"{model} · {row['elapsed_seconds']:.1f}s · "
                f"{row['workspace_bytes'] / 1024 ** 2:.1f} MiB · {row['cleanup']}",
                flush=True,
            )
        if row.get("outcome") == "provider_error":
            print(
                f"STOP: {args.provider} was unreachable before the agent turn; "
                "resume after connectivity returns.",
                flush=True,
            )
            return 3
    return 0


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--base-url", default="http://127.0.0.1:18848")
    value.add_argument("--provider", default="api:deepseek")
    value.add_argument("--llm-model", default="deepseek-chat")
    value.add_argument("--models", type=Path, default=Path("models"))
    value.add_argument("--run-root", type=Path, required=True)
    value.add_argument("--only", action="append", default=[],
                       help="one KI or a comma-separated list; repeatable")
    value.add_argument("--skip", action="append", default=[],
                       help="one KI or a comma-separated list to skip; repeatable")
    value.add_argument("--rerun", action="store_true")
    value.add_argument("--keep-workspaces", action="store_true")
    value.add_argument("--minimum-free-gib", type=float, default=12.0)
    return value


if __name__ == "__main__":
    sys.exit(run(parser().parse_args()))
