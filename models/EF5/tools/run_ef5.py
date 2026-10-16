#!/usr/bin/env python3
"""
run_ef5.py — Execute EF5 with preflight validation and output checking.

Wraps the EF5 binary with:
  1. Pre-flight validation of control file, grids, and forcing data
  2. Execution with timeout and output capture
  3. Post-run validation of output files

Pipeline: validate config → check grids → check forcing → run binary → validate output
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration parser (lightweight)
# ---------------------------------------------------------------------------
def engine_dir(control_path):
    """Directory EF5 runs in (run_ef5 uses the control file's folder as cwd)."""
    return os.path.dirname(os.path.abspath(control_path))


def resolve_path(path, control_path):
    """Resolve a control-file path the way EF5 sees it: relative to the engine cwd."""
    if not path or os.path.isabs(path):
        return path
    return os.path.join(engine_dir(control_path), path)


def executed_task_names(sections):
    """Lower-case names of the tasks listed by TASK= in [Execute] (empty list if none)."""
    names = []
    for sec in sections.values():
        if sec.get("_type") == "execute":
            names.extend(n.strip().lower() for n in sec.get("_tasks", []))
    return names


def _engine_tokens(text):
    """Tokenise a control file exactly like EF5's Config.cpp state machine: comments ('//', '#',
    and '/* ... */') start only where a new token may start (never inside a key or value);
    '[name value]' is a section header; a key runs to '='; a value ends at space, CR or LF.
    Yields ('section', name, value) and ('kv', key, value)."""
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if text.startswith("//", i) or c == "#":
            j = text.find("\n", i)
            i = n if j < 0 else j + 1
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        elif c in " \t\r\n":
            i += 1
        elif c == "[":
            j = i + 1
            while j < n and text[j] not in "]\n":
                j += 1
            body = text[i + 1:j]
            name, _, val = body.partition(" ")
            yield ("section", name, val.replace("\r", ""))
            i = j + 1
        else:
            j = i
            while j < n and text[j] not in "=\n":
                j += 1
            key = text[i:j]
            if j >= n or text[j] == "\n":       # engine: invalid key -> config error; skip it here
                i = j + 1
                continue
            k = j + 1
            while k < n and text[k] not in " \r\n":
                k += 1
            yield ("kv", key, text[j + 1:k])
            i = k


def parse_control_file(control_path):
    """
    Parse EF5 control.txt into a dict of sections, with EF5's own comment and token rules.

    Returns dict: {"<section_type>:<section_name>": {key: value, "_type", "_name", ...}}
    """
    sections = {}
    current_section = None
    current_name = None
    with open(control_path, "r", errors="ignore") as f:
        text = f.read()
    for kind, a, b in _engine_tokens(text):
        if kind == "section":
            current_section = a.strip().lower()
            current_name = b.strip()
            key = f"{current_section}:{current_name}"
            sections[key] = {"_type": current_section, "_name": current_name}
            continue
        if current_section is None:
            continue
        k = a.strip().lower()
        v = b.strip()
        key = f"{current_section}:{current_name}"
        sections[key][k] = v
        if current_section == "execute" and k == "task":
            # [Execute] may repeat TASK=; keep every one (a dict key keeps only the last)
            sections[key].setdefault("_tasks", []).append(v)
        if current_section == "basin" and k == "gauge":
            # [Basin] lists one GAUGE= per line; keep them all
            sections[key].setdefault("_gauges", []).append(v)
    return sections


def preflight_check(control_path, binary_path):
    """
    Validate configuration and data files before running EF5.

    Returns (ok: bool, messages: list[str])
    """
    messages = []
    errors = []

    # Check binary
    if not os.path.isfile(binary_path):
        errors.append(f"EF5 binary not found: {binary_path}")
    elif not os.access(binary_path, os.X_OK):
        errors.append(f"EF5 binary not executable: {binary_path}")

    # Check control file
    if not os.path.isfile(control_path):
        errors.append(f"Control file not found: {control_path}")
        return False, errors

    sections = parse_control_file(control_path)

    # Check [Basic] section
    basic_key = None
    for k in sections:
        if k.startswith("basic:"):
            basic_key = k
            break

    if not basic_key:
        errors.append("Missing [Basic] section in control file")
    else:
        basic = sections[basic_key]
        for grid in ["dem", "ddm", "fam"]:
            path = resolve_path(basic.get(grid, ""), control_path)
            if not path:
                errors.append(f"Missing {grid.upper()} path in [Basic]")
            elif not os.path.isfile(path):
                errors.append(f"{grid.upper()} file not found: {path}")
            else:
                messages.append(f"[OK] {grid.upper()}: {path}")

        proj = basic.get("proj", "").lower()
        if proj not in ["geographic", "laea", ""]:
            errors.append(f"Unknown projection: {proj}. Use 'geographic' or 'laea'")

        esri_ddm = basic.get("esriddm", "").lower()
        if esri_ddm and esri_ddm not in ["true", "false"]:
            errors.append(f"ESRIDDM must be true or false, got: {esri_ddm}")

    # Check forcing sections
    for key, sec in sections.items():
        sec_type = sec.get("_type", "")
        if sec_type in ["precipforcing", "petforcing", "tempforcing"]:
            loc = resolve_path(sec.get("loc", ""), control_path)
            if loc and not os.path.isdir(loc):
                errors.append(f"Forcing directory not found: {loc} (section {key})")
            elif loc:
                messages.append(f"[OK] {sec_type} dir: {loc}")

            unit = sec.get("unit", "")
            if unit:
                messages.append(f"  Unit: {unit}")
                # Check for common unit traps
                if sec_type == "precipforcing" and unit.lower() == "mm/m":
                    errors.append(
                        f"UNIT=mm/m means mm/month — did you mean mm/h (mm per hour)? "
                        f"'m' = month, 'u' = minute in EF5 time units!"
                    )

    # Check gauge sections
    gauge_count = 0
    for key, sec in sections.items():
        if sec.get("_type") == "gauge":
            gauge_count += 1
            lon = sec.get("lon")
            lat = sec.get("lat")
            if lon and lat:
                try:
                    lon_f = float(lon)
                    lat_f = float(lat)
                    if abs(lat_f) > 90:
                        errors.append(f"Gauge {sec['_name']}: LAT={lat_f} out of range [-90,90]")
                    if abs(lon_f) > 180:
                        errors.append(f"Gauge {sec['_name']}: LON={lon_f} out of range [-180,180]")
                except ValueError:
                    errors.append(f"Gauge {sec['_name']}: invalid LON/LAT")

    if gauge_count == 0:
        errors.append("No [Gauge] sections found in control file")
    else:
        messages.append(f"[OK] {gauge_count} gauge(s) defined")

    # Check task sections
    task_count = 0
    for key, sec in sections.items():
        if sec.get("_type") == "task":
            task_count += 1
            style = sec.get("style", "").upper()
            model = sec.get("model", "").upper()
            routing = sec.get("routing", "").upper()

            valid_styles = ["SIMU", "SIMU_RP", "CALI_DREAM", "CALI_ARS", "CLIP_BASIN", "CLIP_GAUGE", "BASIN_AVG"]
            if style and style not in valid_styles:
                errors.append(f"Task {sec['_name']}: unknown STYLE={style}")

            valid_models = ["CREST", "SAC", "HYMOD", "HP"]
            if model and model not in valid_models:
                errors.append(f"Task {sec['_name']}: unknown MODEL={model}")

            valid_routes = ["KW", "LR", ""]
            if routing and routing not in valid_routes:
                errors.append(f"Task {sec['_name']}: unknown ROUTING={routing}")

            # Check time format the way EF5 reads it (TimeVar::LoadTime; date-only = midnight is valid)
            for tkey in ["time_begin", "time_warmend", "time_end"]:
                if tkey in sec:
                    try:
                        _parse_ef5_time(sec.get(tkey))
                    except TimeParseError as ex:
                        errors.append(f"Task {sec['_name']}: {tkey}: {ex}")

            # Check timestep unit
            ts = sec.get("timestep", "")
            if ts:
                unit_char = ts[-1] if ts else ""
                if unit_char == "m":
                    messages.append(
                        f"[WARNING] Task {sec['_name']}: TIMESTEP={ts} — 'm' means MONTHS. "
                        f"For minutes use 'u' (e.g. 5u = 5 minutes)"
                    )

            output_dir = resolve_path(sec.get("output", ""), control_path)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
                messages.append(f"[OK] Output dir: {output_dir}")

    # Check [Execute] section
    has_execute = any(sec.get("_type") == "execute" for sec in sections.values())
    if not has_execute:
        errors.append("Missing [Execute] section — EF5 won't know which tasks to run")

    if errors:
        for e in errors:
            print(f"[ERROR] {e}", file=sys.stderr)
    for m in messages:
        print(m)

    return len(errors) == 0, errors + messages


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------
def resolve_shared_libs(binary_path):
    """Find directories that satisfy ef5's 'not found' shared libraries.

    The ef5 binary is linked against libtiff/libgeotiff/libproj that live in
    conda envs on this server, not on the default loader path — a fresh shell
    gets `error while loading shared libraries: libproj.so.25` (exit 127).
    We parse `ldd` for unresolved libs, then search a set of known conda-env
    lib dirs (and any dir already supplying a *resolved* ef5 dependency) for a
    file of that soname, and return the dirs to prepend to LD_LIBRARY_PATH.
    """
    try:
        ldd = subprocess.run(["ldd", binary_path], capture_output=True, text=True, timeout=30)
    except Exception:
        return []
    missing, known_dirs = [], set()
    for line in ldd.stdout.splitlines():
        line = line.strip()
        if "=> not found" in line:
            missing.append(line.split("=>")[0].strip())
        elif "=> /" in line:  # an already-resolved dep tells us a good lib dir
            known_dirs.add(os.path.dirname(line.split("=>")[1].strip().split(" (")[0]))
    if not missing:
        return []
    search = list(known_dirs) + [
        "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/PCR_GLOBWB_2/miniconda/envs/pcrglobwb_python3/lib",
    ]
    # Add all conda env lib dirs as a last resort
    import glob
    search += sorted(glob.glob("KISSPATH_HOME/miniconda3/envs/*/lib"))
    found = []
    for soname in missing:
        for d in search:
            if os.path.exists(os.path.join(d, soname)):
                if d not in found:
                    found.append(d)
                break
    return found


def run_ef5(binary_path, control_path, timeout=3600, cwd=None):
    """
    Run EF5 binary and capture output.

    Returns (returncode, stdout, stderr, elapsed_seconds)
    """
    if cwd is None:
        cwd = os.path.dirname(os.path.abspath(control_path))

    # absolute control path: the engine runs in cwd, so a relative path would be resolved twice
    cmd = [binary_path, os.path.abspath(control_path)]
    print(f"Running: {' '.join(cmd)}")
    print(f"Working directory: {cwd}")

    env = os.environ.copy()
    lib_dirs = resolve_shared_libs(binary_path)
    if lib_dirs:
        existing = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = ":".join(lib_dirs + ([existing] if existing else []))
        print(f"[run_ef5] LD_LIBRARY_PATH += {':'.join(lib_dirs)}")

    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env=env,
        )
        elapsed = time.time() - start
        return result.returncode, result.stdout, result.stderr, elapsed
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start
        return -1, "", f"Timeout after {timeout}s", elapsed
    except FileNotFoundError:
        return -2, "", f"Binary not found: {binary_path}", 0


