#!/usr/bin/env python3
"""
run_wasp_engine.py -- run the REAL US EPA WASP 8.5 engine (waspccli.exe) under WINE.

This is the real-engine path of the WASP KI. tools/run_wasp.py is NOT EPA WASP: it is an
analytic Python surrogate, and this tool never falls back to it.

What it does
  1. Makes a fresh run directory and copies the .wif into it (with --copy-siblings, also the
     other regular files in the .wif's folder; sub-folders and absolute paths inside the .wif
     are NOT handled). The engine runs there, never in the source folder.
  2. Runs  wine C:\\WASP8\\wasp\\bin\\waspccli.exe <model>.wif  in its own session. --timeout is
     ONE budget for engine + extraction (default 900 s, max 1080 s so that process
     cleanup still fits in the 20-min campaign limit). A malformed .wif can make waspccli spin
     forever; on timeout, Ctrl-C or SIGTERM every process of that session is found in /proc and
     killed by explicit PID, then reaped.
  3. Success needs ALL of: no timeout / no signal; the engine line "run successfully closed out";
     <model>.OUT and <model>.BMD2 created by this run (absent before), BMD2 header valid
     (b"BMD2", version 2, segments > 0, variables > 0, variable names readable); and no ERROR
     line except the known "Failed to locate time function" kind (older example files read by
     8.5; their scientific effect is NOT established -- they are counted and reported).
     The wine exit code is recorded but not trusted (waspccli returned 2 on a successful
     official EPA example and 0 after a killed hang).
  4. Optional: extract results from the .BMD2 with EPA's own BMD2_Extract.exe (same install) to
     CSV; the extractor must exit normally and every requested variable x segment must have finite
     numbers for all output times (BMD2_Extract writes all stored times except the last one --
     observed on EPA's examples -- so it must give n_times-1 records each).
  5. Writes a JSON summary (engine banner, exe + extractor sha256, input sha256, checks, stats).

Engine discovery (an invalid explicit setting fails; no fallback; missing engine -> exit 3):
  WINE prefix : --wineprefix -> $WASP_WINEPREFIX -> $WASP_ENGINE_ROOT/wineprefix
                -> KISSPATH_HOME/engine_builds_20261006/wasp/wineprefix (this server's install)
  wine        : --wine       -> $WASP_WINE       -> `wine` on PATH
  engine      : <prefix>/drive_c/WASP8/wasp/bin/waspccli.exe   (C:\\WASP8\\wasp\\bin\\waspccli.exe)

Usage
  python run_wasp_engine.py --wif SteadyState.wif --run-dir run1 --extract-all
  python run_wasp_engine.py --wif model.wif --extract "Dissolved Oxygen" --segments 1,9
  python run_wasp_engine.py --list-variables run1/SteadyState.BMD2

Exit codes: 0 success; 1 run or extraction failed; 2 bad command line; 3 WINE/engine missing.
"""

import argparse
import csv
import datetime as _dt
import hashlib
import json
import math
import os
import re
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DEFAULT_ENGINE_ROOT = "KISSPATH_HOME/engine_builds_20261006/wasp"  # engine build folder (holds wineprefix/)
ENGINE_WIN = r"C:\WASP8\wasp\bin\waspccli.exe"
EXTRACT_WIN = r"C:\WASP8\wasp\bin\BMD2_Extract.exe"
ENGINE_REL = Path("drive_c/WASP8/wasp/bin/waspccli.exe")
EXTRACT_REL = Path("drive_c/WASP8/wasp/bin/BMD2_Extract.exe")
COMPONENTS_REL = Path("drive_c/WASP8/components.xml")
CLOSE_OUT = "run successfully closed out"
KNOWN_ERROR = re.compile(r"^ERROR: Failed to locate time function, isc=\d+ tfindex=\d+\s*$")


