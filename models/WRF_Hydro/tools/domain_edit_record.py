"""
domain_edit_record.py -- shared by the WRF-Hydro KI domain tools (2026-10-05).

Owner rule: a domain tool must never silently replace, fill or clip input data.
Every such stand-in edit is

  * OFF by default: the tool computes everything, then stops BEFORE writing its
    output, listing per variable the rule, the cell count and the first cells;
  * ON only with an explicit --fix-domain-gaps (floors need explicit values:
    --smois-floor, --tslb-floor; there are no default numbers);
  * RECORDED cell by cell (index, j/i, lat/lon, old value range, new value) in a
    JSON record in the same format as the runners' domain_edits.json
    (wrfhydro_domain_edits.py at the model root), written next to the output as
    domain_edits.<tool>.json, so runners can merge it and apply the 1 % rule to
    tool-made fills with real cell lists.

Kinds:
  fill_missing_data        a value that is missing in the source is replaced
  model_stability_guard    a floor that keeps Noah-MP stable (no data meaning)
  start_value_adjustment   an initial-state floor (SMOIS, TSLB)
  value_clip               a source value outside an accepted range is changed
  water_cell_placeholder   a value on a water cell (LU_INDEX water) that the land
                           model does not use as land; recorded, not gated

Soil fills on land carry tag "soil_fill_on_land". (The 1 % limit on soil fills
was removed by owner decision 2026-10-05.)

Soil gaps are filled from NEIGHBOURS, never with a fixed class
(neighbour_class_fill): for each gap cell, look at the valid land cells in the
8-neighbour ring (Chebyshev distance 1); if there is none, widen ring by ring
(distance 2, 3, ...). Among the valid cells of the first ring that has any, take
the most common class; a tie is broken by the closest (Euclidean, in cells)
cell of each tied class, then by the lowest class id. Only originally valid
cells are used as sources (a filled cell never feeds another fill). Every filled
cell is recorded with its source cells and the class taken.
"""
import datetime as _dt
import json
import os
import sys
from pathlib import Path

import numpy as np

SCHEMA = "wrfhydro_domain_edits/v1"
SOIL_FILL_MAX_SHARE = None        # 1 % limit removed (owner decision 2026-10-05)
SOIL_FILL_TAG = "soil_fill_on_land"
NOT_GATED = ("water_cell_placeholder",)
FIRST_N = 10


def add_cli(parser, floors=False):
    parser.add_argument("--fix-domain-gaps", action="store_true",
                        help="allow the recorded stand-in edits (default off: the tool stops "
                             "and lists the cells that would need one)")
    parser.add_argument("--edits_record", default=None,
                        help="where to write the edit record (default: "
                             "<output dir>/domain_edits.<tool>.json)")
    if floors:
        parser.add_argument("--smois-floor", type=float, default=None,
                            help="REQUIRED with --fix-domain-gaps: SMOIS = max(SMOIS, value)")
        parser.add_argument("--tslb-floor", type=float, default=None,
                            help="optional with --fix-domain-gaps: TSLB = max(TSLB, value)")
    return parser


def default_record_path(output_path, tool):
    return Path(output_path).resolve().parent / f"domain_edits.{tool}.json"


class ToolEdits:
    def __init__(self, tool, fix, record_path, latlon=None, settings_extra=None):
        self.tool = tool
        self.fix = bool(fix)
        self.record_path = Path(record_path)
        self.latlon = latlon            # (lat2d, lon2d) or None
        self.settings_extra = settings_extra or {}
        self.edits = []
        self.pending = []               # edits needed while not allowed

    def settings(self):
        s = {"fix_domain_gaps": self.fix, "tool": self.tool,
             "soil_fill_rule": "neighbour_class_fill (8-neighbours, widening rings; majority, "
                               "tie: closest then lowest class id)"}
        s.update(self.settings_extra)
        return s

    def _cells(self, mask):
        out = []
        for row in np.argwhere(mask):
            j, i = int(row[-2]), int(row[-1])
            c = {"index": [int(x) for x in row], "j": j, "i": i}
            if self.latlon is not None:
                la, lo = self.latlon
                c["lat"] = round(float(la[j, i]), 5)
                c["lon"] = round(float(lo[j, i]), 5)
            out.append(c)
        return out

    def allow(self, file, variable, rule, kind, mask, old, new_value, tag=None, cell_info=None):
        """Record a needed edit. Returns True if the caller may apply it."""
        mask = np.asarray(mask, dtype=bool)
        n = int(mask.sum())
        if n == 0:
            return False
        o = np.asarray(old, dtype="f8")[mask] if old is not None else np.array([])
        fin = o[np.isfinite(o)] if o.size else o
        rec = {"file": file, "variable": variable, "rule": rule, "kind": kind,
               "count": n,
               "old_min": (float(fin.min()) if fin.size else None),
               "old_max": (float(fin.max()) if fin.size else None),
               "old_nonfinite": (int(o.size - fin.size) if o.size else None),
               "new_value": (float(new_value) if isinstance(new_value, (int, float, np.floating))
                             else str(new_value)),
               "made_by": self.tool, "cells": self._cells(mask)}
        if cell_info:
            # per-cell detail (e.g. neighbour sources and the class taken)
            for c in rec["cells"]:
                extra = cell_info.get((c["j"], c["i"]))
                if extra:
                    c.update(extra)
        if tag:
            rec["tag"] = tag
        self.edits.append(rec)
        if kind in NOT_GATED:
            return True
        if not self.fix:
            self.pending.append(rec)
            return False
        return True

    def stop(self, msg):
        print(f"\n  ERROR [{self.tool}]: {msg}", flush=True)
        sys.exit(3)

    def finish(self, n_land=None):
        """Call before writing the output. Stops if edits were needed but not
        allowed, or if soil fills on land exceed 1 %. Writes the record."""
        if self.pending:
            lines = []
            for r in self.pending:
                first = ", ".join(f"[{','.join(map(str, c['index']))}]"
                                  + (f"@{c['lat']},{c['lon']}" if "lat" in c else "")
                                  for c in r["cells"][:FIRST_N])
                lines.append(f"    {r['variable']} ({r['rule']}; {r['kind']}): {r['count']} cells, first {first}")
            self.stop("the source data needs stand-in edits but --fix-domain-gaps is off; "
                      "no output was written.\n" + "\n".join(lines))
        # (n_land kept for callers; the 1 % soil-fill limit was removed 2026-10-05)
        return self.write()

    def record(self):
        by = {}
        for e in self.edits:
            by.setdefault(e["kind"], []).append(
                {k: e[k] for k in ("file", "variable", "rule", "count", "old_min",
                                   "old_max", "old_nonfinite", "new_value")})
        return {"schema": SCHEMA,
                "written_at": _dt.datetime.now().isoformat(timespec="seconds"),
                "settings": self.settings(), "files_checked": [self.tool],
                "n_edited_cells_total": int(sum(e["count"] for e in self.edits)),
                "summary_by_kind": by, "edits": self.edits}

    def write(self):
        rec = self.record()
        self.record_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.record_path.with_name(self.record_path.name + ".tmp")
        tmp.write_text(json.dumps(rec, indent=1))
        os.replace(tmp, self.record_path)
        n = rec["n_edited_cells_total"]
        print(f"  [{self.tool}] edit record: {self.record_path} ({n} edited cells)")
        return rec


