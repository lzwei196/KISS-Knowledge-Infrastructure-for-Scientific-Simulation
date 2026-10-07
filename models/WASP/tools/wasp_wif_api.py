#!/usr/bin/env python3
"""
wasp_wif_api.py -- read and edit a WASP 8.5 input file (.wif) through EPA's OWN data API.

A .wif is a binary file (boost-serialised C++ objects). It cannot be edited as text. The WASP 8.5
install ships `wasptool.exe COMMANDFILE`, which calls the same data functions the WASP GUI and the
engine use (waspcore.dll ShellInterface). Each command line is  G<KEYWORD> args  (get) or
P<KEYWORD> args  (put); PLOADWIF / PSAVEWIF load and save a .wif. This tool is the KI's only way to
change a .wif, so every edit starts from a working file (copy-first) and goes through EPA code.

Keywords verified on WASP 8.5.0 (see docs/s2_parameter_setup.md for the full table):
  PLOADWIF f | PSAVEWIF f | GNUMSEG | GNUMSYS | GSYSNAME i | GSEEDDATE / PSEEDDATE m d y |
  PENDJULIAN days | PMAXDT d | PIQOPT n | PFLOWTYPE seg n | PVOLUME seg v | PDMULT seg d |
  PINITIALDEPTH seg d | PCONSTVALUEBYISC isc inst v | PCONSTPARAM seg isc inst v |
  PINITC sys seg v | PNBRKTF isc 1 n + PBRKTF isc 1 k day v | PNBRKQ fld fn n + PNOQFUNC fld fn k day v |
  PNBFP sys bc n + PBOUNDFUNC sys bc k day v | PPRINTFUNC k day v
Times in time functions, flows, boundaries and print intervals are DAYS RELATIVE TO THE SEED DATE
(stored as absolute dates): set PSEEDDATE before writing any time series.

Failure is never silent. WifApiError (CLI exit 1) is raised when: the API rejects a command
("ERROR while ..."); WINE crashes; the echoed commands differ from the ones sent; any command's
echo has no "Result:" line or no field at all; a command lacks a field this tool or its callers
read (REQUIRED_FIELDS, e.g. GNUMSEG -> numseg, PLOADWIF/PSAVEWIF -> error); or a PUT echoes fewer
numbers than it was given, or a different number (every numeric argument is compared, in order).

Engine discovery: --wineprefix -> $WASP_WINEPREFIX -> $WASP_ENGINE_ROOT/wineprefix ->
KISSPATH_HOME/engine_builds_20261006/wasp/wineprefix; wine: --wine -> $WASP_WINE -> PATH.

Usage
  python wasp_wif_api.py --wif model.wif --get GNUMSEG "GSYSNAME 1"          # JSON to stdout
  python wasp_wif_api.py --wif model.wif --commands edits.txt --out new.wif   # apply P/G lines, save
Exit codes: 0 ok; 1 API/engine error; 2 bad command line; 3 WINE/wasptool missing.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_ENGINE_ROOT = "KISSPATH_HOME/engine_builds_20261006/wasp"
TOOL_WIN = r"C:\WASP8\wasp\bin\wasptool.exe"
TOOL_REL = Path("drive_c/WASP8/wasp/bin/wasptool.exe")
_FIELD = re.compile(r"^  (\S.*?): (.*?) \((INTEGER|REAL|STRING)\)\s*$")
_CMD = re.compile(r"^[PG][A-Z0-9]+( |$)")
_FATAL = ("ERROR while", "ERROR command failed", "WASP COMMAND FAILED", "Unhandled page fault",
          "Unhandled exception", "ERROR: unexpected error", "Malformed command", "Unrecognized command")


# Fields a command's Result block MUST carry (read by this tool or by build_wasp_lake_case.py).
REQUIRED_FIELDS = {
    "PWASPINIT": ("argc",), "PLOADWIF": ("error",), "PSAVEWIF": ("error",),
    "GNUMSEG": ("numseg",), "GNUMSYS": ("numsysinstances",), "GNFIELD": ("nfield",),
    "GNPRINT": ("nprint",), "GMODELTYPE": ("model_type",), "GSYSNAME": ("sys_key",),
    "GNOBC": ("nobc",), "GNOWK": ("nowk",), "GNINQ": ("ninq",),
    "GSEEDDATE": ("month", "day", "year"), "GENDJULIAN": ("days",), "GIQOPT": ("iqopt",),
    "GDMULT": ("dmult",), "GNBRKTF": ("nbrktf",), "GCONSTVALUEBYISC": ("value",),
}


class WifApiError(RuntimeError):
    pass


def default_wineprefix():
    """$WASP_WINEPREFIX -> $WASP_ENGINE_ROOT/wineprefix -> server default (absolute path)."""
    p = os.environ.get("WASP_WINEPREFIX") or str(
        Path(os.environ.get("WASP_ENGINE_ROOT") or DEFAULT_ENGINE_ROOT).expanduser() / "wineprefix")
    return Path(p).expanduser().absolute()


def resolve(wineprefix=None, wine=None):
    """Return (wine, prefix). Raises FileNotFoundError when WINE or wasptool.exe is missing."""
    prefix = Path(wineprefix).expanduser().absolute() if wineprefix else default_wineprefix()
    if not (prefix / TOOL_REL).is_file():
        raise FileNotFoundError(f"wasptool.exe not found under WINE prefix {prefix}")
    w = wine or os.environ.get("WASP_WINE") or shutil.which("wine")
    if not w or not os.access(w, os.X_OK):
        raise FileNotFoundError("wine executable not found (set --wine or $WASP_WINE)")
    return str(Path(w).expanduser().absolute()), prefix


def parse_output(stdout):
    """Split wasptool stdout into [(command, has_result_line, {field: value})]."""
    out, cur = [], None
    for raw in stdout.splitlines():
        ln = raw.rstrip("\r\n")
        if _CMD.match(ln):
            cur = [ln.strip(), False, {}]
            out.append(cur)
        elif cur is not None and ln.strip() == "Result:":
            if cur[1]:
                raise WifApiError(f"two 'Result:' lines for {cur[0]!r}")
            cur[1] = True
        else:
            m = _FIELD.match(ln)
            if m and cur is not None:
                if not cur[1]:
                    raise WifApiError(f"field line before 'Result:' for {cur[0]!r}: {ln.strip()!r}")
                k, v, t = m.groups()
                cur[2][k] = int(v) if t == "INTEGER" else float(v) if t == "REAL" else v
    return [tuple(x) for x in out]


def run_commands(cmds, cwd, wineprefix=None, wine=None, timeout=900):
    """Run wasptool on a list of command lines inside `cwd`; return [(cmd, {field: value})].

    Every command must produce one result block; anything the API rejects raises WifApiError."""
    w, prefix = resolve(wineprefix, wine)
    for c in cmds:
        if not _CMD.match(c) or "\n" in c:
            raise WifApiError(f"not a wasptool command: {c!r}")
    cf = Path(cwd) / "_wasptool_commands.txt"
    cf.write_text("\n".join(cmds) + "\n")
    env = dict(os.environ, WINEPREFIX=str(prefix), WINEDEBUG="-all")
    env.pop("DISPLAY", None)
    try:
        r = subprocess.run([w, TOOL_WIN, cf.name], cwd=cwd, env=env, capture_output=True,
                           text=True, errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        raise WifApiError(f"wasptool timed out after {timeout}s")
    text = r.stdout + "\n" + r.stderr
    bad = [ln for ln in text.splitlines() if ln.startswith(_FATAL)]
    if bad:
        raise WifApiError("wasptool rejected a command: " + " | ".join(bad[:3]))
    blocks = parse_output(r.stdout)
    if [c for c, _, _ in blocks] != [c.strip() for c in cmds]:
        raise WifApiError(f"wasptool returned {len(blocks)} result blocks for {len(cmds)} commands "
                          f"(rc={r.returncode}); last ok: {blocks[-1][0] if blocks else None}")
    out = []
    for c, has_result, res in blocks:
        if not has_result:
            raise WifApiError(f"{c!r}: no 'Result:' block in the wasptool output (rc={r.returncode})")
        if not res:
            raise WifApiError(f"{c!r}: empty Result block (no fields) (rc={r.returncode})")
        missing = [k for k in REQUIRED_FIELDS.get(c.split()[0], ()) if k not in res]
        if missing:
            raise WifApiError(f"{c!r}: Result block lacks required field(s) {missing}; got {sorted(res)}")
        if c.startswith(("PLOADWIF", "PSAVEWIF")) and res["error"] != 0:
            raise WifApiError(f"{c} returned error={res['error']}")
        out.append((c, res))
    return out


def _check_put(cmd, res):
    """A PUT echoes the values the API stored, in argument order; every numeric argument must be
    echoed (no fewer numbers than were sent) and equal the number we asked for."""
    want = []
    for tok in cmd.split()[1:]:
        try:
            want.append(float(tok))
        except ValueError:
            continue
    vals = [v for v in res.values() if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if len(vals) < len(want):
        raise WifApiError(f"{cmd}: API echoed {len(vals)} numeric field(s) for {len(want)} numeric "
                          f"argument(s): {res}")
    for x, got in zip(want, vals):
        if abs(x - got) > 1e-4 * max(1.0, abs(x)):
            raise WifApiError(f"{cmd}: API stored {got}, asked {x}")


def edit_wif(src, dst, cmds, wineprefix=None, wine=None, timeout=900):
    """Copy `src` into a scratch dir, apply `cmds` (P/G lines), save to `dst`, reload `dst`.

    Returns the parsed results of `cmds`. PUT echoes are checked against the requested values."""
    src, dst = Path(src).expanduser().absolute(), Path(dst).expanduser().absolute()
    with tempfile.TemporaryDirectory(prefix="wasp_wif_") as td:
        shutil.copy2(src, Path(td) / "in.wif")
        res = run_commands(["PWASPINIT", "PLOADWIF in.wif"] + list(cmds) + ["PSAVEWIF out.wif"],
                           td, wineprefix, wine, timeout)
        body = res[2:-1]
        for c, r in body:
            if c.startswith("P"):
                _check_put(c, r)
        if not (Path(td) / "out.wif").is_file() or (Path(td) / "out.wif").stat().st_size == 0:
            raise WifApiError("PSAVEWIF wrote no file")
        run_commands(["PWASPINIT", "PLOADWIF out.wif", "GNUMSEG"], td, wineprefix, wine, 300)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(td) / "out.wif", dst)
    return body


def query(wif, cmds, wineprefix=None, wine=None, timeout=900):
    """Run GET commands on a copy of `wif`; return [(cmd, {field: value})]."""
    with tempfile.TemporaryDirectory(prefix="wasp_wif_") as td:
        shutil.copy2(wif, Path(td) / "in.wif")
        return run_commands(["PWASPINIT", "PLOADWIF in.wif"] + list(cmds), td,
                            wineprefix, wine, timeout)[2:]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--wif", required=True, help="input .wif (never modified)")
    ap.add_argument("--get", nargs="*", default=[], help="G<KEYWORD> commands to print as JSON")
    ap.add_argument("--commands", help="text file, one P/G command per line (# = comment)")
    ap.add_argument("--out", help="save the edited .wif here (required with --commands)")
    ap.add_argument("--wineprefix", help="WINE prefix holding C:\\WASP8 (else $WASP_WINEPREFIX, else "
                                         "$WASP_ENGINE_ROOT/wineprefix, else "
                                         f"{DEFAULT_ENGINE_ROOT}/wineprefix)")
    ap.add_argument("--wine", help="wine executable (else $WASP_WINE, else wine on PATH)")
    a = ap.parse_args()
    if not Path(a.wif).is_file():
        print(f"ERROR: no such .wif: {a.wif}", file=sys.stderr)
        return 2
    if bool(a.commands) != bool(a.out) or not (a.get or a.commands):
        print("ERROR: give --get, or --commands together with --out", file=sys.stderr)
        return 2
    try:
        if a.commands:
            cmds = [ln.strip() for ln in Path(a.commands).read_text().splitlines()
                    if ln.strip() and not ln.lstrip().startswith("#")]
            res = edit_wif(a.wif, a.out, cmds, a.wineprefix, a.wine)
            print(f"saved {a.out} ({len(cmds)} commands applied and echo-checked)")
        else:
            res = query(a.wif, [g if g.startswith("G") else "G" + g for g in a.get],
                        a.wineprefix, a.wine)
            print(json.dumps([{"cmd": c, "result": r} for c, r in res], indent=1))
    except FileNotFoundError as e:
        print(f"MISSING DEPENDENCY: {e}", file=sys.stderr)
        return 3
    except WifApiError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