def fail(msg, code=1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- engine discovery
def resolve_engine(args):
    """Return (wine, prefix, engine_exe, extract_exe) or exit 3 with a clear message."""
    if args.wineprefix:
        prefix, src_p = args.wineprefix, "--wineprefix"
    elif os.environ.get("WASP_WINEPREFIX"):
        prefix, src_p = os.environ["WASP_WINEPREFIX"], "$WASP_WINEPREFIX"
    elif os.environ.get("WASP_ENGINE_ROOT"):
        prefix, src_p = str(Path(os.environ["WASP_ENGINE_ROOT"]).expanduser() / "wineprefix"), "$WASP_ENGINE_ROOT"
    else:
        prefix, src_p = str(Path(DEFAULT_ENGINE_ROOT) / "wineprefix"), "server default"
    if args.wine:
        wine, src_w = args.wine, "--wine"
    elif os.environ.get("WASP_WINE"):
        wine, src_w = os.environ["WASP_WINE"], "$WASP_WINE"
    else:
        wine, src_w = shutil.which("wine"), "PATH"
    prefix = Path(prefix).expanduser().absolute()
    missing = []
    if not wine or not (Path(wine).is_file() and os.access(wine, os.X_OK)):
        missing.append(f"wine executable not usable ({src_w}): {wine!r}")
    engine = prefix / ENGINE_REL
    if not engine.is_file():
        missing.append(f"WASP engine not found: {engine} (WINE prefix from {src_p})")
    if missing:
        for m in missing:
            print(f"MISSING ENGINE: {m}", file=sys.stderr)
        print("MISSING ENGINE: the real EPA WASP engine is not available; nothing was run. "
              "(tools/run_wasp.py is an analytic surrogate, not a substitute.)", file=sys.stderr)
        sys.exit(3)
    return str(Path(wine).expanduser().absolute()), prefix, engine, prefix / EXTRACT_REL


def installed_version(prefix):
    """WASP component version from the installer's components.xml (e.g. 8.5.0)."""
    try:
        txt = (prefix / COMPONENTS_REL).read_text(errors="replace")
    except OSError:
        return None
    m = re.search(r"<Package>.*?<Version>([^<]+)</Version>", txt, flags=re.S)
    return m.group(1).strip() if m else None


def wine_env(prefix):
    env = dict(os.environ)
    env["WINEPREFIX"] = str(prefix)
    env["WINEDEBUG"] = "-all"
    env.pop("DISPLAY", None)
    return env


# ---------------------------------------------------------------- process control
def _session_pids(sid):
    """PIDs of live processes whose session id is `sid` (read from /proc/<pid>/stat)."""
    pids = []
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            with open(f"/proc/{d}/stat") as f:
                st = f.read()
        except OSError:
            continue
        fields = st[st.rfind(")") + 2:].split()
        # fields[0]=state, [1]=ppid, [2]=pgrp, [3]=session
        if len(fields) > 3 and fields[3] == str(sid) and fields[0] != "Z":
            pids.append(int(d))
    return pids


def _kill_session(sid):
    """Kill every process of our own child's session by explicit PID (TERM, then KILL)."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        pids = _session_pids(sid)
        if not pids:
            return
        for pid in pids:
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass
        for _ in range(30):
            if not _session_pids(sid):
                return
            time.sleep(0.5)


def run_bounded(cmd, cwd, env, timeout, log_path):
    """Run cmd in a new session; on timeout kill that session's PIDs. Returns (rc|None, wall s)."""
    t0 = time.time()
    with open(log_path, "w") as log:
        p = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdout=log, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, start_new_session=True)
        try:
            rc = p.wait(timeout=max(timeout, 0.1))
        except subprocess.TimeoutExpired:
            _kill_session(p.pid)
            try:
                p.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.kill(p.pid, signal.SIGKILL)
                p.wait()
            return None, time.time() - t0
        except BaseException:  # Ctrl-C / SIGTERM (see _on_sigterm): never leave the engine running
            _kill_session(p.pid)
            try:
                p.wait(timeout=30)
            except BaseException:
                pass
            raise
    # wine may leave helper processes of this run's session behind; clean them up by PID
    _kill_session(p.pid)
    return rc, time.time() - t0


def _on_sigterm(signum, frame):
    raise KeyboardInterrupt(f"signal {signum}")


