#!/usr/bin/env python3
"""
edit_geometry.py -- Modify a HEC-RAS geometry (.gNN) text file in place,
following the copy-first rule (read template line, replace specific values,
write back -- never regenerate from a Python dict).

Capabilities:
  * scale or set Manning's roughness n   (--mann-scale / --mann-set)
  * set expansion / contraction coefficients (--exp / --contr)

The .gNN geometry is keyword/comma delimited (NOT Fortran fixed-width), e.g.

    #Mann= 3 ,0,0
           0               0       0    .015       0      20               0
    Exp/Cntr=0.3,0.1

The Manning data line carries (station, n, ...) triplets; here we rewrite the
n value(s) while preserving every other token and column.

NOTE: after editing the .gNN text you must regenerate the geometry HDF
(preprocess_geometry.py) OR rely on the existing .gNN.hdf if only flow/boundary
values changed. Manning edits that must reach the solver require the run file to
be re-derived; for parametric n studies on an existing run file, edit the run
file's roughness block instead (see SKILL.md "roughness sensitivity").

Usage:
  python3 edit_geometry.py --geom in.g01 --out out.g01 --mann-scale 1.2
  python3 edit_geometry.py --geom in.g01 --out out.g01 --mann-set 0.035
  python3 edit_geometry.py --geom in.g01 --out out.g01 --exp 0.3 --contr 0.1
"""
import argparse
import re
import shutil
import sys


def _edit_mann_block(lines, i, scale=None, setval=None):
    """The line after a '#Mann= k,...' header holds k*(station,n,code) triplets
    as fixed-ish whitespace fields. We find float tokens that look like n
    (0 < n < 1, typical 0.01..0.2) and scale/replace them, preserving width."""
    header = lines[i]
    m = re.match(r"#Mann=\s*(\d+)", header)
    if not m:
        return
    data = lines[i + 1]
    # split into (text, value) chunks by matching numeric tokens with their span
    out = data
    # tokens of the data line
    for tok in re.finditer(r"[-+]?\d*\.\d+|\d+", data):
        s = tok.group()
        if "." not in s:
            continue
        try:
            v = float(s)
        except ValueError:
            continue
        if 0.0 < v < 1.0:  # plausible Manning n
            nv = setval if setval is not None else v * scale
            ns = ("%g" % nv)
            # preserve field width by right-padding/truncating within the token span
            start, end = tok.span()
            width = end - start
            ns = ns.rjust(width) if len(ns) <= width else ns
            out = out[:start] + ns + out[end:]
            # recompute remaining spans is unsafe if width changed; redo conservatively
            if len(ns) != width:
                return _redo_full(lines, i, scale, setval)
    lines[i + 1] = out


def _redo_full(lines, i, scale, setval):
    """Fallback: token-rebuild the Mann data line keeping same separators."""
    data = lines[i + 1].rstrip("\n")
    parts = re.split(r"(\s+)", data)  # keep whitespace separators
    for j, p in enumerate(parts):
        if re.fullmatch(r"[-+]?\d*\.\d+", p or ""):
            v = float(p)
            if 0.0 < v < 1.0:
                nv = setval if setval is not None else v * scale
                parts[j] = ("%g" % nv)
    lines[i + 1] = "".join(parts) + "\n"


def edit_geometry(in_path, out_path, mann_scale=None, mann_set=None,
                  exp=None, contr=None):
    if out_path != in_path:
        shutil.copy2(in_path, out_path)
    with open(out_path) as fh:
        lines = fh.readlines()

    n_mann = 0
    for i, line in enumerate(lines):
        if line.startswith("#Mann=") and (mann_scale is not None or mann_set is not None):
            _edit_mann_block(lines, i, scale=mann_scale, setval=mann_set)
            n_mann += 1

    n_ec = 0
    if exp is not None or contr is not None:
        for i, line in enumerate(lines):
            if line.startswith("Exp/Cntr="):
                cur = line.split("=", 1)[1].strip().split(",")
                e = exp if exp is not None else cur[0]
                c = contr if contr is not None else (cur[1] if len(cur) > 1 else "0.1")
                lines[i] = f"Exp/Cntr={e},{c}\n"
                n_ec += 1

    with open(out_path, "w") as fh:
        fh.writelines(lines)
    return {"mann_blocks_edited": n_mann, "exp_contr_lines_edited": n_ec,
            "out": out_path}


def validate_outputs(result, out_path):
    """Sanity: file still parses and Manning n stayed physical (0.005..0.5)."""
    import re as _re
    with open(out_path) as fh:
        txt = fh.read()
    bad = []
    for i, line in enumerate(txt.splitlines()):
        if line.startswith("#Mann="):
            nxt = txt.splitlines()[i + 1]
            for tok in _re.findall(r"[-+]?\d*\.\d+", nxt):
                v = float(tok)
                if 0.0 < v < 1.0 and not (0.005 <= v <= 0.5):
                    bad.append(v)
    if bad:
        return False, f"Manning n out of physical range: {bad}"
    return True, "geometry edits within physical ranges"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--geom", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mann-scale", type=float, default=None)
    ap.add_argument("--mann-set", type=float, default=None)
    ap.add_argument("--exp", type=float, default=None)
    ap.add_argument("--contr", type=float, default=None)
    a = ap.parse_args()
    res = edit_geometry(a.geom, a.out, mann_scale=a.mann_scale, mann_set=a.mann_set,
                        exp=a.exp, contr=a.contr)
    ok, msg = validate_outputs(res, a.out)
    res["validation"] = {"ok": ok, "detail": msg}
    import json
    print(json.dumps(res, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
