#!/usr/bin/env python3
"""
run_gifmod_engine.py -- run the REAL GIFMod engine headless (a PATCHED FORK, see SKILL.md).

Upstream GIFMod (github.com/USEPA/GIFMod) is a Qt GUI with NO command-line run mode. The server
engine is a patched fork of upstream commit 2a31475: build fixes, missing `return` statements
added, and a small headless driver in main.cpp (SKILL.md "Real engine" lists every patch). This
tool drives that driver:

  --wizard T [--param NAME=VALUE ...]  build a model from a GIFMod wizard template, save it, run it
  --script S                           build a model from a GIFMod script (add/connect/setprop lines)
  --model  M.GIFMod                    load a saved GIFMod project and run it

Each run uses a fresh run directory: the model file is saved/copied there and GIFMod writes its
outputs next to the model file. Before launch the tool reads the project/script/template and, using
the engine's own property catalog (GIFModGUIPropList.csv: properties with a filename/directory
delegate), REFUSES (exit 2) one that sets "Working path" to anything but "." (the engine would write
outside the run dir), or whose input-file properties are relative and not in the run dir, or
absolute and missing. Wizard parameters with a filename delegate must be absolute existing files.
With --copy-siblings the other regular files of the script/model folder are copied in (for relative
input files); sub-folders are NOT staged. Absolute input files are read in place (listed in the summary).

A run counts as successful ONLY if ALL hold: engine exit code 0; the driver line
"HEADLESS: run invoked=1 hasResults=1"; temp.log ends the run with "Simulation ended."; every
experiment named in "Solving <exp>" has "<exp> finished" and none has "<exp> failed"; and every
experiment's hydro_output_<exp>.txt exists and parses. (The engine sets hasResults even when an
experiment fails, so the log lines are required.)
Outputs (hydro_output_*, wq_output_*, output_MB*) are parsed from GIFMod's format -- a "names,"
line, a "//t," line, then one (t, value) pair per variable per row; each variable has its own time
axis -- into one long CSV and a JSON summary. Time is GIFMod's Excel-style serial day
(43831 = 2020-01-01). Columns LAI_* are flagged unreliable (uninitialised in the engine; they
differ run to run).

Engine selection (no silent fallback; missing/unpatched/unsupported engine -> exit 3):
  --binary B  -> run B directly    |  --wrapper W -> run W (a gifmod_headless.sh-style script)
  else $GIFMOD_BINARY (direct)     |  else $GIFMOD_HEADLESS (wrapper)
  else the server wrapper KISSPATH_HOME/engine_builds_20261006/gifmod/install/gifmod_headless.sh
A wrapper must follow a literal grammar: a bash/sh shebang, comments, `export NAME=value ...` (plain
characters only) / `unset NAME ...` lines (no OMP_* thread variables) and ONE final line
`exec /absolute/binary "$@"`; anything else is refused, so the binary that is screened and hashed is
the one that runs. That binary must contain the headless
driver (screening check; the run itself is the proof). The engine always gets
QT_QPA_PLATFORM=offscreen LC_ALL=C LANG=C and OMP_NUM_THREADS (--threads, 1-4).

Usage
  python run_gifmod_engine.py --wizard Simple_pond \\
      --param 'project_start_date=1/1/2020 12:00 AM' --param 'project_end_date=1/31/2020 12:00 AM' \\
      --param ini_Depth=1 --param Area=100 --run-dir /scratch/pond_run
  python run_gifmod_engine.py --model /scratch/pond_run/Simple_pond.GIFMod --run-dir /scratch/rerun

Exit codes: 0 success; 1 run failed; 2 bad command line; 3 engine missing or not the headless build.
"""

import argparse
import csv
import datetime as _dt
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DEFAULT_WRAPPER = "KISSPATH_HOME/engine_builds_20261006/gifmod/install/gifmod_headless.sh"
DRIVER_MARK = b"HEADLESS: running forward model"
RESULT_LINE = "HEADLESS: run invoked=1 hasResults=1"
UNRELIABLE = re.compile(r"^LAI_")