def merge_records(paths, out_path):
    """Merge several tool records into one domain_edits.json (same schema)."""
    edits, checked, settings = [], [], {}
    for p in paths:
        r = json.loads(Path(p).read_text())
        edits.extend(r.get("edits", []))
        checked.extend(r.get("files_checked", []))
        settings[r.get("settings", {}).get("tool", str(p))] = r.get("settings")
    by = {}
    for e in edits:
        by.setdefault(e["kind"], []).append(
            {k: e[k] for k in ("file", "variable", "rule", "count", "old_min",
                               "old_max", "old_nonfinite", "new_value")})
    rec = {"schema": SCHEMA, "written_at": _dt.datetime.now().isoformat(timespec="seconds"),
           "settings": settings, "files_checked": checked,
           "n_edited_cells_total": int(sum(e["count"] for e in edits)),
           "summary_by_kind": by, "edits": edits}
    Path(out_path).write_text(json.dumps(rec, indent=1))
    return rec


def neighbour_class_fill(cls, gap, valid, latlon=None, max_ring=None):
    """Fill gap cells of a 2-D class grid from their neighbours (rule in the
    module docstring). Returns (filled_classes_2d, info) where info maps
    (j, i) -> {"class_taken": c, "ring": r, "sources": [{"j","i","class"[,"lat","lon"]}]}.
    Raises ValueError if some gap cell has no valid land cell anywhere."""
    cls = np.asarray(cls)
    gap = np.asarray(gap, dtype=bool)
    valid = np.asarray(valid, dtype=bool) & ~gap
    ny, nx = cls.shape
    out = cls.copy()
    info = {}
    if not gap.any():
        return out, info
    if not valid.any():
        raise ValueError("no valid land cell with soil data to fill from")
    max_ring = max_ring or max(ny, nx)
    for j, i in np.argwhere(gap):
        j, i = int(j), int(i)
        for r in range(1, max_ring + 1):
            j0, j1 = max(0, j - r), min(ny, j + r + 1)
            i0, i1 = max(0, i - r), min(nx, i + r + 1)
            sub = valid[j0:j1, i0:i1]
            if not sub.any():
                continue
            src = []
            for dj, di in np.argwhere(sub):
                jj, ii = j0 + int(dj), i0 + int(di)
                if max(abs(jj - j), abs(ii - i)) == r:      # this ring only
                    src.append((jj, ii))
            if not src:
                continue
            counts = {}
            for jj, ii in src:
                c = int(cls[jj, ii])
                d = ((jj - j) ** 2 + (ii - i) ** 2) ** 0.5
                n, dmin = counts.get(c, (0, 1e9))
                counts[c] = (n + 1, min(dmin, d))
            best = sorted(counts.items(), key=lambda kv: (-kv[1][0], kv[1][1], kv[0]))[0][0]
            out[j, i] = best
            srcs = []
            for jj, ii in src:
                e = {"j": jj, "i": ii, "class": int(cls[jj, ii])}
                if latlon is not None:
                    e["lat"] = round(float(latlon[0][jj, ii]), 5)
                    e["lon"] = round(float(latlon[1][jj, ii]), 5)
                srcs.append(e)
            info[(j, i)] = {"class_taken": int(best), "ring": r, "sources": srcs}
            break
        else:
            raise ValueError(f"gap cell j={j}, i={i}: no valid land cell within {max_ring} rings")
    return out, info