# ---------------------------------------------------------------------------
# Post-run validation
# ---------------------------------------------------------------------------
def shared_output_conflicts(control_path, sections=None):
    """Fail-closed rule: two or more DIFFERENT executed tasks must not share an OUTPUT dir or a
    CO_FILE (and a CO_FILE must not sit inside another executed task's OUTPUT dir). With shared
    locations the wrapper cannot tell which task wrote what, so it refuses to run.
    Paths are resolved the way the engine sees them (relative to the control file's folder).
    Returns a list of messages; empty means no conflict."""
    if sections is None:
        sections = parse_control_file(control_path)
    tasks = {s.get("_name", "").strip().lower(): s for s in sections.values() if s.get("_type") == "task"}
    run = list(dict.fromkeys(n for n in executed_task_names(sections) if n in tasks))
    outs, cos = {}, {}
    for n in run:
        s = tasks[n]
        od = resolve_path(s.get("output", ""), control_path)
        if od:
            outs.setdefault(os.path.realpath(od), []).append(s.get("_name"))
        co = resolve_path(s.get("co_file", ""), control_path)
        if co:
            cos.setdefault(os.path.realpath(co), []).append(s.get("_name"))
    msgs = []
    for path, names in outs.items():
        if len(names) > 1:
            msgs.append(f"tasks {', '.join(names)} share OUTPUT {path}")
    for path, names in cos.items():
        if len(names) > 1:
            msgs.append(f"tasks {', '.join(names)} share CO_FILE {path}")
        for od, onames in outs.items():
            others = [o for o in onames if o not in names]
            if others and os.path.dirname(path) == od:
                msgs.append(f"CO_FILE {path} of task(s) {', '.join(names)} is inside the OUTPUT dir of "
                            f"task(s) {', '.join(others)}")
    return msgs


