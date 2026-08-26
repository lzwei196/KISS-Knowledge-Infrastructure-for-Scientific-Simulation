"""Apply a parameter VALUE back into a heterogeneous model input — the `address`
dispatcher. This is the crux codex flagged: without robust address semantics the
kit can't generalize across crop YAML, namelists, MODFLOW packages, SWMM .inp, etc.

Each address kind has a paired (write, read) so the contract can self-test via
verify_roundtrip — a write/read that disagrees would corrupt the search silently.

TAXONOMY (v2): GENERIC FORMATS live here — yaml_path / json_path / ini_key / text_token /
namelist / fixed_width / table_cell — one handler reused across many models. MODEL/MECHANISM-
specific kinds (modflow_pkg, swmm_inp, api) do NOT belong here (a central modflow handler would
reimplement flopy); they are injected via injection.mode=runner, using the model's native library
in tools/calib_run.py. write_param raises a clear runner-mode error for those.
"""
from __future__ import annotations
import json
import re
from pathlib import Path


def _resolve(addr, base):
    """Resolve an address file path UNAMBIGUOUSLY (codex applicator.py:18). Order:
    absolute `file` -> as-is; explicit `addr['root']` (absolute) -> root/file;
    else `base`/file (the caller's workdir). An explicit root lets a contract point
    at ki_path-relative inputs without the wrong tree being edited silently."""
    p = Path(addr["file"])
    if p.is_absolute():
        return p
    root = addr.get("root")
    if root:
        return Path(root) / p
    return Path(base) / p


# ---- yaml_path -------------------------------------------------------------
def _yaml_rw(addr, base, value=None):
    import yaml
    f = _resolve(addr, base)
    doc = yaml.safe_load(f.read_text())
    keys = re.split(r"\.|\[|\]", addr["path"])
    keys = [k for k in keys if k != ""]
    node = doc
    for k in keys[:-1]:
        k = int(k) if k.isdigit() else k
        node = node[k]
    last = keys[-1]; last = int(last) if last.isdigit() else last
    if value is None:
        return node[last]
    node[last] = value
    f.write_text(yaml.safe_dump(doc, sort_keys=False))
    return value


# ---- json_path -------------------------------------------------------------
def _json_rw(addr, base, value=None):
    f = _resolve(addr, base)
    doc = json.loads(f.read_text())
    keys = [k for k in re.split(r"\.|\[|\]", addr["path"]) if k != ""]
    node = doc
    for k in keys[:-1]:
        node = node[int(k) if k.isdigit() else k]
    last = keys[-1]; last = int(last) if last.isdigit() else last
    if value is None:
        return node[last]
    node[last] = value
    f.write_text(json.dumps(doc, indent=2))
    return value


# ---- ini_key (configparser) ------------------------------------------------
def _ini_rw(addr, base, value=None):
    import configparser
    f = _resolve(addr, base)
    cp = configparser.ConfigParser()
    cp.read(f)
    if value is None:
        return cp[addr["section"]][addr["key"]]
    cp[addr["section"]][addr["key"]] = str(value)
    with open(f, "w") as fh:
        cp.write(fh)
    return value


# ---- text_token (regex, one capture group) ---------------------------------
def _text_rw(addr, base, value=None):
    f = _resolve(addr, base)
    txt = f.read_text()
    m = re.search(addr["pattern"], txt)
    if not m:
        raise KeyError(f"text_token pattern not found in {f}: {addr['pattern']}")
    if value is None:
        return m.group(1)
    s, e = m.span(1)
    f.write_text(txt[:s] + str(value) + txt[e:])
    return value


# ---- namelist (Fortran &group key=value /) ---------------------------------
def _namelist_rw(addr, base, value=None):
    """Fortran namelist via f90nml (REQUIRED). We do NOT regex-edit namelists: a regex would silently
    corrupt arrays (`k=1,2,3`), `k(2)=` element syntax, quoted strings with commas, and inline `!` comments —
    and C7 can't catch it because it re-reads with the same lossy parser. address: {file, group, key, [index]}."""
    try:
        import f90nml
    except ImportError as e:
        raise RuntimeError("namelist address kind requires f90nml (pip install f90nml) — refusing to "
                           "regex-edit a namelist (silent-corruption risk)") from e
    f = _resolve(addr, base)
    group, key, idx = addr["group"], addr["key"], addr.get("index")
    nml = f90nml.read(str(f))
    cur = nml[group][key]
    if value is None:
        return cur[idx] if (idx is not None and isinstance(cur, list)) else cur
    if idx is not None and isinstance(cur, list):
        cur[idx] = value; nml[group][key] = cur
    else:
        nml[group][key] = value
    nml.write(str(f), force=True)
    return value


