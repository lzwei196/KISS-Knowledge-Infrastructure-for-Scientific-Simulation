"""
wrfhydro_domain_edits.py -- opt-in, fully recorded stand-in edits of a WRF-Hydro
DOMAIN (geo_em.d01.nc, wrfinput_d01.nc, soil_properties.nc). Added 2026-10-05,
revised the same day by owner decision.

* Default OFF. Without --fix-domain-gaps, any cell that would need an edit stops
  the runner before the model runs, with a per-variable count and the first cells.
* With --fix-domain-gaps the edits are applied and EVERY edited cell is recorded
  (variable, rule, kind, old value range, new value, count, cell indices, lat/lon,
  and for soil fills the neighbour source cells and the class taken) in
  domain_edits.json, and summarised for result.json.
* Soil gaps (water soil 14 on land, smc* <= 0) are filled from NEIGHBOURS, never
  with a fixed loam: the most common class of the nearest valid land cells
  (8-neighbours first, then wider rings; tie -> closest, then lowest class id),
  top and bottom layer separately; soil water values then come from that class's
  own SOILPARM.TBL row (same rule as the KI tools: domain_edit_record.py).
  There is no 1 % limit any more (owner decision).
* SMOIS / TSLB floors only with explicit --smois-floor / --tslb-floor (rule
  X = max(X, floor)); without a floor, non-finite or <= 0 values stop.
* GREENFRAC / SHDMAX / SHDMIN floors (dt_v005) stay as opt-in stability guards.

Kinds of edit:
  fill_missing_data       soil gaps (neighbour class), smc* <= 0 (class row)
  model_stability_guard   GREENFRAC, SHDMAX, SHDMIN floors
  start_value_adjustment  SMOIS, TSLB floors (initial state only)

Ships inside the KI (knowledge_infrastructure/tools/); WRF_Hydro/wrfhydro_domain_edits.py
at the model root is only a loader for this file. WRF_Hydro_NWM keeps its own copy.
"""
import datetime as _dt
import json
import os
from pathlib import Path

import numpy as np
import sys as _sys

# The KI's own record module (same neighbour-fill rule as the KI tools); it sits
# next to this file in knowledge_infrastructure/tools/.
_sys.path.insert(0, str(Path(__file__).resolve().parent))
import domain_edit_record as _der  # noqa: E402

RECORD = "domain_edits.json"
# KI tool edit records merged into RECORD (pipeline_step3b = SMOIS/TSLB step of
# run_wrfhydro_full_pipeline.py, same record format)
TOOL_RECORDS = ("build_geo_em", "build_wrfinput", "build_fulldom_hires",
                "build_soil_properties", "build_groundwater", "pipeline_step3b")
WATER_SOIL = 14          # STATSGO water category
LOAM = 6                 # STATSGO loam category (SOILCTOP index 5)
WATER_SOIL_MAX_SHARE = None   # 1 % limit removed (owner decision 2026-10-05)
FIRST_N = 10             # cells listed in a stop message


class DomainEditError(RuntimeError):
    """Edits are needed but not allowed, or exceed the allowed share."""


def add_cli(parser):
    parser.add_argument("--fix-domain-gaps", action="store_true",
                        help="apply the recorded stand-in domain edits (default: off; "
                             "without it any needed edit stops the run)")
    parser.add_argument("--smois-floor", type=float, default=None,
                        help="REQUIRED with --fix-domain-gaps: SMOIS = max(SMOIS, value), m3/m3")
    parser.add_argument("--tslb-floor", type=float, default=None,
                        help="optional with --fix-domain-gaps: TSLB = max(TSLB, value), K")
    parser.add_argument("--accept-unknown-domain-history", action="store_true",
                        help="reuse a complete DOMAIN that has no edit records (built by older "
                             "tools); its record then says 'history unknown', never 'no edits'. "
                             "Default: stop and ask for a DOMAIN rebuild")
    return parser


def soilparm_rows(soilparm_tbl):
    """{class: {"smcmax","smcref","smcwlt"}} from the STAS section of SOILPARM.TBL."""
    lines = Path(soilparm_tbl).read_text().splitlines()
    try:
        k = next(n for n, ln in enumerate(lines) if ln.strip() == "STAS")
    except StopIteration:
        raise DomainEditError(f"no STAS section in {soilparm_tbl}")
    rows = {}
    for ln in lines[k + 2:]:
        parts = [p.strip() for p in ln.split(",")]
        if not parts or not parts[0].isdigit():
            break
        rows[int(parts[0])] = {"smcmax": float(parts[4]), "smcref": float(parts[5]),
                               "smcwlt": float(parts[9])}
    return rows