def fail(msg, code=1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def has_driver(binary):
    tail = b""
    with open(binary, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            if DRIVER_MARK in tail + chunk:
                return True
            tail = chunk[-len(DRIVER_MARK):]
    return False


# Literal wrapper grammar (no shell operators, expansions or quoting tricks are possible):
_WR_SHEBANG = re.compile(r"^#!(/bin/bash|/bin/sh|/usr/bin/env bash)\s*$")
_WR_EXPORT = re.compile(r"^export( [A-Za-z_][A-Za-z0-9_]*=[A-Za-z0-9_./:,+-]*)+$")
_WR_UNSET = re.compile(r"^unset( [A-Za-z_][A-Za-z0-9_]*)+$")
_WR_EXEC = re.compile(r'^exec (/[A-Za-z0-9_./+-]+) "\$@"$')
_WR_FORBIDDEN_VARS = re.compile(r"^(OMP_|GOMP_|KMP_|OPENBLAS_|MKL_)")


def wrapper_target(wrapper):
    """Binary launched by a strictly literal wrapper, or (None, reason).

    Grammar (whole lines, nothing else): '#!/bin/bash' (or /bin/sh, /usr/bin/env bash) first;
    '#' comments; 'export NAME=value ...' (value chars [A-Za-z0-9_./:,+-]); 'unset NAME ...';
    and exactly one final 'exec /absolute/binary "$@"'. Thread variables (OMP_* etc.) may not be
    set, so the tool's --threads limit always holds."""
    try:
        lines = Path(wrapper).read_text(errors="replace").splitlines()
    except OSError as exc:
        return None, f"cannot read wrapper: {exc}"
    if not lines or not _WR_SHEBANG.match(lines[0]):
        return None, "first line must be #!/bin/bash, #!/bin/sh or #!/usr/bin/env bash"
    body = [l.rstrip() for l in lines[1:] if l.strip() and not l.lstrip().startswith("#")]
    if not body:
        return None, "wrapper has no exec line"
    for l in body[:-1]:
        if _WR_EXPORT.match(l):
            names = [w.split("=", 1)[0] for w in l.split()[1:]]
        elif _WR_UNSET.match(l):
            names = l.split()[1:]
        else:
            return None, f"unsupported wrapper line (only literal export/unset before exec): {l!r}"
        bad = [n for n in names if _WR_FORBIDDEN_VARS.match(n)]
        if bad:
            return None, f"wrapper may not set thread variables {bad} (use --threads)"
    m = _WR_EXEC.match(body[-1])
    if not m:
        return None, f'last line must be exactly: exec /absolute/binary "$@" (found {body[-1]!r})'
    return Path(m.group(1)), ""


def select_engine(args):
    """Return dict(mode, launch, binary, wrapper) or exit 3."""
    if args.binary and args.wrapper:
        fail("give either --binary or --wrapper, not both", 2)
    if args.binary:
        mode, path, src = "direct", args.binary, "--binary"
    elif args.wrapper:
        mode, path, src = "wrapper", args.wrapper, "--wrapper"
    elif os.environ.get("GIFMOD_BINARY"):
        mode, path, src = "direct", os.environ["GIFMOD_BINARY"], "$GIFMOD_BINARY"
    elif os.environ.get("GIFMOD_HEADLESS"):
        mode, path, src = "wrapper", os.environ["GIFMOD_HEADLESS"], "$GIFMOD_HEADLESS"
    else:
        mode, path, src = "wrapper", DEFAULT_WRAPPER, "server default"
    path = Path(path).expanduser().absolute()
    if not (path.is_file() and os.access(path, os.X_OK)):
        fail(f"MISSING ENGINE: {mode} {path} (from {src}) not found or not executable. Nothing was run.", 3)
    if mode == "wrapper":
        binary, why = wrapper_target(path)
        if binary is None:
            fail(f"MISSING ENGINE: wrapper {path} not accepted: {why}. Nothing was run.", 3)
        if not (binary.is_file() and os.access(binary, os.X_OK)):
            fail(f"MISSING ENGINE: wrapper {path} launches {binary}, which is not an executable file. "
                 "Nothing was run.", 3)
    else:
        binary = path
    if not has_driver(binary):
        fail(f"MISSING ENGINE: {binary} has no headless driver (unpatched upstream GIFMod is GUI-only and "
             "would hang). Use the patched build (SKILL.md 'Real engine'). Nothing was run.", 3)
    return {"mode": mode, "source": src, "launch": path, "binary": binary.resolve(),
            "wrapper": path if mode == "wrapper" else None}


def engine_env(threads):
    env = dict(os.environ)
    env.update({"QT_QPA_PLATFORM": "offscreen", "LC_ALL": "C", "LANG": "C",
                "OMP_NUM_THREADS": str(threads)})
    return env


def _session_pids(sid):
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


def _on_sigterm(signum, frame):
    raise KeyboardInterrupt(f"signal {signum}")


def run_bounded(cmd, cwd, env, timeout, log_path):
    t0 = time.time()
    with open(log_path, "w") as log:
        p = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdout=log, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, start_new_session=True)
        try:
            rc = p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_session(p.pid)
            try:
                p.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.kill(p.pid, signal.SIGKILL)
                p.wait()
            return None, time.time() - t0
        except BaseException:  # Ctrl-C / SIGTERM: never leave the engine running
            _kill_session(p.pid)
            try:
                p.wait(timeout=30)
            except BaseException:
                pass
            raise
    _kill_session(p.pid)
    return rc, time.time() - t0


_PROP = re.compile(r"([^\x00#$]{1,80})\$\$\$([^\x00#$]{1,80})\$\$\$([^\x00#$]{0,2048})")
OUTPUT_FILE_CODES = {"outputfile", "mcmcoutputfile"}  # GA/MCMC outputs: not used by a forward run


def file_catalog(engine_dir):
    """{lowercase display name or code: info} for every property whose delegate in the engine's own
    GIFModGUIPropList.csv is 'filename...' or 'directory'.
    info = {"display", "role" (workdir | output | input), "file_types" (entity types where it is a file),
            "flag_values" (values the same name takes as a NON-file property elsewhere, e.g. Yes/No)}."""
    cat, other, file_rows = {}, {}, []
    with open(Path(engine_dir) / "GIFModGUIPropList.csv", newline="", errors="replace") as f:
        for row in csv.reader(f):
            if len(row) < 11 or row[0].startswith("//"):
                continue
            etype, name, code, ptype = row[2].strip(), row[5].strip(), row[6].strip(), row[9].strip().lower()
            if ptype.startswith("filename") or ptype == "directory":
                file_rows.append((etype, name, code))
            else:
                vals = {v.strip().lower() for v in row[10].split(";") if v.strip() and v.strip() != "!"}
                for k in (name.lower(), code.lower()):
                    other.setdefault(k, set()).update(vals)
    for etype, name, code in file_rows:
        role = "workdir" if code == "path" else ("output" if code in OUTPUT_FILE_CODES else "input")
        info = cat.setdefault(name.lower(), {"display": name, "role": role, "file_types": set(), "flag_values": None})
        info["file_types"].add(etype.lower())
        if name.lower() in other:
            # e.g. 'Solar-radiation': a file for Climate settings, a Yes/No flag on blocks
            info["flag_values"] = other[name.lower()]
        # a code is a key only if no non-file property shares it
        # (code 'precipitation' is also the Yes/No block property 'Precipitation')
        if code and code.lower() not in other and code.lower() not in cat:
            cat[code.lower()] = info
    return cat


def project_properties(path):
    """(experiment, key, value) triples stored in a saved .GIFMod project.

    GIFMod saves entity properties as UTF-16 text 'experiment$$$key$$$value###...'
    (alignment varies, so both byte offsets are decoded)."""
    b = Path(path).read_bytes()
    out = set()
    for off in (0, 1):
        txt = b[off:].decode("utf-16-be", errors="replace")
        for m in _PROP.finditer(txt):
            out.add((m.group(1).strip(), m.group(2).strip(), m.group(3).strip()))
    return sorted(out)


def script_properties(path):
    """(entity type or None, key, value) from GIFMod script lines like:
    add 'Pond' :Name=Pond,Inflow time series=a.txt   /   setprop 'Climate settings' :Temperature=t.csv"""
    out = []
    for line in Path(path).read_text(errors="replace").splitlines():
        if ":" not in line:
            continue
        head, props = line.split(":", 1)
        mt = re.search(r"'([^']*)'", head)
        etype = mt.group(1).strip().lower() if mt else None
        for kv in props.split(","):
            if "=" in kv:
                k, v = kv.split("=", 1)
                out.append((etype, k.strip(), v.strip()))
    return out


_WIZ_KINDS = {"settings", "major_block", "major_connection", "entity", "change_property", "criteria"}


def _wiz_params(txt):
    """{name: {field: value}} of the 'parameter:' lines of a wizard template."""
    params = {}
    for line in txt.splitlines():
        if line.split(":")[0].strip().lower() != "parameter" or ":" not in line:
            continue
        f = {}
        for kv in _between(line.split(":", 1)[1]).split(","):
            if "=" in kv:
                k, v = kv.split("=", 1)
                f[k.strip().lower()] = v.strip()
        if f.get("name"):
            params[f["name"]] = f
    return params


def _between(seg):
    """Engine's extract_between(seg, '{', '}'): from after the first '{' to the next '}' (or the end)."""
    first = seg.find("{")
    last = seg.find("}", first + 1)
    return seg[first + 1:] if last < 0 else seg[first + 1:last]


def wizard_assignments(path, answers):
    """(entity type or None, key, effective value) exactly as the engine's wizard reader parses lines
    (Wizard_Script_Reader::add_command + wiz_entity + wiz_assigned_value): kind = text before the first
    ':', for kinds settings/major_block/major_connection/entity/change_property/criteria the text between
    the first and second ':' is cut to '{...}' and split on ','. value[x] -> x; param[p] -> the answer
    for p, else its template default; expression[...] -> skipped (numeric); plain text -> literal.
    Text after '}' (e.g. '// comment') is ignored, as by the engine."""
    txt = Path(path).read_text(errors="replace")
    params = _wiz_params(txt)
    out = []
    for line in txt.splitlines():
        parts = line.split(":")
        if len(parts) < 2 or parts[0].strip().lower() not in _WIZ_KINDS:
            continue
        items = []
        for kv in _between(parts[1]).split(","):
            sp = kv.split("=")
            if len(sp) < 2:
                continue
            key, rhs = sp[0].strip(), sp[1]
            br = rhs.split("[")
            if len(br) == 1:
                value = rhs.strip().split(";")[0]
            elif len(br) == 2 and br[0].strip().lower() == "value":
                value = br[1].split("]")[0].strip().split(";")[0]
            elif len(br) == 2 and br[0].strip().lower() == "param":
                name = _between(rhs.strip().replace("[", "{", 1).replace("]", "}", 1)).strip()
                value = answers.get(name, params.get(name, {}).get("default", ""))
            else:
                continue  # expression[...] or syntax the engine rejects
            items.append((key, value.strip()))
        etype = next((v.lower() for k, v in items if k.lower() == "type"), None)
        out.extend((etype, k, v) for k, v in items)
    return out


def wizard_file_params(path, answers):
    """(param, value) for wizard parameters whose delegate is 'filename' (answer, else template default)."""
    out = []
    for name, f in _wiz_params(Path(path).read_text(errors="replace")).items():
        if f.get("delegate", "").lower().startswith("filename"):
            out.append((name, answers.get(name, f.get("default", ""))))
    return out


def check_staging(kind, staged_file, run_dir, catalog, answers):
    """Refuse inputs that would write outside run_dir or read missing files (before launch).
    Returns (problems, absolute input files read in place)."""
    problems, external = [], []

    def is_file_here(info, etype, value):
        """Decide whether this occurrence is the FILE property (names shared with flags need context)."""
        if info["flag_values"] is None:
            return True
        if etype is not None:  # script/wizard: entity type known
            return etype in info["file_types"]
        return value.strip().lower() not in info["flag_values"]  # saved project: no type, use the value

    def check_input(label, value, allow_relative=True):
        if not value or value.startswith("%compacted%"):
            return
        v = Path(value)
        if v.is_absolute():
            if not v.is_file():
                problems.append(f"input file '{value}' ({label}) does not exist")
            else:
                external.append(value)
        elif not allow_relative:
            problems.append(f"input file '{value}' ({label}) must be an absolute path")
        elif not (run_dir / v).is_file():
            problems.append(f"relative input file '{value}' ({label}) is not in the run dir "
                            f"(use --copy-siblings, or absolute paths)")

    if kind == "wizard":
        for name, value in wizard_file_params(staged_file, answers):
            check_input(f"wizard parameter {name}", value, allow_relative=False)
        entries = [(etype, k, v, False) for etype, k, v in wizard_assignments(staged_file, answers)]
    elif kind == "script":
        entries = [(etype, k, v, True) for etype, k, v in script_properties(staged_file)]
    else:
        entries = [(None, k, v, True) for _exp, k, v in project_properties(staged_file)]
    for etype, key, value, rel_ok in entries:
        info = catalog.get(key.lower())
        if not info or not is_file_here(info, etype, value):
            continue
        if info["role"] == "workdir":
            if value != ".":
                problems.append(f"{kind} sets {info['display']} to '{value}'; only '.' (the model's folder = "
                                f"run dir) is allowed, otherwise GIFMod writes outside the run dir")
        elif info["role"] == "input":
            check_input(f"{kind} {info['display']}", value, allow_relative=rel_ok)
    return problems, sorted(set(external))


def _split_names(line):
    """Split a 'names,' header on commas outside parentheses (grid names look like 'S_Catchment (1,2)')."""
    out, cur, depth = [], [], 0
    for ch in line:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(depth - 1, 0)
        if ch == "," and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def parse_pairs(path):
    """GIFMod output: 'names, a, b,' / '//t, a, t, b,' / rows of (t, value) pairs.
    Returns {name: [(t, v), ...]}. Raises ValueError on malformed content."""
    lines = path.read_text(errors="replace").splitlines()
    if not lines or not lines[0].lower().startswith("names"):
        raise ValueError(f"{path.name}: first line is not a 'names,' header")
    names = [n.strip() for n in _split_names(lines[0])[1:] if n.strip()]
    if not names:
        return {}  # e.g. wq_output of a model without constituents ('names,' then '//')
    series = {n: [] for n in names}
    for ln_no, ln in enumerate(lines[1:], start=2):
        if not ln.strip() or ln.startswith("//"):
            continue
        parts = [p.strip() for p in ln.split(",")]
        if parts and parts[-1] == "":
            parts = parts[:-1]
        if len(parts) > 2 * len(names):
            raise ValueError(f"{path.name} line {ln_no}: {len(parts)} fields for {len(names)} variables")
        for k, n in enumerate(names):
            pair = parts[2 * k:2 * k + 2]
            if not pair or all(x == "" for x in pair):
                continue  # this variable's series has ended
            if len(pair) != 2:
                raise ValueError(f"{path.name} line {ln_no}: incomplete (t, value) pair for {n}")
            try:
                t, v = float(pair[0]), float(pair[1])
            except ValueError:
                raise ValueError(f"{path.name} line {ln_no}: non-numeric pair {pair} for {n}")
            if not (math.isfinite(t) and math.isfinite(v)):
                raise ValueError(f"{path.name} line {ln_no}: non-finite pair {pair} for {n}")
            series[n].append((t, v))
    return series


def main():
    ap = argparse.ArgumentParser(
        description="Run the real GIFMod engine headless (patched fork with a headless driver) and check it finished.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--wizard", help="wizard template: a .wiz path, or a bare name in <engine dir>/templates/")
    src.add_argument("--script", help="GIFMod script file (one command per line: add/connect/setprop ...)")
    src.add_argument("--model", help="saved GIFMod project (.GIFMod) to load and run")
    ap.add_argument("--param", action="append", default=[], metavar="NAME=VALUE",
                    help="wizard answer (repeatable); template defaults fill the rest")
    ap.add_argument("--save", help="file NAME (no folder) for the built model in the run dir "
                                   "(default <stem>.GIFMod; wizard/script only)")
    ap.add_argument("--run-dir", help="run directory; must not exist or be empty "
                                      "(default: fresh ./gifmod_engine_<stem>_<UTC time>_XXXX)")
    ap.add_argument("--copy-siblings", action="store_true",
                    help="also copy the other regular files in the script/model folder into the run dir")
    ap.add_argument("--binary", help="patched GIFMod binary to run directly (else see --wrapper / env)")
    ap.add_argument("--wrapper", help=f"headless wrapper script (default {DEFAULT_WRAPPER})")
    ap.add_argument("--threads", type=int, default=4, help="OMP_NUM_THREADS for the engine, 1-4 (default 4)")
    ap.add_argument("--timeout", type=float, default=900.0, help="engine wall-time limit in s, max 1080 (default 900)")
    ap.add_argument("--summary-json", help="summary path (default <run-dir>/gifmod_engine_summary.json)")
    args = ap.parse_args()

    for kv in args.param:
        if "=" not in kv or not kv.split("=", 1)[0].strip():
            ap.error(f"--param must be NAME=VALUE, got {kv!r}")
    if args.param and not args.wizard:
        ap.error("--param is only used with --wizard")
    if args.save and args.model:
        ap.error("--save is not used with --model (the project is copied into the run dir and run there)")
    if args.save and (Path(args.save).name != args.save or not args.save.strip()):
        ap.error("--save must be a plain file name; the model is always saved inside the run dir")
    if args.copy_siblings and args.wizard:
        ap.error("--copy-siblings is for --script/--model")
    if not 1 <= args.threads <= 4:
        ap.error("--threads must be 1..4 (campaign limit)")
    if not (math.isfinite(args.timeout) and 0 < args.timeout <= 1080):
        ap.error("--timeout must be a number in (0, 1080] s (20-min campaign limit minus cleanup reserve)")
    signal.signal(signal.SIGTERM, _on_sigterm)

    eng = select_engine(args)
    templates = eng["binary"].parent / "templates"

    if args.wizard:
        w = Path(args.wizard).expanduser()
        if not w.is_file():
            cand = templates / (args.wizard if args.wizard.endswith(".wiz") else args.wizard + ".wiz")
            if not cand.is_file():
                fail(f"wizard template not found: {args.wizard} (also looked in {templates})", 2)
            w = cand
        src_file, stem = w.resolve(), w.stem
    else:
        src_file = Path(args.script or args.model).expanduser().resolve()
        if not src_file.is_file():
            fail(f"no such file: {src_file}", 2)
        stem = src_file.stem

    if args.run_dir:
        run_dir = Path(args.run_dir).expanduser().resolve()
        if run_dir.exists() and (not run_dir.is_dir() or any(run_dir.iterdir())):
            fail(f"--run-dir {run_dir} exists and is not an empty directory; use a fresh one", 2)
        if not args.wizard and run_dir == src_file.parent:
            fail("--run-dir must not be the input file's own folder", 2)
        run_dir.mkdir(parents=True, exist_ok=True)
    else:
        ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_dir = Path(tempfile.mkdtemp(prefix=f"gifmod_engine_{stem}_{ts}_", dir=Path.cwd()))

    if args.copy_siblings:
        for f in src_file.parent.iterdir():
            if f.is_file():
                shutil.copy2(f, run_dir / f.name)
        stale = [p.name for p in run_dir.iterdir() if re.match(r"(hydro_output_|wq_output_|output_MB|temp\.log)", p.name)]
        if stale:
            fail(f"GIFMod output files {stale} were copied in from the input folder; clean that folder "
                 "or drop --copy-siblings", 2)

    cmd = [str(eng["launch"])]
    if args.model:
        local = run_dir / src_file.name
        if not local.exists():
            shutil.copy2(src_file, local)
        cmd += ["--model", str(local)]
        model_file = local
    else:
        model_file = run_dir / (args.save or f"{stem}.GIFMod")
        if args.wizard:
            cmd += ["--wizard", str(src_file)]
            for kv in args.param:
                cmd += ["--param", kv]
        else:
            local = run_dir / src_file.name
            if not local.exists():
                shutil.copy2(src_file, local)
            cmd += ["--script", str(local)]
        cmd += ["--save", str(model_file)]

    staged = (run_dir / src_file.name) if not args.wizard else src_file
    answers = {kv.split("=", 1)[0].strip(): kv.split("=", 1)[1].strip() for kv in args.param}
    try:
        catalog = file_catalog(eng["binary"].parent)
    except OSError as exc:
        fail(f"MISSING ENGINE: cannot read the engine's property catalog: {exc}", 3)
    stage_problems, external_inputs = check_staging(
        "model" if args.model else ("script" if args.script else "wizard"), staged, run_dir, catalog, answers)
    if stage_problems:
        fail("input cannot be run safely in the run dir: " + "; ".join(stage_problems), 2)

    print(f"GIFMod engine: {eng['binary']} ({eng['mode']} via {eng['launch']}; from {eng['source']})")
    print(f"Run dir      : {run_dir}")
    log_path = run_dir / "gifmod_stdout.log"
    sj = Path(args.summary_json).expanduser().resolve() if args.summary_json else run_dir / "gifmod_engine_summary.json"
    try:
        rc, wall = run_bounded(cmd, run_dir, engine_env(args.threads), args.timeout, log_path)
    except KeyboardInterrupt:
        sj.write_text(json.dumps({"tool": "run_gifmod_engine.py", "status": "failed",
                                  "problems": ["interrupted (Ctrl-C/SIGTERM); engine processes killed"],
                                  "run_dir": str(run_dir)}, indent=2))
        fail("interrupted; engine processes killed", 1)
    except Exception as exc:  # e.g. OSError starting the engine
        sj.write_text(json.dumps({"tool": "run_gifmod_engine.py", "status": "failed",
                                  "problems": [f"engine could not be run: {exc!r}"],
                                  "run_dir": str(run_dir)}, indent=2))
        fail(f"engine could not be run: {exc!r}", 1)
    log = log_path.read_text(errors="replace")
    loglines = log.splitlines()
    headless = [l for l in loglines if l.startswith("HEADLESS:")]
    defaults = [l[len("DEFAULT: "):] for l in loglines if l.startswith("DEFAULT: ")]
    temp_log = run_dir / "temp.log"
    tl = temp_log.read_text(errors="replace") if temp_log.is_file() else ""
    experiments = re.findall(r"Solving (\S.*?)\s*$", tl, flags=re.M)
    finished = [e for e in experiments if re.search(rf"{re.escape(e)} finished\s*$", tl, flags=re.M)]
    failed_exp = re.findall(r"(\S.*?) failed, \((.*)\)", tl)
    m = re.search(r"====\s*(\d+)\s*Errors,\s*(\d+)\s*Warnings", tl)

    summary = {
        "tool": "run_gifmod_engine.py",
        "engine": {"name": "GIFMod, patched fork of USEPA/GIFMod 2a31475 (headless driver)",
                   "mode": eng["mode"], "source": eng["source"], "launch": str(eng["launch"]),
                   "binary": str(eng["binary"]), "binary_sha256": sha256(eng["binary"]),
                   "wrapper_sha256": sha256(eng["wrapper"]) if eng["wrapper"] else None},
        "input": {"kind": "wizard" if args.wizard else ("script" if args.script else "model"),
                  "file": str(src_file), "sha256": sha256(src_file),
                  "answers": args.param, "template_defaults_used": defaults,
                  "external_input_files": external_inputs},
        "model_file": str(model_file), "command": cmd, "run_dir": str(run_dir), "stdout_log": str(log_path),
        "threads": args.threads, "wall_s": round(wall, 2), "returncode": rc, "timed_out": rc is None,
        "headless_lines": headless, "experiments": experiments, "experiments_finished": finished,
        "experiments_failed": [{"experiment": e, "reason": r} for e, r in failed_exp],
        "check_errors": int(m.group(1)) if m else None, "check_warnings": int(m.group(2)) if m else None,
    }
    problems = []
    if rc is None:
        problems.append(f"engine timed out after {args.timeout}s (processes killed)")
    elif rc != 0:
        problems.append(f"engine exit code {rc} (driver: 2 cannot load/open input, 3 wizard errors, 4 no results)")
    if RESULT_LINE not in log:
        problems.append(f"no '{RESULT_LINE}' line")
    if not tl:
        problems.append("no temp.log written")
    elif "Simulation ended." not in tl:
        problems.append("temp.log has no 'Simulation ended.'")
    if tl and not experiments:
        problems.append("temp.log names no solved experiment")
    for e in experiments:
        if e not in finished:
            problems.append(f"experiment '{e}' did not finish")
    for e, r in failed_exp:
        problems.append(f"experiment '{e}' failed: {r}")

    stats, unreliable = {}, []
    csv_path = run_dir / "gifmod_outputs_long.csv"
    if not problems:
        with open(csv_path, "w", newline="") as fo:
            wr = csv.writer(fo)
            wr.writerow(["experiment", "family", "file", "variable", "t_serial_day", "value"])
            for e in experiments:
                for family, fname in (("hydro", f"hydro_output_{e}.txt"), ("wq", f"wq_output_{e}.txt"),
                                      ("mass_balance", f"output_MB{e}.txt")):
                    f = run_dir / fname
                    if not f.is_file():
                        if family == "hydro":
                            problems.append(f"{fname} not written in the run dir (does the project set its own output path?)")
                        continue
                    try:
                        series = parse_pairs(f)
                    except ValueError as exc:
                        problems.append(f"cannot parse {fname}: {exc}")
                        continue
                    if family == "hydro" and not any(series.values()):
                        problems.append(f"{fname} has no data")
                    for name, pts in series.items():
                        for t, v in pts:
                            wr.writerow([e, family, fname, name, repr(t), repr(v)])
                        if pts:
                            vals = [v for _, v in pts]
                            rec = {"n": len(pts), "t_first": pts[0][0], "t_last": pts[-1][0],
                                   "min": min(vals), "max": max(vals), "mean": sum(vals) / len(vals),
                                   "final": vals[-1]}
                            if UNRELIABLE.match(name):
                                rec["unreliable"] = "uninitialised in the engine; differs run to run"
                                unreliable.append(f"{e}/{family}/{name}")
                            stats.setdefault(e, {}).setdefault(family, {})[name] = rec

    summary.update({"status": "success" if not problems else "failed", "problems": problems,
                    "parsed_csv": str(csv_path) if not problems else None, "stats": stats,
                    "unreliable_variables": unreliable,
                    "outputs": sorted(p.name for p in run_dir.iterdir() if p.is_file())})
    sj.write_text(json.dumps(summary, indent=2))
    if problems:
        tail = "\n".join(headless[-6:] or loglines[-10:])
        fail("GIFMod run FAILED: " + "; ".join(problems) + f"\n--- engine output ({log_path}) ---\n{tail}"
             + f"\nSummary: {sj}")
    print(f"GIFMod run OK : {RESULT_LINE}; finished: {', '.join(finished)} ({wall:.1f}s)")
    print(f"Parsed        : {csv_path}")
    print(f"Summary       : {sj}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