# ---- fixed_width (character columns on a line) -----------------------------
def _fixed_width_rw(addr, base, value=None):
    """Fixed-width field. address: {file, line, col_start, col_end} — 1-indexed line,
    1-indexed INCLUSIVE character columns. Right-justified into the field (Fortran-style)."""
    f = _resolve(addr, base)
    lines = f.read_text().split("\n")
    ln = addr["line"] - 1
    c0, c1 = addr["col_start"] - 1, addr["col_end"]
    line = lines[ln]
    if value is None:
        return line[c0:c1].strip()
    width = c1 - c0
    s = str(value)
    if len(s) > width:      # NEVER silently truncate — a clipped value is a wrong value
        raise ValueError(f"fixed_width value {s!r} ({len(s)} chars) exceeds field width {width} at "
                         f"{f} line {addr['line']} cols {addr['col_start']}-{addr['col_end']}")
    lines[ln] = line[:c0] + s.rjust(width) + line[c1:]
    f.write_text("\n".join(lines))
    return value


# ---- table_cell (delimited or whitespace table) ----------------------------
def _table_cell_rw(addr, base, value=None):
    """A cell in a table. address: {file, row, col, [delimiter]} — 0-indexed row/col;
    delimiter omitted = whitespace-split (rejoined single-space — pass a delimiter to
    preserve exact layout)."""
    f = _resolve(addr, base)
    delim = addr.get("delimiter")
    lines = f.read_text().split("\n")
    r, col = addr["row"], addr["col"]
    cells = lines[r].split(delim) if delim else lines[r].split()
    if value is None:
        return cells[col].strip()
    if not delim:           # whitespace rejoin destroys column alignment a fixed-position reader depends on
        raise ValueError("table_cell WRITE requires an explicit `delimiter` (read is fine without one) — "
                         "rejoining whitespace would collapse column alignment")
    cells[col] = str(value)
    lines[r] = delim.join(cells)
    f.write_text("\n".join(lines))
    return value


_RW = {
    "yaml_path": _yaml_rw, "json_path": _json_rw, "ini_key": _ini_rw, "text_token": _text_rw,
    "namelist": _namelist_rw, "fixed_width": _fixed_width_rw, "table_cell": _table_cell_rw,
}
# model/mechanism-specific — NOT central applicator kinds. Inject via injection.mode=runner
# (tools/calib_run.py using the model's native library: flopy for MODFLOW, pyswmm for SWMM, an API client).
_RUNNER_ONLY = {"modflow_pkg", "swmm_inp", "api"}


def write_param(address: dict, value, base: str):
    kind = address["kind"]
    if kind in _RUNNER_ONLY:
        raise ValueError(
            f"address kind {kind!r} is model/mechanism-specific — set injection.mode=runner and inject via "
            f"tools/calib_run.py using the model's native library (flopy/pyswmm/API); the central applicator "
            f"does not reimplement it")
    fn = _RW.get(kind)
    if fn is None:
        raise NotImplementedError(f"unknown address kind {kind!r}")
    return fn(address, base, value)


def read_param(address: dict, base: str):
    kind = address["kind"]
    if kind in _RUNNER_ONLY:
        raise ValueError(f"address kind {kind!r} is runner-mode only (see write_param)")
    fn = _RW.get(kind)
    if fn is None:
        raise NotImplementedError(f"unknown address kind {kind!r}")
    return fn(address, base, None)


def verify_roundtrip(address: dict, value, base: str, rtol: float = 1e-6) -> bool:
    """C7: write value, read it back, confirm agreement (else the search is corrupt). Fail-closed:
    non-finite → False; isclose with a tiny abs_tol so a near-zero value can't be clamped to 0 silently."""
    import math
    write_param(address, value, base)
    got = read_param(address, base)
    try:
        fg, fv = float(got), float(value)
        return math.isfinite(fg) and math.isfinite(fv) and math.isclose(fg, fv, rel_tol=rtol, abs_tol=1e-12)
    except (TypeError, ValueError):
        return str(got) == str(value)