class DomainEdits:
    def __init__(self, fix=False, smois_floor=None, tslb_floor=None,
                 soilparm_tbl=None, log=print, accept_unknown_history=False):
        self.fix = bool(fix)
        self.accept_unknown_history = bool(accept_unknown_history)
        self.history = "complete"      # "unknown: ..." when an unrecorded DOMAIN is reused
        self.smois_floor = smois_floor
        self.tslb_floor = tslb_floor
        self.soilparm_tbl = str(soilparm_tbl) if soilparm_tbl else None
        self.log = log
        self.edits = []          # full records
        self.checked = []        # files checked
        self.latlon = None
        self.tool_soil_cells = set()  # (j, i) of soil fills recorded by the KI tools
        # SMOIS floor: no default number. With --fix-domain-gaps but no
        # --smois-floor, no SMOIS floor is applied; SMOIS values that are
        # non-finite or <= 0 then stop the run (they need an explicit floor).
        self.geo_path = None

    def settings(self):
        return {"fix_domain_gaps": self.fix, "smois_floor": self.smois_floor,
                "tslb_floor": self.tslb_floor, "soilparm_tbl": self.soilparm_tbl,
                "soil_fill_rule": "neighbour_class_fill (8-neighbours, widening rings; majority, "
                                  "tie: closest then lowest class id)"}

    # ------------------------------------------------------------- helpers
    def _coords(self, ds):
        for la, lo in (("XLAT_M", "XLONG_M"), ("XLAT", "XLONG")):
            if la in ds.variables and lo in ds.variables:
                return (np.squeeze(np.asarray(ds[la][:], dtype="f8")),
                        np.squeeze(np.asarray(ds[lo][:], dtype="f8")))
        return None

    def _cells(self, mask):
        idx = np.argwhere(mask)
        out = []
        for row in idx:
            j, i = int(row[-2]), int(row[-1])
            c = {"index": [int(x) for x in row], "j": j, "i": i}
            if self.latlon is not None:
                la, lo = self.latlon
                c["lat"] = round(float(la[j, i]), 5)
                c["lon"] = round(float(lo[j, i]), 5)
            out.append(c)
        return out

    def _need(self, needed):
        """needed: list of (var, rule, kind, mask, data). Stop if not allowed."""
        needed = [n for n in needed if n[3].any()]
        if needed and not self.fix:
            parts = []
            for var, rule, kind, mask, data in needed:
                cells = self._cells(mask)[:FIRST_N]
                parts.append(f"{var} ({rule}; {kind}): {int(mask.sum())} cells, first "
                             + ", ".join(f"[{','.join(map(str, c['index']))}]"
                                         + (f"@{c['lat']},{c['lon']}" if 'lat' in c else "")
                                         for c in cells))
            raise DomainEditError("domain needs stand-in edits but --fix-domain-gaps is off; "
                                  "nothing was changed. " + " | ".join(parts))
        return needed

    def _apply(self, ds, path, var, rule, kind, mask, new_value):
        a = ds[var][:]
        data = np.ma.getdata(a).astype("f8")
        old = data[mask]
        fin = old[np.isfinite(old)]
        rec = {"file": Path(path).name, "variable": var, "rule": rule, "kind": kind,
               "count": int(mask.sum()),
               "old_min": (float(fin.min()) if fin.size else None),
               "old_max": (float(fin.max()) if fin.size else None),
               "old_nonfinite": int(old.size - fin.size),
               "new_value": (new_value if np.isscalar(new_value) else "per-cell"),
               "cells": self._cells(mask)}
        a2 = np.ma.array(np.ma.getdata(a).copy(), mask=np.ma.getmaskarray(a).copy())
        a2[mask] = new_value
        ds[var][:] = a2
        self.edits.append(rec)
        self.log(f"  domain edit {Path(path).name}:{var} {rule} -> {rec['count']} cells ({kind})")

    def tool_flags(self):
        """Flags passed on to the KI domain tools (same opt-in)."""
        return ["--fix-domain-gaps"] if self.fix else []

    def merge_tool_record(self, path):
        """Merge the edit record a KI tool wrote (domain_edit_record.py, same
        format, real cell lists). Missing record = the tool did not apply the
        rule (old tool) -> stop."""
        p = Path(path)
        if not p.is_file():
            raise DomainEditError(f"KI tool wrote no edit record {p}; its fills cannot be accounted for")
        rec = json.loads(p.read_text())
        gated = [e for e in rec.get("edits", []) if e.get("kind") != "water_cell_placeholder"]
        if bool(rec.get("settings", {}).get("fix_domain_gaps")) and gated and not self.fix:
            # stand-ins applied under the flag, but this run does not allow them
            raise DomainEditError(f"{p} holds {sum(int(e.get('count', 0)) for e in gated)} cells of "
                                  f"stand-in edits made with --fix-domain-gaps; this run is without the flag")
        for e in rec.get("edits", []):
            self.edits.append(e)
            if e.get("tag") == "soil_fill_on_land":
                self.tool_soil_cells.update((c["j"], c["i"]) for c in e.get("cells", [])
                                            if isinstance(c, dict))
        self.checked.append(str(p))
        n = int(rec.get("n_edited_cells_total", 0))
        self.log(f"  merged KI tool edit record {p.name}: {n} edited cells")
        return rec

    # ------------------------------------------------------------- stages
    def geo_em(self, path, check_greenfrac=True):
        import netCDF4 as nc
        ds = nc.Dataset(str(path), "a" if self.fix else "r")
        try:
            self.latlon = self._coords(ds)
            land = np.squeeze(np.asarray(ds["LANDMASK"][:])) > 0.5
            n_land = int(land.sum())
            if n_land == 0:
                raise DomainEditError(f"{path}: LANDMASK has no land cells")
            self.geo_path = str(path)
            needed = []
            gaps = {}
            for v in ("SCT_DOM", "SCB_DOM"):
                if v in ds.variables:
                    arr = np.asarray(ds[v][:], dtype="f8")          # (1, sn, we)
                    m = (np.round(arr) == WATER_SOIL) & land[None, ...]
                    if m.any():
                        try:
                            filled, info = _der.neighbour_class_fill(
                                np.round(arr[0]).astype(int), m[0], land & ~m[0], latlon=self.latlon)
                        except ValueError as exc:
                            raise DomainEditError(f"{path}: {v} gaps cannot be filled from neighbours: {exc}")
                        gaps[v] = (filled, info)
                    needed.append((v, f"{v}=={WATER_SOIL} (water) on land -> most common class of the "
                                      f"nearest valid land neighbours", "fill_missing_data", m, arr))
            gf = np.asarray(ds["GREENFRAC"][:], dtype="f8") if "GREENFRAC" in ds.variables else None
            if gf is not None and check_greenfrac:
                needed.append(("GREENFRAC", "GREENFRAC < 0.01 -> 0.01", "model_stability_guard",
                               gf < 0.01, gf))
            needed = self._need(needed)
            # (no 1 % limit: removed by owner decision 2026-10-05)
            for var, rule, kind, mask, data in needed:
                if var in ("SCT_DOM", "SCB_DOM"):
                    filled, info = gaps[var]
                    newv = np.asarray(ds[var][:]).copy()
                    newv[0][mask[0]] = filled[mask[0]]
                    old = np.asarray(ds[var][:], dtype="f8")[mask]
                    cells = self._cells(mask)
                    for c in cells:
                        c.update(info.get((c["j"], c["i"]), {}))
                    self.edits.append({"file": Path(path).name, "variable": var, "rule": rule,
                                       "kind": kind, "count": int(mask.sum()),
                                       "old_min": float(old.min()), "old_max": float(old.max()),
                                       "old_nonfinite": 0, "new_value": "neighbour class (cells[].class_taken)",
                                       "tag": "soil_fill_on_land", "cells": cells})
                    ds[var][:] = newv
                    cat = "SOILCTOP" if var == "SCT_DOM" else "SOILCBOT"
                    if cat in ds.variables:
                        a = np.asarray(ds[cat][:], dtype="f8")       # (1, 16, sn, we)
                        newa = a.copy()
                        for (jj, ii), d in info.items():
                            newa[0, :, jj, ii] = 0.0
                            newa[0, d["class_taken"] - 1, jj, ii] = 1.0
                        ds[cat][:] = newa
                        self.edits.append({
                            "file": Path(path).name, "variable": cat,
                            "rule": f"category fractions on the {var} cells -> 100 % of the class taken",
                            "kind": "fill_missing_data", "count": int(mask.sum()),
                            "old_min": None, "old_max": None, "old_nonfinite": 0,
                            "new_value": "fraction 1 for the class taken, others 0",
                            "tag": "soil_fill_on_land", "cells": cells})
                    self.log(f"  domain edit {Path(path).name}:{var} -> {int(mask.sum())} cells from neighbours")
                elif var == "GREENFRAC":
                    self._apply(ds, path, var, rule, kind, mask, 0.01)
            self.checked.append(str(path))
        finally:
            ds.close()

    def wrfinput(self, path, check_shd=True):
        import netCDF4 as nc
        ds = nc.Dataset(str(path), "a" if self.fix else "r")
        try:
            if self.latlon is None:
                self.latlon = self._coords(ds)
            needed = []
            if check_shd:
                for v in ("SHDMAX", "SHDMIN"):
                    if v in ds.variables:
                        a = np.asarray(ds[v][:], dtype="f8")
                        needed.append((v, f"{v} < 1 % -> 1 %", "model_stability_guard", a < 1.0, a))
            # SMOIS / TSLB: LAND cells only (XLAND == 1). On water cells the
            # water-soil row gives SMOIS 0 by construction; they are not soil.
            _xl = np.squeeze(np.asarray(ds["XLAND"][:])) if "XLAND" in ds.variables else None
            for v, floor in (("SMOIS", self.smois_floor), ("TSLB", self.tslb_floor)):
                if v not in ds.variables:
                    continue
                a = np.ma.filled(ds[v][:].astype("f8"), np.nan)
                _landm = (np.broadcast_to(_xl < 1.5, a.shape) if _xl is not None
                          else np.ones(a.shape, dtype=bool))
                bad = (~np.isfinite(a) | (a <= 0)) & _landm
                if floor is None:
                    if bad.any():
                        # no floor given: non-finite / <= 0 values can only stop
                        needed.append((v, f"{v} non-finite or <= 0 (no --{v.lower()}-floor given)",
                                       "start_value_adjustment", bad, a))
                    continue
                m = bad | ((a < floor) & _landm)
                needed.append((v, f"{v} = max({v}, {floor})", "start_value_adjustment", m, a))
            needed = self._need(needed)
            for var, rule, kind, mask, data in needed:
                if "no --" in rule:
                    raise DomainEditError(f"{path}: {var} has {int(mask.sum())} non-finite or <= 0 "
                                          f"cells and no --{var.lower()}-floor was given")
                new = {"SHDMAX": 1.0, "SHDMIN": 1.0, "SMOIS": self.smois_floor,
                       "TSLB": self.tslb_floor}[var]
                self._apply(ds, path, var, rule, kind, mask, float(new))
            self.checked.append(str(path))
        finally:
            ds.close()

    def soil(self, path):
        """smc* <= 0 (a land cell whose class row has no soil water values) is a
        soil gap: the cell's class is taken from its nearest valid land
        neighbours (same rule as the KI tools) and smcmax/smcwlt/smcref then come
        from that class's own SOILPARM.TBL row -- no fixed numbers."""
        import netCDF4 as nc
        ds = nc.Dataset(str(path), "a" if self.fix else "r")
        try:
            needed = []
            arrs = {}
            # LAND cells only: the water-soil row is 0 on water cells by construction
            if not self.geo_path:
                raise DomainEditError("soil check needs the geo_em (land mask); run geo_em() first")
            _g = nc.Dataset(self.geo_path, "r")
            _landmask = np.squeeze(np.asarray(_g["LANDMASK"][:])) > 0.5
            _g.close()
            for v in ("smcmax", "smcwlt", "smcref"):
                if v in ds.variables:
                    a = np.ma.filled(ds[v][:].astype("f8"), np.nan)
                    arrs[v] = a
                    needed.append((v, f"{v} <= 0 on land -> SOILPARM row of the neighbour class",
                                   "fill_missing_data",
                                   (~np.isfinite(a) | (a <= 0)) & np.broadcast_to(_landmask, a.shape), a))
            needed = self._need(needed)
            if needed:
                if not self.soilparm_tbl or not self.geo_path:
                    raise DomainEditError("smc* edits need SOILPARM.TBL and the geo_em (class grid)")
                g = nc.Dataset(self.geo_path, "r")
                cls = np.round(np.squeeze(np.asarray(g["SCT_DOM"][:]))).astype(int)
                land = np.squeeze(np.asarray(g["LANDMASK"][:])) > 0.5
                g.close()
                rows = soilparm_rows(self.soilparm_tbl)
                gap2d = np.zeros_like(land)
                for var, rule, kind, mask, data in needed:
                    gap2d |= mask.reshape(-1, *mask.shape[-2:]).any(axis=0)
                bad_cls = land & (~np.isin(cls, list(rows.keys())) | (cls == WATER_SOIL))
                gap2d |= bad_cls
                filled, info = _der.neighbour_class_fill(cls, gap2d & land, land & ~gap2d,
                                                         latlon=self.latlon)
                if (gap2d & ~land).any():
                    raise DomainEditError(f"{path}: smc* <= 0 on water cells; not a soil gap to fill")
                for var, rule, kind, mask, data in needed:
                    key = {"smcmax": "smcmax", "smcwlt": "smcwlt", "smcref": "smcref"}[var]
                    a = ds[var][:]
                    newa = np.ma.getdata(a).copy()
                    old = np.ma.getdata(a)[mask]
                    for (jj, ii), d in info.items():
                        row = rows.get(d["class_taken"])
                        if row is None:
                            raise DomainEditError(f"class {d['class_taken']} has no SOILPARM row")
                        sel = mask[..., jj, ii]
                        newa[..., jj, ii] = np.where(sel, row[key], newa[..., jj, ii])
                    cells = self._cells(mask)
                    for c in cells:
                        c.update(info.get((c["j"], c["i"]), {}))
                    fin = old[np.isfinite(old)]
                    self.edits.append({"file": Path(path).name, "variable": var, "rule": rule,
                                       "kind": kind, "count": int(mask.sum()),
                                       "old_min": float(fin.min()) if fin.size else None,
                                       "old_max": float(fin.max()) if fin.size else None,
                                       "old_nonfinite": int(old.size - fin.size),
                                       "new_value": "SOILPARM row of cells[].class_taken",
                                       "tag": "soil_fill_on_land", "cells": cells})
                    ds[var][:] = newa
                    self.log(f"  domain edit {Path(path).name}:{var} -> {int(mask.sum())} cells "
                             f"(class from neighbours, values from SOILPARM.TBL)")
            self.checked.append(str(path))
        finally:
            ds.close()

    # ------------------------------------------------------------- record
    def record(self):
        by = {}
        for e in self.edits:
            by.setdefault(e["kind"], []).append(
                {k: e[k] for k in ("file", "variable", "rule", "count", "old_min",
                                   "old_max", "old_nonfinite", "new_value")})
        return {"written_at": _dt.datetime.now().isoformat(timespec="seconds"),
                "settings": self.settings(), "history": self.history,
                "files_checked": self.checked,
                "n_edited_cells_total": int(sum(e["count"] for e in self.edits)),
                "summary_by_kind": by, "edits": self.edits}

    def write(self, *paths):
        rec = self.record()
        # sha256 of the DOMAIN *.nc files the record describes (the folder of the
        # first path named domain_edits.json), so a reused record can be checked
        # against the files it was written for (domain_record_matches).
        for q in paths:
            if Path(q).name == RECORD and any(Path(q).parent.glob("*.nc")):
                rec["files_sha256"] = domain_file_hashes(Path(q).parent)
                break
        txt = json.dumps(rec, indent=1)
        for p in paths:
            p = Path(p)
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_text(txt)
            os.replace(tmp, p)
        return rec


