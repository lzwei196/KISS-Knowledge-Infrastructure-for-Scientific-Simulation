#!/usr/bin/env python3
"""configure_kineros2_sediment.py -- set up / check KINEROS2 erosion & sediment transport tags.

KINEROS2 routes sediment only when the run's sediment flag is Y (run_kineros2_engine.py
--sediment) AND the parameter file carries the sediment tags.  The default method is Smith's
(splash + hydraulic erosion, up to 5 particle classes):
  GLOBAL   DIAMS   = d1, d2, ...  particle diameters, mm (METRIC) or INCHES (ENGLISH), <= 5 classes
           DENSITY = r1, r2, ...  g/cc, one per class (engine stops 'missing particle density')
           TEMP    = T            water temperature, deg C (METRIC) or deg F (ENGLISH)
  PLANE    SPLASH  = s            rain splash coefficient            (required unless PAV >= 1)
           COH     = c            soil cohesion coefficient          (required unless PAV >= 1)
           FRACT   = f1, f2, ...  class fractions in DIAMS order; |sum - 1| <= 0.05 or the engine stops
           PAV     = p            optional erosion pavement fraction (0-1; 1 = non-eroding)
  CHANNEL  COH, FRACT (bed material), optional PAV
Method switch (per element, by PRESENCE of a tag): 'KE' -> RHEM, 'KR' -> DWEPP, neither -> Smith.
'KE' is also read as the element's Ks, so it is not a harmless alias.

Modes
  --check PAR                 report method per element and every sediment tag the engine will miss
  --par IN --out OUT ...      copy-first: write GLOBAL class tags and element tags into a copy
     --diams 0.005,0.05,0.25 --density 2.65,2.60,2.60 --temp 33
     --plane-fract 0.2,0.6,0.2 --splash 50 --cohesion 0.5
     --channel-fract 0,0.4,0.6 --channel-cohesion 0.01 [--channel-pav 0.6]
  (values above are the ARS EX1 sample's; they are a format example, not site defaults)

Exit codes: 0 ok | 2 bad input or the file is not sediment-ready
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _k2lib as k2  # noqa: E402
from edit_kineros2_par import _targets, set_list, set_value  # noqa: E402


def _floats(s):
    return [float(x) for x in s.split(",")] if s else None


def check(tf) -> dict:
    errs, info = [], []
    g = k2.global_block(tf)
    diams = [float(v) for v in g.get_list("DI", 5)] if g else []
    dens = [float(v) for v in g.get_list("DE", 5)] if g else []
    units = k2.par_units(tf)
    if not diams:
        errs.append("GLOBAL has no DIAMS -> engine stops 'particle classes not defined'")
    if len(dens) < len(diams):
        errs.append(f"GLOBAL DENSITY has {len(dens)} values for {len(diams)} DIAMS -> 'missing particle density'")
    if g and g.get_float("T") is None:
        info.append("GLOBAL TEMP missing -> engine uses 0 deg for viscosity")
    if diams and units == "english" and max(diams) > 0.5:
        errs.append(f"DIAMS {diams} look like MILLIMETRES but UNITS=ENGLISH expects inches")
    if diams and units == "metric" and max(diams) < 0.0005:
        errs.append(f"DIAMS {diams} look like INCHES/metres but UNITS=METRIC expects mm")
    methods = {}
    for b in tf.blocks[1:]:
        if b.name not in ("PLANE", "CHANNEL"):
            continue
        meth = "RHEM" if b.lookup("KE")[0] is not None else ("DWEPP" if b.lookup("KR")[0] is not None else "Smith")
        methods[b.element_id] = meth
        if meth != "Smith":
            continue
        pav = b.get_float("PA") or 0.0
        if pav > 1.00001:
            errs.append(f"{b.name} {b.element_id}: PAV={pav} > 1")
        if pav < 1.0:
            if b.name == "PLANE" and b.lookup("SPL")[0] is None:
                errs.append(f"PLANE {b.element_id}: no SPLASH -> engine stops 'rain splash coefficient (SP) not found'")
            if b.lookup("CO")[0] is None:
                errs.append(f"{b.name} {b.element_id}: no COH -> engine stops 'soil cohesion coefficient (CO) not found'")
        fr = [float(v) for v in b.get_list("FR", 5)]
        if diams and fr and abs(sum(fr[:len(diams)]) - 1.0) > 0.05:
            errs.append(f"{b.name} {b.element_id}: FRACT {fr} sums to {sum(fr):.3f} -> 'fractions do not add to 1'")
        if diams and not fr:
            errs.append(f"{b.name} {b.element_id}: no FRACT")
        if diams and fr and len(fr) != len(diams):
            errs.append(f"{b.name} {b.element_id}: {len(fr)} FRACT values for {len(diams)} DIAMS classes")
    if len(set(methods.values())) > 1:
        info.append(f"mixed sediment methods {set(methods.values())}: the method is a module-level switch reset "
                    f"per element in kinsed.f90 -- mixing is untested")
    return {"units": units, "diams": diams, "density": dens, "methods": methods, "errors": errs, "notes": info}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", help="parameter file to check")
    ap.add_argument("--par"); ap.add_argument("--out")
    ap.add_argument("--diams"); ap.add_argument("--density"); ap.add_argument("--temp", type=float)
    ap.add_argument("--plane-fract"); ap.add_argument("--splash", type=float); ap.add_argument("--cohesion", type=float)
    ap.add_argument("--plane-pav", type=float)
    ap.add_argument("--channel-fract"); ap.add_argument("--channel-cohesion", type=float)
    ap.add_argument("--channel-pav", type=float)
    a = ap.parse_args(argv)
    try:
        if a.check:
            r = check(k2.read_tagged(a.check))
            for k in ("units", "diams", "density", "methods"):
                print(f"{k}: {r[k]}")
            for n in r["notes"]:
                print(f"note: {n}")
            for e in r["errors"]:
                print(f"ERROR: {e}")
            print("sediment-ready" if not r["errors"] else f"{len(r['errors'])} problem(s)")
            return 2 if r["errors"] else 0
        if not (a.par and a.out):
            ap.error("give --check PAR, or --par IN --out OUT with the values to set")
        diams, dens = _floats(a.diams), _floats(a.density)
        if diams and (not dens or len(dens) != len(diams)):
            raise ValueError("--density needs one value per --diams class")
        if diams and len(diams) > 5:
            raise ValueError("KINEROS2 supports at most 5 particle classes")
        for nm, fr in (("--plane-fract", _floats(a.plane_fract)), ("--channel-fract", _floats(a.channel_fract))):
            if fr and abs(sum(fr) - 1.0) > 0.05:
                raise ValueError(f"{nm} {fr} sums to {sum(fr):.3f}; must be 1 +/- 0.05")
            if fr and diams and len(fr) != len(diams):
                raise ValueError(f"{nm} has {len(fr)} values for {len(diams)} classes")
        specs = []
        if diams:
            # list tags must be written in one go: replace/insert the whole line text
            specs.append(("GLOBAL", "DIAMS", ", ".join(f"{d:g}" for d in diams)))
            specs.append(("GLOBAL", "DENSITY", ", ".join(f"{d:g}" for d in dens)))
        if a.temp is not None:
            specs.append(("GLOBAL", "TEMP", f"{a.temp:g}"))
        if a.plane_fract:
            specs.append(("PLANE", "FRACT", a.plane_fract.replace(",", ", ")))
        if a.splash is not None:
            specs.append(("PLANE", "SPLASH", f"{a.splash:g}"))
        if a.cohesion is not None:
            specs.append(("PLANE", "COH", f"{a.cohesion:g}"))
        if a.plane_pav is not None:
            specs.append(("PLANE", "PAV", f"{a.plane_pav:g}"))
        if a.channel_fract:
            specs.append(("CHANNEL", "FRACT", a.channel_fract.replace(",", ", ")))
        if a.channel_cohesion is not None:
            specs.append(("CHANNEL", "COH", f"{a.channel_cohesion:g}"))
        if a.channel_pav is not None:
            specs.append(("CHANNEL", "PAV", f"{a.channel_pav:g}"))
        tf = k2.read_tagged(a.par)
        for sel, tag, val in specs:
            vals = [v.strip() for v in val.split(",")]
            for bi in _targets(tf, sel):
                if len(vals) > 1 or tag in ("DIAMS", "DENSITY", "FRACT"):
                    set_list(tf, bi, tag, vals)
                else:
                    set_value(tf, bi, tag, 1, vals[0])
        tf.write(a.out)
        r = check(k2.read_tagged(a.out))
        print(f"wrote {a.out}; methods {r['methods']}")
        for e in r["errors"]:
            print(f"ERROR: {e}")
        return 2 if r["errors"] else 0
    except (ValueError, k2.EngineError, FileNotFoundError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