# ---------------------------------------------------------------- BMD2 metadata
def bmd2_header(path):
    """(version, n_segments, n_variables, n_times); raises ValueError if not a supported BMD2 file.
    Header: b"BMD2", int32 version (2), nseg, nvar, (int32), n stored times."""
    with open(path, "rb") as f:
        head = f.read(24)
    if len(head) < 24 or head[:4] != b"BMD2":
        raise ValueError(f"{Path(path).name} is not a BMD2 file (bad signature)")
    ver, nseg, nvar, _x, ntimes = struct.unpack("<5i", head[4:24])
    if ver != 2:
        raise ValueError(f"{Path(path).name}: unsupported BMD2 version {ver} (expected 2)")
    if not (0 < nseg < 10_000_000 and 0 < nvar < 100_000 and 1 < ntimes < 100_000_000):
        raise ValueError(f"{Path(path).name}: implausible header nseg={nseg} nvar={nvar} ntimes={ntimes}")
    return ver, nseg, nvar, ntimes


def bmd2_variables(path):
    """(name, units) list from the BMD2 trailer: NAME <len><str> <int32> UNITS <len><str>."""
    b = Path(path).read_bytes()
    key_name, key_units = b"\x04\x00\x00\x00NAME", b"\x05\x00\x00\x00UNITS"
    out, i = [], 0
    while True:
        i = b.find(key_name, i)
        if i < 0:
            break
        j = i + len(key_name)
        if j + 4 > len(b):
            break
        n = struct.unpack("<i", b[j:j + 4])[0]
        if not 0 < n < 512:
            i = j
            continue
        name = b[j + 4:j + 4 + n]
        k = j + 4 + n + 4  # skip the int32 after the name
        if b[k:k + len(key_units)] == key_units:
            m = k + len(key_units)
            un = struct.unpack("<i", b[m:m + 4])[0] if m + 4 <= len(b) else -1
            units = b[m + 4:m + 4 + un] if 0 <= un < 512 else b""
            out.append((name.decode("latin-1").strip(), units.decode("utf-8", errors="replace").strip()))
            i = m + 4 + max(un, 0)
        else:
            i = j
    return out