def summary_for_result(rec):
    """Short form for result.json['domain_edits'] (cells stay in domain_edits.json)."""
    return {"settings": rec.get("settings"),
            "n_edited_cells_total": rec.get("n_edited_cells_total"),
            "summary_by_kind": rec.get("summary_by_kind"),
            "full_record": RECORD}


def summary_sentence(rec):
    by = rec.get("summary_by_kind") or {}
    hist = rec.get("history", "complete")
    if hist != "complete":
        return (f"Domain edits: HISTORY UNKNOWN ({hist}); this run found "
                f"{rec.get('n_edited_cells_total', 0)} edited cells, earlier edits cannot be seen.")
    if not by:
        return "Domain edits: none (no stand-in edit was needed)."
    words = {"fill_missing_data": "filled missing data",
             "model_stability_guard": "model-stability guards",
             "start_value_adjustment": "start-value adjustments"}
    parts = []
    for kind, rows in by.items():
        parts.append(f"{words.get(kind, kind)}: " + ", ".join(
            f"{r['variable']} {r['count']} cells ({r['rule']})" for r in rows))
    return ("Domain edits (opted in with --fix-domain-gaps, every cell in domain_edits.json): "
            + "; ".join(parts) + ".")


def domain_file_hashes(domain_dir):
    """sha256 of every *.nc directly in domain_dir (name -> hex)."""
    import hashlib
    out = {}
    for f in sorted(Path(domain_dir).glob("*.nc")):
        h = hashlib.sha256()
        with open(f, "rb") as fh:
            for b in iter(lambda: fh.read(1 << 20), b""):
                h.update(b)
        out[f.name] = h.hexdigest()
    return out