def snapshot_outputs(control_path):
    """(mtime_ns, size, inode) of every regular file in any task OUTPUT dir and of every task
    CO_FILE, taken BEFORE the run, so the post-run check can tell files this run wrote from files
    left by an earlier run (no time tolerance)."""
    snap = {}
    try:
        sections = parse_control_file(control_path)
    except OSError:
        return snap

    def _add(f):
        st = os.stat(f)
        snap[os.path.abspath(str(f))] = (st.st_mtime_ns, st.st_size, st.st_ino)

    for s in sections.values():
        if s.get("_type") != "task":
            continue
        od = resolve_path(s.get("output", ""), control_path)
        if od and os.path.isdir(od):
            for f in Path(od).iterdir():
                if f.is_file():
                    _add(f)
        co = resolve_path(s.get("co_file", ""), control_path)
        if co and os.path.isfile(co):
            _add(co)
    return snap


snapshot_gauge_csvs = snapshot_outputs   # older name


def _co_rows(text):
    """Parse rows EF5 appends to a CO_FILE: 'YYYY-MM-DD HH:UU,gauge,Q' (Simulator.cpp:136, 1081).
    Returns [(time12, gauge_lower, value)], time12 = first 12 digits (YYYYMMDDHHUU)."""
    rows = []
    for line in text.splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) < 3:
            continue
        try:
            val = float(parts[-1])
        except ValueError:
            continue
        digits = re.sub(r"\D", "", parts[0])[:12]
        rows.append((digits, parts[1].lower(), val))   # val may be nan/inf; callers check
    return rows


# --- Step evidence --------------------------------------------------------------------------
# EF5 logs "INFO:...: Executing task <name>" before each task (ExecutionController.cpp:70) and,
# at the start of every time step, the step time as "YYYY-MM-DD HH:UU" at the start of a line:
# SimulateDistributed Simulator.cpp:1341 (NORMAL_LOGF, format set at :136), SimulateLumped (HyMOD)
# Simulator.cpp:1730 (printf), BasinAvg Simulator.cpp:674. Distributed/lumped runs only produce
# output once warmEndTime <= currentTime (Simulator.cpp:1415, 1771); BasinAvg has no warm-up. Task names are lower-cased (Config.cpp:363-368).
# Calibration (SimulateForCali, Simulator.cpp:2050-) prints no per-step line, so for CALI_* the
# zero-step case is checked before the run from TIME_BEGIN/TIME_WARMEND/TIME_END and TIMESTEP.
STDOUT_STEPPING_STYLES = ("simu", "simu_rp", "basin_avg")
WINDOW_CHECKED_STYLES = ("cali_ars", "cali_dream")
_STEP_LINE = re.compile(r"(?m)^[ \t]*(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})")
_EXEC_LINE = re.compile(r"Executing task (\S+)")


def split_stdout_by_task(stdout):
    """[(task_name_lower, section_text)] in execution order, split at 'Executing task <name>'."""
    plain = re.sub(r"\x1b\[[0-9;]*m", "", stdout or "")
    marks = list(_EXEC_LINE.finditer(plain))
    out = []
    for i, mk in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(plain)
        out.append((mk.group(1).strip().lower(), plain[mk.end():end]))
    return out


def step_times(section_text):
    """'YYYYMMDDHHUU' of every per-step line in one task's stdout section."""
    return ["".join(m.groups()) for m in _STEP_LINE.finditer(section_text)]


class TimeParseError(ValueError):
    pass


