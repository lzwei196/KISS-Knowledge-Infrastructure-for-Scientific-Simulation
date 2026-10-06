#!/usr/bin/env python3
"""edit_kineros2_par.py -- inspect, validate and edit a KINEROS2 parameter file (copy-first).

The parameter file is tagged ("KS = 10", or a column header line "KS G DIST POR ROCK" with one
value row per soil layer).  This tool reads it with the SAME lookup rules as the engine's
reader.for (prefix match on the first token, list values end at the line end, column values
counted by line and position) and changes values by replacing single tokens in place, so the
rest of the file -- comments, layout, CRLF line endings -- stays byte-identical.  It never
regenerates a parameter file from scratch.

Sub-commands
  list      FILE                          elements, topology, key tags as the ENGINE reads them
  validate  FILE [--rain PRE]             static checks (exit 2 on errors)
  set       FILE --out NEW  --set SPEC ... SPEC = <ID|TYPE|*>:<TAG>[:<index>]=<value>
            e.g. --set 10:KSAT=0.4  --set PLANE:SAT=0.25  --set 2:KS:2=30  --set 27:PRINT=2
            A tag missing from a block is ADDED as a new 'TAG = value' line before END
            (only for index 1; a missing column/second-layer value is an error).
  get       FILE --tag TAG [--index N]     the value every element would receive

Exit codes: 0 ok | 2 validation errors / bad spec | 1 unexpected failure
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _k2lib as k2  # noqa: E402

KEY_TAGS = ("LEN", "WID", "SL", "MAN", "KS", "G", "DI", "POR", "ROC", "SA", "CV", "INT", "CAN", "THI", "PRI")


def _targets(tf, sel) -> list:
    """Indices into tf.blocks.  Indices stay valid after line insertions (block count is unchanged)."""
    idx = [i for i, b in enumerate(tf.blocks) if b.name != "GLOBAL"]
    if sel == "*":
        return idx
    if sel.upper() == "GLOBAL":
        return [i for i, b in enumerate(tf.blocks) if b.name == "GLOBAL"]
    if sel.upper() in k2.ELEMENT_TYPES:
        return [i for i in idx if tf.blocks[i].name == sel.upper()]
    try:
        eid = int(sel)
    except ValueError:
        raise ValueError(f"selector {sel!r} is not an element ID, element type, GLOBAL or *")
    hit = [i for i in idx if tf.blocks[i].element_id == eid]
    if not hit:
        raise ValueError(f"no element with ID {eid}")
    return hit


def set_value(tf, bi: int, tag: str, idx: int, val: str) -> dict:
    """Set tag[idx] of block number bi; add 'TAG = val' before END when absent (idx 1 only)."""
    b = tf.blocks[bi]
    if "+" in val or "," in val or " " in val.strip():
        raise ValueError(f"value {val!r}: no '+', commas or spaces (the reader splits on them); "
                         f"write plain decimals, e.g. 1600000 not 1.6e+06")
    old, tok = b.lookup(tag, idx)
    if tok is not None:
        k2.set_token(tf, tok, val)
        return {"block": b.name, "id": b.element_id, "tag": tag, "index": idx, "old": old, "new": val}
    if idx != 1:
        raise ValueError(f"{b.name} {b.element_id}: {tag}[{idx}] not present; add the second-layer value by "
                         f"hand following the manual's two-layer layout")
    k2.insert_line_before_end(tf, b, f"  {tag} = {val}")
    if tf.blocks[bi].lookup(tag, 1)[0] is None:
        raise ValueError(f"inserted {tag} into {b.name} {b.element_id} but the engine lookup cannot see it "
                         f"(another tag starting with {tag!r} comes first?)")
    return {"block": b.name, "id": b.element_id, "tag": tag, "index": 1, "old": None, "new": val, "added": True}


def set_list(tf, bi: int, tag: str, values: list) -> dict:
    """Set a whole list tag (e.g. FRACT = a, b, c): replace in place if the count matches, else add."""
    b = tf.blocks[bi]
    have = b.get_list(tag, 10)
    if have and len(have) != len(values):
        raise ValueError(f"{b.name} {b.element_id}: {tag} has {len(have)} values, new list has {len(values)}; "
                         f"edit that line by hand")
    if have:
        for i, v in enumerate(values, start=1):
            set_value(tf, bi, tag, i, v)
    else:
        k2.insert_line_before_end(tf, b, f"  {tag} = {', '.join(values)}")
        if tf.blocks[bi].get_list(tag, 10) != [v.upper() for v in values]:
            raise ValueError(f"{b.name} {b.element_id}: inserted {tag} list not read back by the engine lookup")
    return {"block": b.name, "id": b.element_id, "tag": tag, "old": have or None, "new": values}


def apply_sets(tf, specs) -> list:
    """Apply SPEC strings (<ID|TYPE|GLOBAL|*>:<TAG>[:<index>]=<value>) to a parsed TaggedFile."""
    log = []
    for spec in specs:
        lhs, eq, val = spec.partition("=")
        parts = lhs.split(":")
        if not eq or len(parts) not in (2, 3):
            raise ValueError(f"bad --set {spec!r}; expected <ID|TYPE|*>:<TAG>[:<index>]=<value>")
        sel, tag = parts[0], parts[1].upper()
        idx = int(parts[2]) if len(parts) == 3 else 1
        for bi in _targets(tf, sel):
            log.append(set_value(tf, bi, tag, idx, val.strip()))
    return log


def cmd_list(tf):
    print(f"units={k2.par_units(tf)}  CLEN={k2.global_block(tf).get_float('C')}")
    print(f"{'type':9s} {'id':>6s}  {'upstream':14s} {'lateral':10s} " + " ".join(f"{t:>8s}" for t in KEY_TAGS))
    for b in tf.blocks[1:]:
        vals = [b.lookup(t)[0] or "-" for t in KEY_TAGS]
        print(f"{b.name:9s} {str(b.element_id):>6s}  {','.join(b.get_list('UP', 10)) or '-':14s} "
              f"{','.join(b.get_list('LA', 3)) or '-':10s} " + " ".join(f"{v:>8s}" for v in vals))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list"); p.add_argument("file")
    p = sub.add_parser("validate"); p.add_argument("file"); p.add_argument("--rain"); p.add_argument("--json")
    p = sub.add_parser("set"); p.add_argument("file"); p.add_argument("--out", required=True)
    p.add_argument("--set", action="append", required=True); p.add_argument("--rain")
    p = sub.add_parser("get"); p.add_argument("file"); p.add_argument("--tag", required=True)
    p.add_argument("--index", type=int, default=1)
    a = ap.parse_args(argv)
    try:
        tf = k2.read_tagged(a.file)
        if a.cmd == "list":
            cmd_list(tf)
            return 0
        if a.cmd == "get":
            for b in tf.blocks:
                print(f"{b.name:9s} {str(b.element_id):>6s}  {a.tag.upper()}[{a.index}] = {b.lookup(a.tag, a.index)[0]}")
            return 0
        if a.cmd == "validate":
            rain = k2.read_tagged(a.rain) if a.rain else None
            v = k2.validate_parfile(tf, rain)
            if rain is not None:
                v["warnings"] += k2.rain_units_check(rain, k2.par_units(tf))
            for e in v["errors"]:
                print(f"ERROR: {e}")
            for w in v["warnings"]:
                print(f"warning: {w}")
            print(f"{len(v['elements'])} elements, outlet {v['outlet']}, {len(v['errors'])} error(s)")
            if a.json:
                Path(a.json).write_text(json.dumps(v, indent=2))
            return 2 if v["errors"] else 0
        if a.cmd == "set":
            out = Path(a.out)
            if out.resolve() == Path(a.file).resolve():
                raise ValueError("--out must differ from the input (copy-first; keep the original)")
            log = apply_sets(tf, a.set)
            tf.write(out)
            check = k2.read_tagged(out)
            v = k2.validate_parfile(check, k2.read_tagged(a.rain) if a.rain else None)
            for c in log:
                print(f"  {c['block']:8s} {str(c['id']):>6s} {c['tag']}[{c['index']}]: {c['old']} -> {c['new']}"
                      + ("  (added)" if c.get("added") else ""))
            for e in v["errors"]:
                print(f"ERROR after edit: {e}")
            print(f"wrote {out} ({len(log)} change(s))")
            return 2 if v["errors"] else 0
    except (ValueError, k2.EngineError, FileNotFoundError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