def archive_record(domain_dir, log=print):
    """Before a DOMAIN is (partly) rebuilt: the aggregate record describes the
    OLD files, so move it to domain_edits.json.previous_<time> (kept). The new
    record is then made from the new files and tool records."""
    p = Path(domain_dir) / RECORD
    if not p.is_file():
        return None
    keep = p.with_name(f"{RECORD}.previous_{_dt.datetime.now():%Y%m%dT%H%M%S}")
    os.replace(p, keep)
    log(f"  domain: rebuild -> old edit record kept as {keep.name}")
    return keep


def domain_record_matches(domain_dir, edits):
    """A reused DOMAIN must carry a domain_edits.json written with the same
    settings AND for the same files (files_sha256 equal to the DOMAIN *.nc now);
    otherwise its edit history is unknown. Returns (ok, why, rec)."""
    p = Path(domain_dir) / RECORD
    if not p.is_file():
        return False, f"no {RECORD} in {domain_dir} (edit history unknown)", None
    try:
        rec = json.loads(p.read_text())
    except (OSError, ValueError) as e:
        return False, f"{p} unreadable: {e}", None
    if rec.get("settings") != json.loads(json.dumps(edits.settings())):
        return False, f"{p} written with other settings {rec.get('settings')}", rec
    if "files_sha256" not in rec:
        return False, f"{p} has no files_sha256 (older record): cannot show it is for these files", rec
    now = domain_file_hashes(domain_dir)
    if rec["files_sha256"] != now:
        diff = sorted(k for k in set(now) | set(rec["files_sha256"])
                      if now.get(k) != rec["files_sha256"].get(k))
        return False, f"{p} was written for other domain files (changed: {diff})", rec
    return True, "domain edit record matches (settings and file hashes)", rec