def _sscanf_ints(text, widths):
    """C sscanf with '%0Nd' fields in a row: each field skips leading white space, takes an optional
    sign and up to N characters (sign counted), and needs >= 1 digit; scanning stops at the first
    field that does not match. Returns the parsed ints (possibly fewer than len(widths))."""
    vals, i, n = [], 0, len(text)
    for w in widths:
        while i < n and text[i] in " \t\r\n\v\f":
            i += 1
        j, sign = i, ""
        if j < n and text[j] in "+-" and w > 1:
            sign = text[j]; j += 1
        k = j
        while k < n and text[k].isdigit() and (k - i) < w:
            k += 1
        if k == j:
            break
        vals.append(int(sign + text[j:k]))
        i = k
    return vals


def _parse_ef5_time(v):
    """TIME_BEGIN / TIME_WARMEND / TIME_END exactly like TimeVar::LoadTime (TimeVar.cpp:18-59):
    sscanf("%04d%02d%02d%02d%02d%02d") with fall-through defaults (month Jan, day 1, 00:00:00),
    so '2020', '202001', '20200102' (= midnight) are valid; fields are then normalised by timegm
    (e.g. month 13 -> next January). Raises TimeParseError when not even the year parses."""
    import datetime as _dt
    vals = _sscanf_ints(v or "", (4, 2, 2, 2, 2, 2))
    if not vals:
        raise TimeParseError(f"unable to process time {v!r} (EF5 'Unable to process time')")
    year, month, day, hour, minute, second = (vals + [1, 1, 0, 0, 0][len(vals) - 1:])[:6] \
        if len(vals) < 6 else vals
    # timegm-style normalisation of possibly out-of-range fields
    months = (month - 1)
    y = year + months // 12
    mo = months % 12 + 1
    try:
        base = _dt.datetime(y, mo, 1)
    except ValueError as ex:
        raise TimeParseError(f"time {v!r} is out of range ({ex})")
    return base + _dt.timedelta(days=day - 1, hours=hour, minutes=minute, seconds=second)


def task_times(sec):
    """(begin, warmend, end) of a task as EF5 reads them. TIME_WARMEND defaults to TIME_BEGIN only
    when the key is ABSENT (TaskConfigSection.cpp:643-645); an explicit value that cannot be read
    raises TimeParseError, as does a missing TIME_BEGIN/TIME_END (both required,
    TaskConfigSection.cpp:572-577)."""
    def _get(key, required):
        if key not in sec:
            if required:
                raise TimeParseError(f"{key.upper()} is missing")
            return None
        return _parse_ef5_time(sec.get(key))
    b = _get("time_begin", True)
    e = _get("time_end", True)
    w = _get("time_warmend", False)
    return b, (w if w is not None else b), e


def time_errors(control_path, sections=None):
    """Pre-run: every executed task's TIME_* values must parse the way EF5 parses them."""
    if sections is None:
        sections = parse_control_file(control_path)
    tasks = {s.get("_name", "").strip().lower(): s for s in sections.values() if s.get("_type") == "task"}
    errs = []
    for n in dict.fromkeys(x for x in executed_task_names(sections) if x in tasks):
        s = tasks[n]
        if s.get("style", "").strip().lower() not in STDOUT_STEPPING_STYLES + WINDOW_CHECKED_STYLES:
            continue
        try:
            task_times(s)
        except TimeParseError as ex:
            errs.append(f"task {s.get('_name')}: {ex}")
    return errs


def _parse_step(step):
    """TIMESTEP -> (k, unit) with k > 0, or None (non-positive or unreadable steps are refused:
    EF5 would loop forever on a zero step)."""
    m = re.fullmatch(r"\s*(\d*)\s*([ymdhus])\s*", (step or "").lower())
    if not m:
        return None
    k = int(m.group(1) or 1)
    return (k, m.group(2)) if k > 0 else None


def _add_step(t0, step):
    """Add one EF5 TIMESTEP (e.g. 1h, 5u, 1d, 1m=month, 1y) the way TimeVar::Increment does:
    calendar fields normalised like timegm (TimeVar.cpp:224-252), not fixed seconds."""
    import datetime as _dt
    ps = _parse_step(step)
    if ps is None:
        return None
    k, u = ps
    if u in "ym":
        months = t0.month - 1 + (k * 12 if u == "y" else k)
        y, mo = t0.year + months // 12, months % 12 + 1
        # normalisation: Jan 31 + 1 month = "Feb 31" = Mar 2/3, not a clamp to Feb 28/29
        return t0.replace(year=y, month=mo, day=1) + _dt.timedelta(days=t0.day - 1)
    return t0 + _dt.timedelta(seconds={"d": 86400, "h": 3600, "u": 60, "s": 1}[u] * k)


