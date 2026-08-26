"""codex_exec_common.py — ONE robust way for KDT-side gates to run `codex exec`.

Why this exists: the deep-dive of 2026-07-18 found the codex invocation logic copied (and drifted)
across 7 call sites. The webapp side unified on backend/services/codex_cli.py (version-fenced bin
resolution + pinned gate model/effort). This module is the KDT-side counterpart for EXECUTION:

  - bin/argv policy is IMPORTED from the webapp codex_cli.py (single source: >=0.144 fence,
    -m gpt-5.5 -c model_reasoning_effort=high pins). A minimal local fence exists ONLY for the
    case where the webapp tree is unreadable — same floor, clearly marked, never 0.123.
  - de-nested env (CLAUDECODE* stripped) so codex does not nest inside a calling Claude session.
  - single retry on a TRANSIENT proxy/TLS/stream drop (the #1 real failure: mihomo egress drops
    mid-request), mirroring panel_review.py / _codex_decision semantics.
  - UNCAPPED, STALL-GUARDED execution for promote-path gates (timeout=None): no wall-clock kill —
    a hard timeout kills codex mid-reasoning and truncates the verdict (the codex-no-timeout
    lesson). Instead the process is aborted only when its stdout+stderr stop growing for
    `stall_timeout` seconds (codex streams chrome to stderr while reasoning; sustained total
    silence = proxy wedge / dead stream, cf. the NASA-POWER stall detector).
  - BUDGETED execution (timeout=N) for callers under a wall-clock ceiling (e.g. a panel that must
    finish under the harness Bash cap) — same contract as panel_review._codex_exec_resilient:
    retry only within the remaining budget; a genuine full timeout is NOT retried.

Callers keep their own prompts and verdict parsers. This module never parses verdicts.

Env knobs (all optional):
  KDT_CODEX_BIN       explicit binary path (wins over resolution; still version-fenced unless
                      KDT_CODEX_BIN_TRUST=1)
  KDT_CODEX_STALL_S   uncapped-mode no-progress abort window (default 900)
  KDT_CODEX_HARD_S    uncapped-mode absolute ceiling, safety net only (default 0 = none)
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time

_HYDROCRAFT_WEB = "/mnt/disk1/Hydrocraft_server/Hydrocraft/hydrocraft-web"

# Transient proxy/TLS/stream markers — kept in sync with panel_review.py / research_orchestrator
# (_CODEX_TRANSIENT_MARKERS). If you edit one list, edit all.
TRANSIENT_MARKERS = (
    "reconnecting", "stream disconnected", "stream error", "stream closed",
    "tls", "handshake", "connection reset", "connection closed", "connection refused",
    "econnreset", "proxy", "error sending request", "502 bad gateway", "503 ",
    "temporarily unavailable",
)

MIN_VERSION = (0, 144)  # fallback fence only; canonical floor lives in webapp codex_cli.py


def is_transient(text: str) -> bool:
    t = (text or "").lower()
    return any(m in t for m in TRANSIENT_MARKERS)


def denested_env(base: dict | None = None) -> dict:
    """Copy of the environment with the Claude-session vars stripped, so a codex subprocess does
    not believe it is nested inside the calling agent. Proxy vars are left alone — codex needs
    the egress proxy."""
    env = {**(base if base is not None else os.environ)}
    for k in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT"):
        env.pop(k, None)
    return env


# ── bin/argv resolution: webapp codex_cli.py is the single policy source ─────────────────

def _import_codex_cli():
    try:
        from backend.services import codex_cli as m  # already importable (webapp process)
        return m
    except Exception:
        pass
    try:
        if _HYDROCRAFT_WEB not in sys.path:
            sys.path.insert(0, _HYDROCRAFT_WEB)
        from backend.services import codex_cli as m
        return m
    except Exception:
        return None


def _fallback_version_ok(binp: str) -> bool:
    """Minimal local fence for when the webapp tree is unreadable. Same floor, fail-closed:
    unknown version → refused (never quietly run the 0.123 npm global)."""
    import re
    try:
        r = subprocess.run([binp, "--version"], capture_output=True, text=True, timeout=20)
        m = re.search(r"(\d+)\.(\d+)", (r.stdout or "") + " " + (r.stderr or ""))
        return bool(m) and (int(m.group(1)), int(m.group(2))) >= MIN_VERSION
    except Exception:
        return False


def resolve_codex_bin() -> str | None:
    """Version-fenced codex path, or None. KDT_CODEX_BIN wins (fenced too, unless
    KDT_CODEX_BIN_TRUST=1 for emergencies)."""
    explicit = os.environ.get("KDT_CODEX_BIN")
    if explicit:
        if not os.path.exists(explicit):
            return None
        if os.environ.get("KDT_CODEX_BIN_TRUST") == "1" or _fallback_version_ok(explicit):
            return explicit
        return None
    cli = _import_codex_cli()
    if cli is not None:
        try:
            return cli.codex_bin()
        except Exception:
            pass
    # webapp policy module unreadable → minimal local fence over the same candidate list
    for c in (os.path.expanduser("~/.local/bin/codex"),
              "/home/server/.codex/packages/standalone/current/bin/codex",
              "/usr/local/bin/codex"):
        if os.path.exists(c) and _fallback_version_ok(c):
            return c
    return None


def build_exec_cmd(bin_path: str | None = None, *, sandbox: str | None = None) -> list | None:
    """`codex exec` argv with the pipeline gate pins (model/effort) from webapp codex_cli.py.
    If the webapp module is unreadable, a local argv with the SAME pins is used instead."""
    b = bin_path or resolve_codex_bin()
    if not b:
        return None
    cli = _import_codex_cli()
    if cli is not None:
        try:
            cmd = cli.codex_exec_cmd(b, sandbox=sandbox)
            if cmd:
                return cmd
        except Exception:
            pass
    # Fallback keeps the SAME gate pins as codex_cli.py (codex finding #4: dropping them here would
    # silently regress the gate onto ~/.codex/config.toml defaults when the webapp module is merely
    # import-broken). Values duplicated deliberately — sync with codex_cli.GATE_MODEL/GATE_EFFORT.
    cmd = [b, "exec", "--skip-git-repo-check", "-m", "gpt-5.5",
           "-c", "model_reasoning_effort=high"]
    if sandbox:
        cmd += ["--sandbox", sandbox]
    return cmd


# ── execution ────────────────────────────────────────────────────────────────────────────

def _result(**kw) -> dict:
    base = {"ok": False, "out": "", "err": "", "rc": None, "timed_out": False,
            "stalled": False, "error": None, "bin": None, "attempts": 0, "duration_s": 0.0}
    base.update(kw)
    return base


def _looks_transient(res: dict) -> bool:
    if res["timed_out"] or res["stalled"]:
        return False  # handled separately by mode-specific retry rules
    if res["error"]:
        return is_transient(res["error"])
    if res["rc"] not in (0, None):
        return is_transient(res["err"]) or is_transient(res["out"])
    # rc==0 but empty/transient body: codex sometimes exits 0 after the stream drops.
    # Length-bounded: a long rc==0 reply that merely MENTIONS "proxy"/"tls" is a real answer,
    # not a drop — only a short banner counts as transient.
    body = (res["out"] or "").strip()
    if not body:
        return True
    return len(body) < 500 and is_transient(body)


def _run_budgeted(cmd, prompt, timeout, cwd, env) -> dict:
    t0 = time.monotonic()
    try:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                           timeout=timeout, cwd=cwd, env=env)
        return _result(ok=(r.returncode == 0), out=r.stdout or "", err=r.stderr or "",
                       rc=r.returncode, duration_s=time.monotonic() - t0)
    except subprocess.TimeoutExpired:
        return _result(timed_out=True, duration_s=time.monotonic() - t0)
    except Exception as e:  # noqa: BLE001
        return _result(error=str(e), duration_s=time.monotonic() - t0)


def _run_stall_guarded(cmd, prompt, stall_timeout, hard_timeout, cwd, env) -> dict:
    """Popen with stdout/stderr to temp files; abort only when BOTH stop growing for
    `stall_timeout` s (or the optional `hard_timeout` safety net trips). The child runs in its
    own session so an abort kills the whole process group (codex spawns helpers)."""
    t0 = time.monotonic()
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as fo, \
         tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as fe, \
         tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as fi:
        # Prompt via a temp FILE, not a pipe: a blocking pipe write on a >64 KB prompt (review
        # prompts routinely are) with a non-reading child would hang BEFORE the watchdog loop
        # even starts — the exact unbounded hang this module exists to prevent (codex finding #1).
        fi.write(prompt)
        fi.flush()
        fi.seek(0)
        try:
            p = subprocess.Popen(cmd, stdin=fi, stdout=fo, stderr=fe,
                                 text=True, cwd=cwd, env=env, start_new_session=True)
        except Exception as e:  # noqa: BLE001
            return _result(error=str(e), duration_s=time.monotonic() - t0)

        last_size = -1
        last_progress = time.monotonic()
        stalled = timed_out = False
        while True:
            rc = p.poll()
            if rc is not None:
                break
            now = time.monotonic()
            size = os.fstat(fo.fileno()).st_size + os.fstat(fe.fileno()).st_size
            if size != last_size:
                last_size = size
                last_progress = now
            if now - last_progress > stall_timeout:
                stalled = True
            if hard_timeout and (now - t0) > hard_timeout:
                timed_out = True
            if stalled or timed_out:
                try:
                    os.killpg(p.pid, 15)
                    time.sleep(3)
                    if p.poll() is None:
                        os.killpg(p.pid, 9)
                except Exception:
                    p.kill()
                p.wait()
                break
            time.sleep(2)

        fo.seek(0); fe.seek(0)
        out, err = fo.read(), fe.read()
        rc = p.returncode
        return _result(ok=(not stalled and not timed_out and rc == 0),
                       out=out, err=err, rc=rc, stalled=stalled, timed_out=timed_out,
                       duration_s=time.monotonic() - t0)


def codex_exec(prompt: str, *, timeout: int | None = None, stall_timeout: int | None = None,
               hard_timeout: int | None = None, retries: int = 1, cwd=None,
               sandbox: str | None = None, bin_path: str | None = None) -> dict:
    """Run `codex exec` (prompt on stdin, de-nested env) and return a normalized dict:
      {ok, out, err, rc, timed_out, stalled, error, bin, attempts, duration_s}

    timeout=None → UNCAPPED stall-guarded mode (gates: never kill mid-reasoning; abort only on
      `stall_timeout` s (default KDT_CODEX_STALL_S or 900) of zero output growth, or the
      KDT_CODEX_HARD_S safety ceiling if set). Transient drops AND stalls retry up to `retries`
      times (a stall is almost always a proxy wedge, and there is no budget to protect).
    timeout=N → BUDGETED mode (panel-style): single subprocess.run under N seconds; transient
      drops retry within the REMAINING budget when >=20 s is left; a full timeout is NOT retried.

    Verdict parsing stays with the caller. `ok` means: process completed with rc 0 and was not
    stalled/timed out — it does NOT certify the output is non-transient garbage; callers that
    gate on content should still check `is_transient(res['out'])`.
    """
    cmd = build_exec_cmd(bin_path, sandbox=sandbox)
    if not cmd:
        return _result(error="no codex CLI >= %s.%s found (0.123 npm global is refused)"
                             % MIN_VERSION)
    env = denested_env()
    binp = cmd[0]

    if timeout is not None:
        t0 = time.monotonic()
        res = _run_budgeted(cmd, prompt, timeout, cwd, env)
        attempts = 1
        if _looks_transient(res) and retries > 0:
            remaining = int(timeout - (time.monotonic() - t0))
            if remaining >= 20:
                res = _run_budgeted(cmd, prompt, remaining, cwd, env)
                attempts += 1
        if res["ok"] and _looks_transient(res):
            res["ok"] = False
            res["error"] = "output still transient/empty after %d attempt(s)" % attempts
        res["bin"], res["attempts"] = binp, attempts
        return res

    st = stall_timeout if stall_timeout is not None else int(os.environ.get("KDT_CODEX_STALL_S") or 900)
    ht = hard_timeout if hard_timeout is not None else int(os.environ.get("KDT_CODEX_HARD_S") or 0)
    attempts = 0
    res = _result()
    while attempts <= retries:
        res = _run_stall_guarded(cmd, prompt, st, ht or None, cwd, env)
        attempts += 1
        if res["ok"] and not _looks_transient(res):
            break
        if not (res["stalled"] or _looks_transient(res)):
            break  # real failure (bad rc, exec error) — retrying won't change it
        if attempts > retries:
            break
    if res["ok"] and _looks_transient(res):
        # retries exhausted on a transient/empty rc==0 body — do NOT hand callers ok=True with
        # garbage output they might parse (codex finding #3): the contract is ok ⇒ usable reply.
        res["ok"] = False
        res["error"] = "output still transient/empty after %d attempt(s)" % attempts
    res["bin"], res["attempts"] = binp, attempts
    return res