def move_domain_aside(domain_dir, log=print):
    """Keep an old DOMAIN (moved to a dated sibling), never delete it."""
    d = Path(domain_dir)
    if not d.exists():
        return None
    stamp = f"{d.name}.previous_{_dt.datetime.now():%Y%m%dT%H%M%S}"
    dest, n = d.with_name(stamp), 1
    while dest.exists():                 # two moves in the same second
        dest, n = d.with_name(f"{stamp}_{n}"), n + 1
    os.rename(d, dest)
    log(f"  DOMAIN moved to {dest.name} (kept): rebuilt so every edit is recorded")
    return dest


# Written by a runner when it starts a DOMAIN rebuild and removed only when every
# file is built. While it exists the DOMAIN is a mix of new and missing files and
# must be neither reused nor recorded.
REBUILD_MARK = ".rebuild_incomplete"


def start_rebuild(domain_dir, log=print):
    """Begin a DOMAIN rebuild in a FRESH folder: the old DOMAIN (files and edit
    record) is moved aside whole (kept, never deleted), then an empty DOMAIN with
    the incomplete-rebuild mark is made."""
    d = Path(domain_dir)
    if d.exists() and any(d.iterdir()):
        move_domain_aside(d, log)
    d.mkdir(parents=True, exist_ok=True)
    (d / REBUILD_MARK).write_text(_dt.datetime.now().isoformat(timespec="seconds"))