def post_warmup_steps_by_window(sec):
    """1 if the loop t = begin + step; t <= end has some t >= warmend, 0 if none, None if the
    window or TIMESTEP cannot be read or the step is not positive."""
    import datetime as _dt
    try:
        b, w, e = task_times(sec)
    except TimeParseError:
        return None
    ps = _parse_step(sec.get("timestep"))
    if not ps:
        return None
    k, u = ps
    if u not in "ym":
        # fixed-length step: jump straight to the first step at or after warm-up end
        dt = {"d": 86400, "h": 3600, "u": 60, "s": 1}[u] * k
        need = max(1, -(-int((w - b).total_seconds()) // dt))
        t = b + _dt.timedelta(seconds=need * dt)
        return 1 if t <= e else 0
    t = _add_step(b, sec.get("timestep"))
    while t is not None and t <= e:          # month/year steps: few iterations
        if w <= t:
            return 1
        nt = _add_step(t, sec.get("timestep"))
        if nt is None or nt <= t:
            return None
        t = nt
    return 0


def first_post_warmup_step_index(sec):
    """1-based index k of the first step t_k = begin + k x TIMESTEP with t_k >= TIME_WARMEND
    (ignoring TIME_END), or None if TIMESTEP is not a positive step. Raises TimeParseError."""
    b, w, e = task_times(sec)
    ps = _parse_step(sec.get("timestep"))
    if not ps:
        raise TimeParseError(f"TIMESTEP {sec.get('timestep')!r} is not a positive step")
    k, u = ps
    if u not in "ym":
        dt = {"d": 86400, "h": 3600, "u": 60, "s": 1}[u] * k
        return max(1, -(-int((w - b).total_seconds()) // dt))
    t, i = b, 0
    while True:
        i += 1
        nt = _add_step(t, sec.get("timestep"))
        if nt is None or nt <= t:
            return None
        if nt >= w:
            return i
        if i > 100000:
            return None
        t = nt


UNSUPPORTED_STEP_KEYS = ("time_begin_lr", "timestep_lr")


def unsupported_step_key_errors(control_path, sections=None):
    """Fail closed on keys that change EF5's step sequence. TIME_BEGIN_LR + TIMESTEP_LR switch the
    loop to a second step size once currentTime >= TIME_BEGIN_LR (TaskConfigSection.cpp:109-123,
    417-440; Simulator.cpp:410-412, 1574-1576). The output check assumes one TIMESTEP, so any
    executed task that sets either key is refused. (Read all TaskConfigSection keys: no other key
    changes the step sequence or the warm-up output gate; PRELOAD_FILE, forecasts, DA_FILE, STATES
    and TIME_STATE change inputs or state saving, not step times.)"""
    if sections is None:
        sections = parse_control_file(control_path)
    tasks = {s.get("_name", "").strip().lower(): s for s in sections.values() if s.get("_type") == "task"}
    errs = []
    for n in dict.fromkeys(x for x in executed_task_names(sections) if x in tasks):
        s = tasks[n]
        keys = [k.upper() for k in UNSUPPORTED_STEP_KEYS if k in s]
        if keys:
            errs.append(f"task {s.get('_name')} sets {', '.join(keys)}: two-step-size runs (TIME_BEGIN_LR/"
                        f"TIMESTEP_LR) are not supported by this wrapper's output check; run without them "
                        f"or check the output by hand")
    # ENSEMBLETASK= in [Execute] (ExecuteConfigSection.cpp:22-) runs ensemble calibration tasks
    # that this check does not cover at all; refuse rather than report an unchecked success.
    for s in sections.values():
        if s.get("_type") == "execute" and "ensembletask" in s:
            errs.append(f"[Execute] lists ENSEMBLETASK={s.get('ensembletask')}: ensemble tasks are not covered "
                        f"by this wrapper's output check; run them without run_ef5.py or check by hand")
    return errs


def zero_step_window_errors(control_path, sections=None):
    """Pre-run check for task styles whose stdout shows no step lines (CALI_*)."""
    if sections is None:
        sections = parse_control_file(control_path)
    tasks = {s.get("_name", "").strip().lower(): s for s in sections.values() if s.get("_type") == "task"}
    errs = []
    for n in dict.fromkeys(x for x in executed_task_names(sections) if x in tasks):
        s = tasks[n]
        if s.get("style", "").strip().lower() not in WINDOW_CHECKED_STYLES:
            continue
        k = post_warmup_steps_by_window(s)
        if k is None:
            errs.append(f"task {s.get('_name')}: cannot read TIME_BEGIN/TIME_WARMEND/TIME_END, or TIMESTEP "
                        f"is not a positive step ({s.get('timestep')}), so a post-warm-up step cannot be proven")
        elif k == 0:
            errs.append(f"task {s.get('_name')}: no post-warm-up step fits the window "
                        f"(TIME_WARMEND={s.get('time_warmend')}, TIME_END={s.get('time_end')}, "
                        f"TIMESTEP={s.get('timestep')})")
    return errs


def validate_output(control_path, stdout, stderr, returncode, run_start=None, pre_state=None):
    """Validate EF5 output after run."""
    messages = []

    if returncode != 0:
        messages.append(f"[ERROR] EF5 exited with code {returncode}")
        if "Segmentation fault" in stderr or "SIGSEGV" in stderr:
            messages.append("[ERROR] Segmentation fault — check grid dimensions and memory")
        if "No execute section" in stderr or "No execute section" in stdout:
            messages.append("[ERROR] Missing [Execute] section in control file")

    # Check for output files — only for tasks [Execute] actually runs, with paths resolved
    # against the engine cwd. Housekeeping files (results.json, da_log.csv) and directories
    # do not count as model output.
    sections = parse_control_file(control_path)
    run_names = executed_task_names(sections)
    housekeeping = {"results.json", "da_log.csv"}
    tasks = {s.get("_name", "").strip().lower(): s for s in sections.values() if s.get("_type") == "task"}
    # executions in [Execute] order (repeats kept); with no TASK= list, every task in file order
    order = [n for n in run_names if n in tasks] if run_names else list(tasks)

    def _changed(m):
        """True if this run wrote m: new or changed mtime/size/inode vs the pre-run snapshot;
        without a snapshot, mtime at or after run start (no tolerance)."""
        m = os.path.abspath(str(m))
        if pre_state is not None:
            if m not in pre_state:
                return True
            st = os.stat(m)
            return (st.st_mtime_ns, st.st_size, st.st_ino) != pre_state[m]
        if run_start is not None:
            return os.stat(m).st_mtime >= run_start
        return True

    for c in unsupported_step_key_errors(control_path, sections):
        messages.append(f"[ERROR] {c}")

    # Shared OUTPUT / CO_FILE between executed tasks makes output unattributable: fail closed.
    for c in shared_output_conflicts(control_path, sections):
        messages.append(f"[ERROR] {c} — give each task its own OUTPUT and CO_FILE")

    basins = {s.get("_name", "").strip().lower(): s for s in sections.values() if s.get("_type") == "basin"}
    gauges = {s.get("_name", "").strip().lower(): s for s in sections.values() if s.get("_type") == "gauge"}

    def _task_csvs(s):
        """abs paths of the gauge CSVs this task writes (ts.<gauge>.<model>.csv for each basin gauge
        with OUTPUTTS not false/no, Simulator.cpp:369-388), or None if basin/gauges are unknown."""
        od = resolve_path(s.get("output", ""), control_path)
        model = s.get("model", "").strip().lower()
        b = basins.get(s.get("basin", "").strip().lower())
        if not od or not model or not b or not b.get("_gauges"):
            return None
        out = []
        for g in b["_gauges"]:
            g = g.strip().lower()
            # EF5 accepts FALSE/NO (case-insensitive) to switch gauge CSV output off (GaugeConfigSection.cpp)
            if gauges.get(g, {}).get("outputts", "true").strip().lower() in ("false", "no"):
                continue
            out.append(os.path.abspath(os.path.join(od, f"ts.{g}.{model}.csv")))
        return out

    def _n_rows(path):
        with open(path, errors="ignore") as fh:
            return sum(1 for _ in fh) - 1

    def _nonfinite_q_rows(path):
        """Rows whose Discharge (2nd column) is not a finite number. Note: when simulated Q is
        non-finite, EF5 writes the OBSERVED value into Discharge and 'nan' into Observed
        (Simulator.cpp:972-982, dag hazard ts_nan_column_shift); with real observations that row
        cannot be told apart from a finite simulation with a missing observation."""
        import math as _m
        n = 0
        with open(path, errors="ignore") as fh:
            next(fh, None)
            for line in fh:
                parts = line.split(",")
                if len(parts) < 2:
                    continue
                try:
                    if not _m.isfinite(float(parts[1])):
                        n += 1
                except ValueError:
                    n += 1
        return n

    for n in dict.fromkeys(order):
        sec = tasks[n]
        output_dir = resolve_path(sec.get("output", ""), control_path)
        co_file = resolve_path(sec.get("co_file", ""), control_path)
        co_ok = False
        if co_file:
            # combined output (CO_FILE) is written directly, independent of OUTPUT (Simulator.cpp:1070-1084)
            if os.path.isfile(co_file) and _changed(co_file):
                # EF5 opens CO_FILE in append mode: count only rows added by this run
                old = (pre_state or {}).get(os.path.abspath(co_file))
                with open(co_file, "rb") as fh:
                    if old and old[2] == os.stat(co_file).st_ino and os.path.getsize(co_file) >= old[1]:
                        fh.seek(old[1])
                    new_rows = _co_rows(fh.read().decode(errors="ignore"))
            else:
                new_rows = []
            # Requested CO gauges: this task's basin gauges with WANTCO true/yes (default false,
            # GaugeConfigSection.cpp:21, 94-102). EACH must have >= 1 new row of its own; EF5 drops an
            # out-of-domain gauge with only a warning (BasicGrids.cpp:664-671).
            b_ = basins.get(sec.get("basin", "").strip().lower())
            if b_ and b_.get("_gauges"):
                want = [g.strip().lower() for g in b_["_gauges"]
                        if gauges.get(g.strip().lower(), {}).get("wantco", "false").strip().lower()
                        in ("true", "yes")]
                wants_co = bool(want)
                import math as _m
                got = {r[1] for r in new_rows if _m.isfinite(r[2])}
                for g in dict.fromkeys(r[1] for r in new_rows if not _m.isfinite(r[2]) and r[1] in want):
                    messages.append(f"[ERROR] CO_FILE {co_file} of task {sec.get('_name')} has non-finite "
                                    f"discharge (nan/inf) for gauge {g}")
                missing = [g for g in dict.fromkeys(want) if g not in got]
                bad_nf = {r[1] for r in new_rows if not _m.isfinite(r[2])}
                co_nonfinite = bool(bad_nf & set(want))
                for g in missing:
                    if g in bad_nf:
                        continue
                    messages.append(f"[ERROR] CO_FILE {co_file} of task {sec.get('_name')} got no new row for "
                                    f"WANTCO gauge {g} (gauge outside the domain, or no post-warm-up step?)")
                co_ok = bool(want) and not missing and not co_nonfinite
            else:
                # basin/gauges cannot be resolved: rows cannot be checked per gauge -> fail closed
                wants_co = False
                co_ok = False
                messages.append(f"[ERROR] Task {sec.get('_name')}: BASIN {sec.get('basin')!r} or its GAUGE= list "
                                f"cannot be resolved, so its CO_FILE rows cannot be checked per gauge")
            if co_ok:
                messages.append(f"[OK] combined output file {co_file}")
            elif not (b_ and b_.get("_gauges")):
                pass                 # error already reported above
            elif not wants_co:
                messages.append(f"[WARNING] CO_FILE {co_file} of task {sec.get('_name')} is set but no gauge "
                                f"has WANTCO=yes")
        if not output_dir:
            if co_file and not co_ok:
                messages.append(f"[ERROR] Task {sec.get('_name')} has no OUTPUT dir and its CO_FILE got "
                                f"no new data rows")
            continue
        if not os.path.isdir(output_dir):
            if co_ok:
                continue
            messages.append(f"[ERROR] Output dir of task {sec.get('_name')} does not exist: {output_dir}")
            continue
        files = [f for f in Path(output_dir).iterdir()
                 if f.is_file() and f.name not in housekeeping and _changed(f)
                 and not (co_file and os.path.abspath(str(f)) == os.path.abspath(co_file))]
        # Only SIMU/SIMU_RP write gauge rows; BASIN_AVG leaves header-only CSVs, CLIP/calibration none.
        if sec.get("style", "").strip().lower() in ("simu", "simu_rp"):
            mine = _task_csvs(sec)
            if mine is not None:
                # every expected gauge CSV must be rewritten by this run and have data rows; EF5 drops
                # a gauge outside the domain with only a warning (BasicGrids.cpp:664-671)
                for m in mine:
                    if not os.path.isfile(m):
                        messages.append(f"[ERROR] Expected gauge time series {os.path.basename(m)} was not "
                                        f"written by task {sec.get('_name')} (gauge outside the domain?)")
                    elif not _changed(m):
                        messages.append(f"[ERROR] Gauge time series {os.path.basename(m)} is older than this "
                                        f"run (not rewritten by task {sec.get('_name')})")
                    elif _n_rows(m) < 1:
                        messages.append(f"[ERROR] Gauge time series {os.path.basename(m)} has a header but no "
                                        f"data rows (e.g. TIME_WARMEND after TIME_END, or no simulated steps)")
                    else:
                        nf = _nonfinite_q_rows(m)
                        if nf:
                            messages.append(f"[ERROR] Gauge time series {os.path.basename(m)} has {nf} row(s) with "
                                            f"non-finite Discharge (nan/inf)")
            else:
                # basin/gauges cannot be resolved: the expected gauge files are unknown -> fail closed
                messages.append(f"[ERROR] Task {sec.get('_name')}: BASIN {sec.get('basin')!r} or its GAUGE= list "
                                f"cannot be resolved, so its gauge time series cannot be checked")
        style = sec.get("style", "").strip().lower()
        if style in ("simu", "simu_rp") and sec.get("model", "").strip().lower() != "hymod":
            # requested per-step and max grids (OUTPUT_GRIDS, GriddedOutput.cpp) must be fresh here;
            # options that depend on other modules (return period, snow, inundation, thresholds,
            # accumulations) are not required
            req = {g.strip().lower() for g in sec.get("output_grids", "").split("|") if g.strip()}
            prefix = {"streamflow": "q.", "soilmoisture": "sm.", "precip": "precip.", "pet": "pet.",
                      "maxstreamflow": "maxq.", "maxsoilmoisture": "maxsm.",
                      "unitstreamflow": "unitq.", "maxunitstreamflow": "maxunitq."}
            for g in sorted(req & set(prefix)):
                if not any(f.name.startswith(prefix[g]) and f.suffix == ".tif" for f in files):
                    messages.append(f"[ERROR] Task {sec.get('_name')} requested OUTPUT_GRIDS {g.upper()} but no "
                                    f"fresh {prefix[g]}*.tif was written in {output_dir}")
        if style == "basin_avg" and not any(f.name.startswith("precip.") and f.name.endswith(".avg.tif")
                                            for f in files):
            messages.append(f"[ERROR] BASIN_AVG task {sec.get('_name')} wrote no fresh precip.*.avg.tif")
        if files:
            messages.append(f"[OK] {len(files)} output files in {output_dir}")
        elif co_ok:
            messages.append(f"[OK] no files in {output_dir}, but the combined output file has data")
        else:
            messages.append(f"[ERROR] No model output files in {output_dir} "
                            f"(only housekeeping files or nothing)")

    # ONE proof that a stepping task ran: its own stdout section shows >= 1 post-warm-up step line.
    sections_out = split_stdout_by_task(stdout)
    pos = 0
    for n in order:
        sec = tasks[n]
        style = sec.get("style", "").strip().lower()
        # match this execution to the next "Executing task <n>" section, in order
        idx = next((i for i in range(pos, len(sections_out)) if sections_out[i][0] == n), None)
        if idx is None:
            messages.append(f"[ERROR] EF5 stdout has no 'Executing task {sec.get('_name')}' line for this execution")
            continue
        pos = idx + 1
        if style not in STDOUT_STEPPING_STYLES:
            continue
        times = step_times(sections_out[idx][1])
        if style != "basin_avg" and times:
            # One step line is printed per executed step, in order (minute resolution only). Step k's
            # exact time is begin + k x TIMESTEP (TimeVar::Increment), so the run reached warm-up end iff
            # the number of printed lines >= k* = index of the first step at or after TIME_WARMEND.
            try:
                kstar = first_post_warmup_step_index(sec)
            except TimeParseError as ex:
                messages.append(f"[ERROR] Task {sec.get('_name')}: {ex}; cannot tell warm-up steps from "
                                f"post-warm-up steps")
                continue
            if kstar is None or len(times) < kstar:
                times = []
        if not times:
            messages.append(f"[ERROR] Task {sec.get('_name')} ran no time step"
                            f"{'' if style == 'basin_avg' else ' after warm-up'} (no step line in its "
                            f"stdout section); check TIME_BEGIN/TIME_WARMEND/TIME_END and TIMESTEP")

    # Check for gauge time series output
    for line in stdout.split("\n"):
        if "time series" in line.lower() or "output" in line.lower():
            messages.append(f"  EF5: {line.strip()}")

    # Missing forcing is a scientific failure, not a warning: EF5 logs it on stdout,
    # replaces the field with zeros and still exits 0 (Simulator.cpp LoadForcings).
    log = (stdout or "") + "\n" + (stderr or "")
    for pattern in ("Missing precip file", "Missing PET file", "Missing Temp file"):
        count = log.count(pattern)
        if count > 0:
            messages.append(f"[ERROR] '{pattern}' appeared {count} times — EF5 used zeros for "
                            f"those steps; the run is not valid (check NAME date tokens vs FREQ)")
    # EF5 logs set-up failures (e.g. forcing FREQ finer than TIMESTEP) as "ERROR:<file>(<line>):"
    # lines, skips the simulation and still exits 0 (Messages.h ERROR_LOG, ExecutionController.cpp).
    plain = re.sub(r"\x1b\[[0-9;]*m", "", log)
    ef5_errors = [l.strip() for l in plain.splitlines() if l.lstrip().startswith("ERROR:")]
    # Known source quirk: STYLE_BASIN_AVG has no `break` in ExecutionController.cpp, so after a
    # successful BASIN_AVG task EF5 also logs "Unimplemented simulation run style". Drop exactly one
    # such line per executed BASIN_AVG task; any other error line still fails the run.
    _styles = {s.get("_name", "").strip().lower(): s.get("style", "").strip().lower()
               for s in sections.values() if s.get("_type") == "task"}
    # count EXECUTIONS: [Execute] may list the same task twice and EF5 runs it twice
    n_basin_avg = sum(1 for n in run_names if _styles.get(n) == "basin_avg")
    kept = []
    for l in ef5_errors:
        if n_basin_avg and "Unimplemented simulation run style" in l:
            n_basin_avg -= 1
            continue
        kept.append(l)
    ef5_errors = kept
    if ef5_errors:
        messages.append(f"[ERROR] EF5 logged {len(ef5_errors)} error line(s), first: {ef5_errors[0][:200]}")
    for g in dict.fromkeys(re.findall(r"Gauge (\S+) is outside the basic grid domain", plain)):
        # BasicGrids.cpp:668-671: the gauge is dropped with only a warning; its outputs are missing
        messages.append(f"[ERROR] Gauge {g} is outside the basic grid domain and was dropped by EF5")
    n_open_fail = log.count("Failed to open gauge output file")
    if n_open_fail:
        messages.append(f"[ERROR] EF5 could not open {n_open_fail} gauge output file(s) — "
                        f"those time series were not written")
    if "Unsupported precip format" in log:
        messages.append("[ERROR] 'Unsupported precip format' — precip TYPE has no reader "
                        "(e.g. TRMMV7); EF5 used zero rain")

    # Check for common warnings in stdout
    warning_patterns = [
        ("Node Soil Moisture", "Initial soil moisture issues — check IWU parameter"),
        ("not found", "Missing file — check paths in control file"),
        ("Impervious Area", "IM parameter out of range"),
    ]
    for pattern, explanation in warning_patterns:
        count = stdout.count(pattern)
        if count > 0:
            messages.append(f"[WARNING] '{pattern}' appeared {count} times — {explanation}")

    return messages


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Run EF5 with preflight and post-run validation")
    parser.add_argument("--binary", required=True, help="Path to ef5 binary")
    parser.add_argument("--control", required=True, help="Path to control.txt")
    parser.add_argument("--timeout", type=int, default=3600, help="Timeout in seconds")
    parser.add_argument("--skip-preflight", action="store_true", help="Skip preflight checks")
    parser.add_argument("--log", help="Log file path for output")
    args = parser.parse_args()
    # The engine runs with cwd = the control file's folder; resolve the binary against the
    # caller's cwd first so a relative --binary still points at the same file.
    if os.sep in args.binary or os.path.exists(args.binary):
        args.binary = os.path.abspath(args.binary)

    # Pre-flight
    if not args.skip_preflight:
        print("=" * 60)
        print("PREFLIGHT CHECKS")
        print("=" * 60)
        ok, msgs = preflight_check(args.control, args.binary)
        if not ok:
            print("\n[ABORT] Preflight checks failed. Fix errors above before running.")
            sys.exit(1)
        print("\n[OK] All preflight checks passed\n")

    # Fail closed on shared output locations (checked even with --skip-preflight)
    conflicts = shared_output_conflicts(args.control) if os.path.isfile(args.control) else []
    conflicts += zero_step_window_errors(args.control) if os.path.isfile(args.control) else []
    conflicts += time_errors(args.control) if os.path.isfile(args.control) else []
    conflicts += unsupported_step_key_errors(args.control) if os.path.isfile(args.control) else []
    if conflicts:
        for c in conflicts:
            print(f"[ERROR] {c}", file=sys.stderr)
        print("\n[ABORT] The control file cannot be checked or cannot run a post-warm-up step "
              "(see errors above). Give each task its own OUTPUT and CO_FILE, and a time window "
              "with at least one step.", file=sys.stderr)
        sys.exit(1)

    # Execute
    print("=" * 60)
    print("EXECUTING EF5")
    print("=" * 60)
    pre_state = snapshot_outputs(args.control)
    run_start = time.time()
    returncode, stdout, stderr, elapsed = run_ef5(args.binary, args.control, args.timeout)

    print(f"\nEF5 completed in {elapsed:.1f}s with exit code {returncode}")
    if stdout:
        print("\n--- STDOUT ---")
        print(stdout[:5000])
    if stderr:
        print("\n--- STDERR ---")
        print(stderr[:2000])

    # Post-run validation
    print("\n" + "=" * 60)
    print("POST-RUN VALIDATION")
    print("=" * 60)
    msgs = validate_output(args.control, stdout, stderr, returncode, run_start=run_start,
                           pre_state=pre_state)
    for m in msgs:
        print(m)

    # Write log
    if args.log:
        log_data = {
            "binary": args.binary,
            "control": args.control,
            "returncode": returncode,
            "elapsed_s": elapsed,
            "stdout_head": stdout[:2000],
            "stderr_head": stderr[:1000],
        }
        with open(args.log, "w") as f:
            json.dump(log_data, f, indent=2)
        print(f"\n[OK] Log written to {args.log}")

    failed = returncode != 0 or any(m.startswith("[ERROR]") for m in msgs)
    if failed and returncode == 0:
        print("\n[FAIL] EF5 exited 0 but post-run validation found errors (see above)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
