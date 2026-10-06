#!/usr/bin/env python3
"""Write parameter_slm_run.list: proportional changes to QUINCY parameters (calibration lever).

The real engine reads this file when base_ctl set_parameter_values_from_file = .TRUE.
(mo_qs_set_parameters.f90). tools/run_quincy_engine.py --param_list sets that flag AND
set_parameter_values_proportional = .TRUE., so every value here is a MULTIPLIER of the engine
default (1.0 = unchanged; 0.8 = -20 %). Proportional mode is used on purpose: in absolute mode
the engine converts some file values first (e.g. jmax2n / 4, chl2n / 39.8, k1_fn_struc * M_N / 1e6),
so an absolute value in "natural" units would be silently wrong.

Engine rules (Set_quincy_parameter_value): for a NEGATIVE default the multiplier acts on the
size of the change, not the sign; t_ref_decomposition, t_opt_nitrification and
lctlib_t_air_senescence scale the departure from 273.15 K.

Valid names are read from the engine source NAMELIST blocks, so a typo is refused here instead
of crashing the Fortran namelist reader. A name the engine READS but never APPLIES (its
Set_quincy_parameter_value call is commented out because the engine recomputes the value from
other parameters: lctlib fn_oth_min, k_rtos, c0_allom in qs-2026.04-public) is refused too,
since the change would silently do nothing. Groups:
  lnd_q_assimi_nml lnd_q_pheno_nml jsb_rad_nml qs_shared_nml lnd_spq_nml lnd_veg_nml lnd_sb_nml
  lctlib_pft<N>_nml (PFT-specific, N = 1..8; the engine applies only the group of the run's PFT)
The engine writes what it applied to parameter_sensi_param_values.txt /
parameter_sensi_lctlib_values.txt (old and new value); the run tool records changed rows.

Usage: edit_quincy_parameters.py --set vcmax2n=1.1 --set sla=0.9 --pft 5 --out p.list
Exit codes: 0 ok, 2 unknown/ambiguous name, bad multiplier, or engine source not found.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _quincy_common import ENGINE_ROOT, finite  # noqa: E402

SRC = ENGINE_ROOT / "src/src/quincy_standalone/mo_qs_set_parameters.f90"
SLM_GROUPS = ["lnd_q_assimi_nml", "lnd_q_pheno_nml", "jsb_rad_nml", "qs_shared_nml",
              "lnd_spq_nml", "lnd_veg_nml", "lnd_sb_nml"]


def namelist_members(src_text: str) -> dict[str, list[str]]:
    """{group: [names]} for every `NAMELIST /group/ a, b, ...` block in the source."""
    out = {}
    for m in re.finditer(r"(?im)^\s*NAMELIST\s*/(\w+)/(.*?)(?=^\s*(?:NAMELIST|!|REAL|INTEGER|CHARACTER|LOGICAL|"
                         r"CALL|IF|nml_|\w+\s*=)\b)", src_text, re.S):
        names = re.findall(r"([A-Za-z_]\w*)\s*,?\s*&?", re.sub(r"!.*", "", m.group(2)))
        out[m.group(1).lower()] = [n for n in names if n]
    return out


def applied_names(src_text: str) -> set[str]:
    """Names the engine actually applies: the name string of every ACTIVE (not commented-out)
    Set_quincy_parameter_value / Modify_quincy_namelist_parameter call, plus the list variable of
    the Modify calls (e.g. f_psensi_soil_sand). lctlib names are returned without 'lctlib_'."""
    stmts, cur = [], ""
    for line in src_text.splitlines():
        s = re.sub(r"!.*", "", line).rstrip()
        if s.endswith("&"):
            cur += s[:-1] + " "
            continue
        stmts.append(cur + s)
        cur = ""
    out = set()
    for s in stmts:
        m = re.search(r"CALL\s+(Set_quincy_parameter_value|Modify_quincy_namelist_parameter)\s*\((.*)\)", s, re.I)
        if not m:
            continue
        lit = re.findall(r'"([^"]+)"', m.group(2))
        if lit:
            out.add(lit[0][len("lctlib_"):] if lit[0].startswith("lctlib_") else lit[0])
        if m.group(1).lower().startswith("modify"):
            out.add(m.group(2).split(",")[0].strip().split("%")[-1])
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", action="append", default=[], metavar="NAME=MULT",
                    help="parameter name (without _pN for PFT parameters) = multiplier (0 < m <= 5)")
    ap.add_argument("--pft", type=int, help="PFT number 1-8 for PFT-specific (lctlib) parameters")
    ap.add_argument("--list", action="store_true", help="print the valid names per group and exit")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    if not SRC.is_file():
        print(f"ERROR: engine source {SRC} not found (names are validated against it)", file=sys.stderr)
        return 2
    src_text = SRC.read_text(errors="replace")
    groups = namelist_members(src_text)
    active = applied_names(src_text)
    slm = {g: groups.get(g, []) for g in SLM_GROUPS}
    if a.list:
        print(json.dumps({**slm, **{g: v for g, v in groups.items() if g.startswith("lctlib_pft")}}, indent=1))
        return 0
    chosen: dict[str, dict[str, float]] = {}
    try:
        if not a.set or not a.out:
            raise ValueError("--set and --out are required (or use --list)")
        for item in a.set:
            if "=" not in item:
                raise ValueError(f"--set {item!r}: use NAME=MULTIPLIER")
            name, val = (s.strip() for s in item.split("=", 1))
            mult = finite(val, name, 1e-6, 5.0)
            hits = [g for g, names in slm.items() if name in names]
            if not hits and a.pft is not None:
                if not 1 <= a.pft <= 8:
                    raise ValueError("--pft must be 1-8 (the engine has PFT parameter groups for PFTs 1-8 only)")
                g = f"lctlib_pft{a.pft}_nml"
                if f"{name}_p{a.pft}" in groups.get(g, []):
                    hits, name = [g], f"{name}_p{a.pft}"
            if not hits:
                raise ValueError(f"{name!r} is not a parameter the engine reads"
                                 + ("" if a.pft else " (PFT parameters need --pft)") + "; see --list")
            if len(hits) > 1:
                raise ValueError(f"{name!r} is in several groups {hits}")
            base = re.sub(r"_p\d+$", "", name) if hits[0].startswith("lctlib_pft") else name
            if base not in active:
                raise ValueError(f"{name!r} is read by the engine but never applied (its Set_quincy_parameter_value "
                                 f"call is commented out in {SRC.name}; the engine recomputes it), so the change "
                                 "would do nothing")
            chosen.setdefault(hits[0], {})[name] = mult
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    lines = ["! parameter_slm_run.list written by tools/edit_quincy_parameters.py",
             "! values are MULTIPLIERS of the engine defaults (set_parameter_values_proportional = .TRUE.)"]
    for g, kv in chosen.items():
        lines += [f"&{g}"] + [f"  {k} = {v:.10g}" for k, v in kv.items()] + ["/"]
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text("\n".join(lines) + "\n")
    print(json.dumps({"out": a.out, "changes": chosen}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