def finish_rebuild(domain_dir):
    (Path(domain_dir) / REBUILD_MARK).unlink()


def rebuild_incomplete(domain_dir):
    return (Path(domain_dir) / REBUILD_MARK).exists()


ROLLBACK_DIR = ".domain_edits_rollback"
ROLLBACK_FILES = ("geo_em.d01.nc", "wrfinput_d01.nc", "soil_properties.nc", RECORD)


def _restore_rollback(domain_dir, log=print):
    """Put back the files saved by _make_rollback (after an error or a crash)."""
    import shutil
    rb = Path(domain_dir) / ROLLBACK_DIR
    if not rb.is_dir():
        return False
    present = {f.name for f in rb.iterdir()}
    for name in ROLLBACK_FILES:
        dest = Path(domain_dir) / name
        if name in present:
            os.replace(rb / name, dest)
        elif name == RECORD and dest.exists():
            dest.unlink()          # there was no record before the failed attempt
    shutil.rmtree(rb)
    log(f"  domain: unfinished edit attempt rolled back from {ROLLBACK_DIR}/")
    return True


def _make_rollback(domain_dir, log=print):
    import shutil
    domain_dir = Path(domain_dir)
    rb = domain_dir / ROLLBACK_DIR
    tmp = domain_dir / (ROLLBACK_DIR + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)         # half-written copy: the originals were not touched yet
    tmp.mkdir()
    for name in ROLLBACK_FILES:
        src = domain_dir / name
        if src.is_file():
            shutil.copy2(src, tmp / name)
    os.replace(tmp, rb)            # rollback folder appears complete or not at all
    return rb