# ---------------------------------------------------------------- extraction
def extract(wine, prefix, extract_exe, run_dir, bmd2, variables, segments, timeout, ntimes):
    """Run EPA BMD2_Extract.exe -> CSV; validate it; return (csv_path, stats, extractor rc)."""
    if not extract_exe.is_file():
        fail(f"BMD2_Extract.exe not found at {extract_exe}; cannot extract (the WASP run itself "
             "finished; raw results are in the .BMD2)")
    for v in variables:
        if "'" in v:
            fail(f"variable names containing a quote cannot be passed to BMD2_Extract: {v!r}")
    csv_name = f"{bmd2.stem}_extract.csv"
    csv_path = run_dir / csv_name
    if csv_path.exists():
        fail(f"{csv_path} already exists; refusing to mix old and new extraction", 2)
    ctl = run_dir / "bmd2_extract_control.dat"
    # control format (BMD2_Extract, WASP 8.5): bmd2 file / csv file / 1 = CSV / N segments /
    # N lines "seg,'station'" / M variables / M quoted names (Fortran list-directed reads)
    lines = [bmd2.name, csv_name, "1", str(len(segments))]
    lines += [f"{s},'{s}'" for s in segments]
    lines += [str(len(variables))] + [f"'{v}'" for v in variables]
    ctl.write_text("\n".join(lines) + "\n")
    log_path = run_dir / "bmd2_extract.log"
    rc, _ = run_bounded([wine, EXTRACT_WIN, ctl.name], run_dir, wine_env(prefix), timeout, log_path)
    log = log_path.read_text(errors="replace")
    if rc is None:
        fail(f"BMD2_Extract timed out after {timeout:.0f}s (processes killed); see {log_path}")
    if rc < 0:
        fail(f"BMD2_Extract was killed by signal {-rc}; see {log_path}")
    if "FORTRAN Runtime Error" in log or "BMD2 File Opened" not in log or not csv_path.is_file():
        fail(f"BMD2_Extract failed (rc={rc}); log tail:\n" + "\n".join(log.strip().splitlines()[-6:]))

    with open(csv_path, newline="", errors="replace") as f:
        rows = list(csv.reader(f))
    if len(rows) < 2:
        fail(f"BMD2_Extract wrote no data rows to {csv_path}")
    # known formatting of BMD2_Extract: NUL/space padded names and a trailing empty column
    header = [h.replace("\x00", "").strip() for h in rows[0]]
    idx = {}
    for v in variables:
        if v not in header:
            fail(f"extracted CSV lacks requested variable {v!r}; header = {header}")
        idx[v] = header.index(v)
    data = {}  # (var, seg) -> list of (datetime, value)
    for n, r in enumerate(rows[1:], start=2):
        if not any(c.strip() for c in r):
            continue
        try:
            t = _dt.datetime.strptime(r[0].strip(), "%m/%d/%Y %H:%M")
            seg = int(r[1])
        except (ValueError, IndexError):
            fail(f"{csv_path.name} line {n}: bad time/segment {r[:2]}")
        for v, k in idx.items():
            try:
                x = float(r[k])
            except (ValueError, IndexError):
                fail(f"{csv_path.name} line {n}: non-numeric {v!r} value {r[k:k + 1]}")
            if not math.isfinite(x):
                fail(f"{csv_path.name} line {n}: non-finite {v!r} value {x}")
            data.setdefault((v, seg), []).append((t, x))
    counts = set()
    stats = {}
    for v in variables:
        for s in segments:
            pts = data.get((v, s))
            if not pts:
                fail(f"no extracted data for variable {v!r} segment {s}")
            counts.add(len(pts))
            pts.sort(key=lambda p: p[0])
            vals = [x for _, x in pts]
            stats.setdefault(v, {})[str(s)] = {
                "n": len(pts), "t_first": pts[0][0].isoformat(), "t_last": pts[-1][0].isoformat(),
                "min": min(vals), "max": max(vals), "mean": sum(vals) / len(vals), "final": vals[-1]}
    if counts != {ntimes - 1}:
        fail(f"incomplete extraction: records per variable/segment {sorted(counts)}, expected {ntimes - 1} "
             f"(BMD2 holds {ntimes} times; BMD2_Extract writes all but the last)")
    return csv_path, stats, rc


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(
        description="Run the REAL EPA WASP 8.5 engine (waspccli.exe) under WINE and check it closed out. "
                    "tools/run_wasp.py is an analytic surrogate, not WASP; this tool never falls back to it.")
    ap.add_argument("--wif", help="WASP input file (.wif) to run")
    ap.add_argument("--run-dir", help="run directory; must not exist or be empty "
                                      "(default: a fresh ./wasp_engine_<stem>_<UTC time>_XXXX)")
    ap.add_argument("--copy-siblings", action="store_true",
                    help="also copy the other regular files in the .wif's folder (not sub-folders)")
    ap.add_argument("--wineprefix", help="WINE prefix holding C:\\WASP8 (else $WASP_WINEPREFIX, else "
                                         f"$WASP_ENGINE_ROOT/wineprefix, else {DEFAULT_ENGINE_ROOT}/wineprefix)")
    ap.add_argument("--wine", help="wine executable (else $WASP_WINE, else wine on PATH)")
    ap.add_argument("--timeout", type=float, default=900.0,
                    help="total wall-time budget in s for engine + extraction (default 900, max 1080)")
    ap.add_argument("--extract", action="append", default=[], metavar="VAR",
                    help="BMD2 variable to extract to CSV with EPA BMD2_Extract (repeatable, exact name)")
    ap.add_argument("--extract-all", action="store_true", help="extract every variable of the main .BMD2")
    ap.add_argument("--segments", help="comma list of segment numbers to extract (default: all)")
    ap.add_argument("--allow-engine-errors", action="store_true",
                    help="do not fail on ERROR lines other than the known 'Failed to locate time function' kind "
                         "(they are still counted and reported)")
    ap.add_argument("--summary-json", help="summary path (default <run-dir>/wasp_engine_summary.json)")
    ap.add_argument("--list-variables", metavar="BMD2", help="print the variables of a .BMD2 file and exit")
    args = ap.parse_args()

    if not (math.isfinite(args.timeout) and 0 < args.timeout <= 1080):
        ap.error("--timeout must be a number in (0, 1080] s (20-min campaign limit minus cleanup reserve)")
    signal.signal(signal.SIGTERM, _on_sigterm)
    if args.list_variables:
        p = Path(args.list_variables)
        if not p.is_file():
            fail(f"no such file: {p}", 2)
        try:
            ver, nseg, nvar, ntimes = bmd2_header(p)
        except ValueError as exc:
            fail(str(exc))
        vs = bmd2_variables(p)
        print(json.dumps({"bmd2": str(p), "version": ver, "n_segments": nseg, "n_variables": nvar,
                          "n_times": ntimes,
                          "variables": [{"name": n, "units": u} for n, u in vs]}, indent=2))
        return 0 if len(vs) == nvar else 1
    if not args.wif:
        ap.error("--wif is required (or use --list-variables)")
    if args.extract and args.extract_all:
        ap.error("use --extract or --extract-all, not both")
    if args.segments and not (args.extract or args.extract_all):
        ap.error("--segments is only used with --extract/--extract-all")
    segments_req = None
    if args.segments:
        try:
            segments_req = [int(x) for x in args.segments.split(",") if x.strip()]
        except ValueError:
            ap.error(f"bad --segments {args.segments!r}")
        if not segments_req or min(segments_req) < 1:
            ap.error(f"bad --segments {args.segments!r}")

    wif = Path(args.wif).expanduser().absolute()
    if not wif.is_file():
        fail(f"no such .wif: {wif}", 2)
    wine, prefix, engine, extract_exe = resolve_engine(args)
    stem = wif.stem

    if args.run_dir:
        run_dir = Path(args.run_dir).expanduser().absolute()
        if run_dir.resolve() == wif.parent.resolve():
            fail("--run-dir must not be the .wif's own folder", 2)
        if run_dir.exists() and (not run_dir.is_dir() or any(run_dir.iterdir())):
            fail(f"--run-dir {run_dir} exists and is not an empty directory; use a fresh one", 2)
        run_dir.mkdir(parents=True, exist_ok=True)
    else:
        ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_dir = Path(tempfile.mkdtemp(prefix=f"wasp_engine_{stem}_{ts}_", dir=Path.cwd()))
    if args.copy_siblings:
        for f in wif.parent.iterdir():
            if f.is_file():
                shutil.copy2(f, run_dir / f.name)
    else:
        shutil.copy2(wif, run_dir / wif.name)
    out_f, bmd_f = run_dir / f"{stem}.OUT", run_dir / f"{stem}.BMD2"
    pre = [p.name for p in run_dir.iterdir() if p.suffix.upper() in (".OUT", ".BMD2")]
    if pre:
        fail(f"output files {pre} were copied in from the .wif folder; remove them or drop --copy-siblings", 2)

    print(f"WASP engine : {engine} (wine {wine}, WINEPREFIX {prefix})")
    print(f"Run dir     : {run_dir}")
    log_path = run_dir / "waspccli_stdout.log"
    sj = Path(args.summary_json).expanduser().absolute() if args.summary_json else run_dir / "wasp_engine_summary.json"
    deadline = time.time() + args.timeout
    try:
        rc, wall = run_bounded([wine, ENGINE_WIN, wif.name], run_dir, wine_env(prefix), args.timeout, log_path)
    except KeyboardInterrupt:
        sj.write_text(json.dumps({"tool": "run_wasp_engine.py", "status": "failed",
                                  "problems": ["interrupted (Ctrl-C/SIGTERM); engine processes killed"],
                                  "run_dir": str(run_dir)}, indent=2))
        fail("interrupted; engine processes killed", 1)
    except Exception as exc:  # e.g. OSError starting wine
        sj.write_text(json.dumps({"tool": "run_wasp_engine.py", "status": "failed",
                                  "problems": [f"engine could not be run: {exc!r}"],
                                  "run_dir": str(run_dir)}, indent=2))
        fail(f"engine could not be run: {exc!r}", 1)
    log = log_path.read_text(errors="replace")
    lines = log.splitlines()
    banner = next((l.strip() for l in lines if l.strip().lower().startswith("wasp suite version")), None)
    err_lines = [l.rstrip() for l in lines if l.lstrip().startswith("ERROR")]
    known = [l for l in err_lines if KNOWN_ERROR.match(l.strip())]
    unknown = [l for l in err_lines if not KNOWN_ERROR.match(l.strip())]
    closed = CLOSE_OUT in log

    summary = {
        "tool": "run_wasp_engine.py",
        "engine": {"name": "EPA WASP", "installed_version": installed_version(prefix), "banner": banner,
                   "exe": str(engine), "exe_sha256": sha256(engine), "windows_path": ENGINE_WIN,
                   "wineprefix": str(prefix), "wine": wine},
        "wif": str(wif), "wif_sha256": sha256(wif), "run_dir": str(run_dir), "stdout_log": str(log_path),
        "wall_s": round(wall, 2), "wine_returncode": rc, "timed_out": rc is None, "closed_out": closed,
        "known_time_function_errors": len(known), "other_error_lines": unknown[:20],
        "outputs": sorted(p.name for p in run_dir.iterdir() if p.suffix.upper() in (".OUT", ".BMD2")),
    }
    problems = []
    if rc is None:
        problems.append(f"engine timed out after {args.timeout:.0f}s (processes killed)")
    elif rc < 0:
        problems.append(f"engine killed by signal {-rc}")
    if not closed:
        problems.append(f"engine did not print '{CLOSE_OUT}'")
    if unknown and not args.allow_engine_errors:
        problems.append(f"{len(unknown)} unrecognised ERROR line(s), first: {unknown[0]!r} "
                        "(use --allow-engine-errors only after checking them)")
    for p in (out_f, bmd_f):
        if not (p.is_file() and p.stat().st_size > 0):
            problems.append(f"output {p.name} was not written")
    if not problems:
        try:
            ver, nseg, nvar, ntimes = bmd2_header(bmd_f)
            vs = bmd2_variables(bmd_f)
            if len(vs) != nvar:
                raise ValueError(f"read {len(vs)} variable names but header says {nvar}")
            summary["bmd2"] = {"file": bmd_f.name, "version": ver, "n_segments": nseg, "n_variables": nvar,
                               "n_times": ntimes,
                               "variables": [{"name": n, "units": u} for n, u in vs]}
        except ValueError as exc:
            problems.append(f"BMD2 check failed: {exc}")
    summary["engine_run"] = "closed_out" if not problems else "failed"
    want_extract = bool(args.extract or args.extract_all)
    summary["status"] = ("failed" if problems else ("extracting" if want_extract else "success"))
    summary["problems"] = problems
    sj.write_text(json.dumps(summary, indent=2))
    if problems:
        tail = "\n".join(lines[-10:])
        fail("WASP run FAILED: " + "; ".join(problems) + f"\n--- engine output tail ({log_path}) ---\n{tail}"
             + f"\nSummary: {sj}")

    print(f"WASP run OK : '{CLOSE_OUT}' in {wall:.1f}s (wine rc={rc}; {len(known)} known "
          f"'Failed to locate time function' lines, {len(unknown)} other ERROR lines)")

    if want_extract:
        try:
            names = [v["name"] for v in summary["bmd2"]["variables"]]
            variables = names if args.extract_all else args.extract
            bad = [v for v in variables if v not in names]
            if bad:
                fail(f"unknown variable(s) {bad}; available: {names}", 2)
            nseg = summary["bmd2"]["n_segments"]
            segments = segments_req or list(range(1, nseg + 1))
            out_of_range = [x for x in segments if not 1 <= x <= nseg]
            if out_of_range:
                fail(f"segments {out_of_range} not in 1..{nseg}", 2)
            remaining = deadline - time.time()
            if remaining < 5:
                fail(f"no time left in the --timeout budget for extraction ({remaining:.0f}s)")
            csv_path, stats, xrc = extract(wine, prefix, extract_exe, run_dir, bmd_f, variables, segments,
                                           remaining, summary["bmd2"]["n_times"])
        except (SystemExit, KeyboardInterrupt, Exception) as exc:
            if isinstance(exc, KeyboardInterrupt):
                why = "interrupted (Ctrl-C/SIGTERM); extractor processes killed"
            elif isinstance(exc, SystemExit):
                why = "result extraction failed (engine run itself closed out; see stderr / bmd2_extract.log)"
            else:
                why = f"result extraction failed with {exc!r} (engine run itself closed out)"
            summary["status"] = "failed"
            summary["problems"] = [why]
            sj.write_text(json.dumps(summary, indent=2))
            if isinstance(exc, SystemExit):
                raise
            fail(why, 1)
        summary["extract"] = {"csv": str(csv_path), "tool": EXTRACT_WIN, "tool_sha256": sha256(extract_exe),
                              "tool_returncode": xrc, "segments": segments, "variables": variables,
                              "stats": stats}
        summary["status"] = "success"
        sj.write_text(json.dumps(summary, indent=2))
        print(f"Extracted   : {csv_path}")

    print(f"Summary     : {sj}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
