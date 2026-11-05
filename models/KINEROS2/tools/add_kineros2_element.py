#!/usr/bin/env python3
"""add_kineros2_element.py -- insert a detention POND or a flow INJECT element into a KINEROS2
parameter file (copy-first) and re-wire the downstream element.

POND  (pond.for; manual Input.pdf 2.c): routes inflow through a storage-discharge rating table.
  --type pond --id 900 --receives 23 --feeds 26 --rating rating.csv [--storage 0] [--seepage-ks 0]
  rating.csv columns volume,discharge,surface  (cu m, cu m/s, sq m for METRIC; cu ft, cu ft/s, sq ft
  for ENGLISH).  Engine rules checked here: <= 49 rows; volume starts at 0 and increases; the first
  discharge is 0 (pond.for reads q(j-1) for the first positive discharge); surface > 0.
  The pond block goes right after the element it receives, and in the --feeds element's UPSTREAM
  list the received id is replaced by the pond id.

INJECT (inject.for; Input.pdf 2.d): time-varying inflow from outside the model (measured flow,
  another model's output).
  --type inject --id 901 --feeds 2 --hydrograph inflow.csv [--offset-min 0]
  inflow.csv columns time_min,discharge[,c1..cN] (m3/s or ft3/s; optional sediment concentrations,
  one per particle class).  Time must start at 0.  The data file is written NEXT TO --out with an
  UPPER-CASE name, because the engine upper-cases FILE= values before opening them; pass it to
  run_kineros2_engine.py with --extra-file.  The new id is appended to the --feeds element's
  UPSTREAM list (a channel takes at most 10 upstream elements).

Exit codes: 0 written and re-validated | 2 bad input
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _k2lib as k2  # noqa: E402


def _rows(path, cols):
    with open(path) as fh:
        rd = csv.DictReader(fh)
        missing = [c for c in cols if c not in (rd.fieldnames or [])]
        if missing:
            raise ValueError(f"{path}: missing column(s) {missing}; have {rd.fieldnames}")
        return [{k: float(v) for k, v in r.items() if v not in (None, "")} for r in rd], rd.fieldnames


def _block_index(tf, eid):
    for i, b in enumerate(tf.blocks):
        if b.name != "GLOBAL" and b.element_id == eid:
            return i
    raise ValueError(f"no element with ID {eid}")


def _insert_block(tf, after_line: int, lines: list):
    eol = "\r\n" if tf.lines and tf.lines[0].endswith("\r\n") else "\n"
    new = [eol] + [ln + eol for ln in lines]
    tf.lines[after_line + 1:after_line + 1] = new
    tf.blocks = k2.read_tagged_from_lines(tf.path, tf.lines).blocks


def add_pond(tf, a):
    rows, _ = _rows(a.rating, ["volume", "discharge", "surface"])
    if not 2 <= len(rows) <= 49:
        raise ValueError(f"rating table has {len(rows)} rows; the engine accepts 2-49")
    v = [r["volume"] for r in rows]; q = [r["discharge"] for r in rows]; s = [r["surface"] for r in rows]
    if v[0] != 0 or any(b <= a_ for a_, b in zip(v, v[1:])):
        raise ValueError("rating volumes must start at 0 and strictly increase")
    if q[0] != 0 or any(b < a_ for a_, b in zip(q, q[1:])):
        raise ValueError("rating discharge must start at 0 and never decrease")
    if any(x <= 0 for x in s):
        raise ValueError("surface areas must be > 0")
    ri = _block_index(tf, a.receives)
    fi = _block_index(tf, a.feeds)
    if fi <= ri:
        raise ValueError(f"--feeds {a.feeds} is processed before --receives {a.receives}")
    ups = tf.blocks[fi].get_list("UP", 10)
    if str(a.receives) not in [str(int(float(u))) for u in ups]:
        raise ValueError(f"element {a.receives} is not in the UPSTREAM list of {a.feeds} ({ups}); "
                         f"a pond can only be spliced into an upstream link")
    lines = [f"BEGIN POND ! inserted by add_kineros2_element.py: receives {a.receives}, feeds {a.feeds}",
             f"  ID = {a.id}, UP = {a.receives}" + (f", PRINT = {a.print}" if a.print else ""),
             f"  STORAGE = {k2.fmt_num(a.storage)}"]
    if a.seepage_ks:
        lines.append(f"  K = {k2.fmt_num(a.seepage_ks)}")
    lines += [f"  N = {len(rows)}", "  VOLUME        DISCHARGE        SURFACE"]
    lines += [f"  {k2.fmt_num(r['volume']):<13s} {k2.fmt_num(r['discharge']):<16s} {k2.fmt_num(r['surface'])}"
              for r in rows]
    lines.append("END")
    _insert_block(tf, tf.blocks[ri].end_line, lines)
    fi = _block_index(tf, a.feeds)
    for i in range(1, 11):
        val, tok = tf.blocks[fi].lookup("UP", i)
        if val is not None and int(float(val)) == a.receives:
            k2.set_token(tf, tok, str(a.id))
            break
    return f"POND {a.id} between {a.receives} and {a.feeds}"


def add_inject(tf, a, out: Path):
    rows, fields = _rows(a.hydrograph, ["time_min", "discharge"])
    if not rows or rows[0]["time_min"] != 0:
        raise ValueError("injection hydrograph must start at time_min = 0")
    if any(r2["time_min"] <= r1["time_min"] for r1, r2 in zip(rows, rows[1:])):
        raise ValueError("injection times must increase")
    if a.offset_min and rows[0]["discharge"] != 0:
        raise ValueError("engine: 'cannot offset nonzero initial discharge'")
    conc = [c for c in fields if c not in ("time_min", "discharge")]
    fname = (a.inject_file or f"INJ{a.id}.DAT").upper()
    with open(out.parent / fname, "w") as fh:
        for r in rows:
            fh.write(" ".join(k2.fmt_num(r[c], 8) for c in ["time_min", "discharge"] + conc) + "\n")
    fi = _block_index(tf, a.feeds)
    lines = [f"BEGIN INJECT ! inserted by add_kineros2_element.py: feeds {a.feeds}",
             f"  ID = {a.id}, FILE = {fname}" + (f", OFFSET = {a.offset_min:g}" if a.offset_min else "")
             + (f", PRINT = {a.print}" if a.print else ""),
             "END"]
    prev_end = tf.blocks[fi - 1].end_line
    _insert_block(tf, prev_end, lines)
    fi = _block_index(tf, a.feeds)
    ups = tf.blocks[fi].get_list("UP", 10)
    if len(ups) >= 10:
        raise ValueError(f"element {a.feeds} already has 10 upstream elements")
    if ups:
        _, tok = tf.blocks[fi].lookup("UP", len(ups))
        k2.set_token(tf, tok, f"{tok.text}, {a.id}")
        tf.blocks = k2.read_tagged_from_lines(tf.path, tf.lines).blocks
    else:
        k2.insert_line_before_end(tf, tf.blocks[fi], f"  UPSTREAM = {a.id}")
    return f"INJECT {a.id} ({fname}, {len(rows)} rows{', +' + str(len(conc)) + ' conc cols' if conc else ''}) into {a.feeds}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--par", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--type", choices=["pond", "inject"], required=True)
    ap.add_argument("--id", type=int, required=True)
    ap.add_argument("--feeds", type=int, required=True, help="downstream element that receives the new one")
    ap.add_argument("--receives", type=int, help="pond: element whose outflow enters the pond")
    ap.add_argument("--rating", help="pond: CSV volume,discharge,surface")
    ap.add_argument("--storage", type=float, default=0.0, help="pond: initial storage volume")
    ap.add_argument("--seepage-ks", type=float, help="pond: constant seepage rate (mm/hr or in/hr)")
    ap.add_argument("--hydrograph", help="inject: CSV time_min,discharge[,conc...]")
    ap.add_argument("--offset-min", type=float, default=0.0)
    ap.add_argument("--inject-file", help="inject: data file name (written upper-case)")
    ap.add_argument("--print", type=int, choices=[0, 1, 2], default=0)
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        if out.resolve() == Path(a.par).resolve():
            raise ValueError("--out must differ from --par (copy-first)")
        tf = k2.read_tagged(a.par)
        if any(b.element_id == a.id for b in tf.blocks if b.name != "GLOBAL"):
            raise ValueError(f"ID {a.id} already used")
        if a.type == "pond":
            if a.receives is None or not a.rating:
                raise ValueError("pond needs --receives and --rating")
            msg = add_pond(tf, a)
        else:
            if not a.hydrograph:
                raise ValueError("inject needs --hydrograph")
            msg = add_inject(tf, a, out)
        tf.write(out)
        v = k2.validate_parfile(k2.read_tagged(out))
        for e in v["errors"]:
            print(f"ERROR after insert: {e}")
        for w in v["warnings"]:
            print(f"warning: {w}")
        print(f"wrote {out}: {msg}; {len(v['elements'])} elements, outlet {v['outlet']}")
        return 2 if v["errors"] else 0
    except (ValueError, k2.EngineError, FileNotFoundError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