def ensure_domain_record(domain_dir, edits, state_dir, log=print, check_greenfrac=False,
                         check_shd=False):
    """For runners that reuse or build a DOMAIN without their own edit steps:
    a DOMAIN with a matching domain_edits.json is accepted as is. Otherwise the
    KI tool records found in DOMAIN are merged, the domain files are scanned
    (soil gaps, smc <= 0, SMOIS/TSLB; GREENFRAC/SHD floors only if asked) --
    stopping without --fix-domain-gaps, filling from neighbours and recording
    with it -- and the record is written to DOMAIN/ and state_dir/."""
    domain_dir = Path(domain_dir)
    if rebuild_incomplete(domain_dir):
        raise DomainEditError(f"{domain_dir}: a DOMAIN rebuild did not finish ({REBUILD_MARK} "
                              f"present); rebuild it again before it is used or recorded")
    _restore_rollback(domain_dir, log)       # a crashed earlier attempt: undo it first
    ok, why, rec = domain_record_matches(domain_dir, edits)
    if ok:
        log(f"  domain: {why}")
        (Path(state_dir) / RECORD).write_text(json.dumps(rec, indent=1))
        return rec
    # 2026-10-15: never overwrite an existing edit history. The KI tool records
    # (domain_edits.<tool>.json) are merged again below, so their edits are kept.
    # But edits this module made itself (runner floors / soil fills, written only
    # to domain_edits.json) would be lost: a rescan with other settings no longer
    # sees the already-changed values and the new record would claim "no edit".
    # So: if the old record holds more edited cells than the tool records now on
    # disk account for, stop -- rerun with the record's settings, or rebuild the
    # DOMAIN (move_domain_aside keeps the old one). An unreadable record = unknown
    # history = stop. Otherwise the old record is kept as a dated copy.
    p_rec = domain_dir / RECORD
    tool_files = [domain_dir / f"domain_edits.{tool}.json" for tool in TOOL_RECORDS]
    if p_rec.is_file():
        if rec is None:
            raise DomainEditError(f"{p_rec} is unreadable ({why}); the edit history of this DOMAIN "
                                  f"is unknown. Rebuild the DOMAIN instead of reusing it.")
        n_prev = int(rec.get("n_edited_cells_total") or 0)
        n_tool = 0
        for f in tool_files:
            if f.is_file():
                try:
                    n_tool += int(json.loads(f.read_text()).get("n_edited_cells_total") or 0)
                except (OSError, ValueError) as exc:
                    raise DomainEditError(f"{f} unreadable: {exc}")
        if n_prev > n_tool:
            raise DomainEditError(
                f"{p_rec} cannot be reused ({why}). It records {n_prev} edited cells (settings "
                f"{rec.get('settings')}), but the KI tool records on disk account for only {n_tool}; "
                f"the other {n_prev - n_tool} may still be in the domain files and a rescan would not "
                f"see them. This run uses {edits.settings()}. Rerun with the record's settings on "
                f"the same files, or rebuild the DOMAIN (move_domain_aside keeps the old one) so "
                f"the record stays true.")
    if rec is not None and rec.get("history", "complete") != "complete":
        edits.history = rec["history"]          # once unknown, always unknown
    # When is the history known well enough to rescan and write a "complete"
    # record? (a clean rescan cannot see values changed earlier without a record)
    #  * no domain_edits.json: only if every KI build tool left its own record
    #    (a DOMAIN built by the current tools);
    #  * domain_edits.json with files_sha256: only if the DOMAIN *.nc files are
    #    still exactly those it was written for (a later, unrecorded change such
    #    as a hand-made SMOIS floor makes them differ);
    #  * domain_edits.json without files_sha256 (pipeline / older record): only if
    #    every KI build tool left its own record.
    # Otherwise stop, unless --accept-unknown-domain-history: then the record
    # says "history unknown", never "no edits".
    build_tools = ("build_geo_em", "build_wrfinput", "build_fulldom_hires",
                   "build_soil_properties", "build_groundwater")
    missing = [t_ for t_ in build_tools if not (domain_dir / f"domain_edits.{t_}.json").is_file()]
    unknown = None
    if rec is not None and "files_sha256" in rec:
        now_h = domain_file_hashes(domain_dir)
        if rec["files_sha256"] != now_h:
            changed = sorted(k for k in set(now_h) | set(rec["files_sha256"])
                             if now_h.get(k) != rec["files_sha256"].get(k))
            unknown = (f"the DOMAIN files changed after {RECORD} was written (changed: {changed}) "
                       f"and nothing records how")
    elif missing:
        unknown = (f"{domain_dir} has {'no ' + RECORD if rec is None else RECORD + ' without file hashes'} "
                   f"and no edit record from {', '.join(missing)}")
    if unknown:
        msg = unknown + ": its edit history is unknown"
        if not edits.accept_unknown_history:
            raise DomainEditError(msg + "; rebuild the DOMAIN (move_domain_aside keeps the old "
                                  "one), or pass --accept-unknown-domain-history to reuse it "
                                  "with a record that says 'history unknown'")
        edits.history = "unknown: " + msg
        log(f"  domain: WARNING {msg}; reused on request, recorded as history unknown")
    log(f"  domain: {why} -> scanning the domain files")
    # All-or-nothing: the scan edits the NetCDF files in place one variable at a
    # time and a later check can still stop (e.g. SMOIS <= 0 without a floor).
    # The domain files and the old record are copied to a rollback folder first;
    # on any error they are put back, so no edit stays without a record. The
    # folder is removed only after the new record is written (a crash leaves it,
    # and _restore_rollback puts the files back at the next call).
    rb = _make_rollback(domain_dir, log)
    try:
        for f in tool_files:
            if f.is_file():
                edits.merge_tool_record(f)
        if (domain_dir / "geo_em.d01.nc").is_file():
            edits.geo_em(domain_dir / "geo_em.d01.nc", check_greenfrac=check_greenfrac)
        if (domain_dir / "wrfinput_d01.nc").is_file():
            edits.wrfinput(domain_dir / "wrfinput_d01.nc", check_shd=check_shd)
        if (domain_dir / "soil_properties.nc").is_file():
            edits.soil(domain_dir / "soil_properties.nc")
        if p_rec.is_file():
            keep = p_rec.with_name(f"{RECORD}.previous_{_dt.datetime.now():%Y%m%dT%H%M%S}")
            os.replace(p_rec, keep)
            log(f"  domain: old record kept as {keep.name}")
        rec = edits.write(domain_dir / RECORD, Path(state_dir) / RECORD)
    except BaseException:
        _restore_rollback(domain_dir, log)
        raise
    import shutil
    shutil.rmtree(rb)
    log("  " + summary_sentence(rec))
    return rec
