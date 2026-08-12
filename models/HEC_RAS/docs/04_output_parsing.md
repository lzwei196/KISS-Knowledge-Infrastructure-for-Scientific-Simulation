# Stage 04 — Output Parsing

**Purpose.** Extract genuine solver results from the HEC-RAS results HDF5 into
tidy per-(profile, cross-section) records (CSV/JSON). Nothing is recomputed.

**Inputs.** `<prj>.pNN.tmp.hdf` (or `.pNN.hdf`) produced by `RasSteady.exe`.

**Outputs.** A record list with: `profile`, `xs_index`, `river_station`, `ws`,
`eg`, `q`, `vel_chnl`, `vel_total`, `hyd_depth`, `top_width`, `flow_area`,
`shear`, `frict_slope`, `crit_ws`, plus derived `froude` and `regime`
(sub/super/critical). Optional CSV + JSON.

**Procedure.**
```bash
python3 tools/parse_output_hecras.py --hdf out/MIXED.p01.tmp.hdf \
        --csv out/results.csv --json out/results.json
```
Results live at HDF path
`/Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Cross Sections/`:
`Water Surface`, `Energy Grade`, `Flow` are `[n_profiles, n_xs]`; the
`Additional Variables/` group holds velocity, depth, width, area, Froude, shear…

**Verification.** `validate_outputs()` requires ≥1 record and finite WS. Spot
check: energy grade ≥ water surface at every cross section (EG = WS + αV²/2g),
and discharge constant along the reach (mass conservation).

**Traps.**
- The `Profile Names` dataset lives one level up (`…/Steady Profiles/Profile
  Names`), not under `Cross Sections/` — the parser handles both.
- River-station labels come from `/Geometry/Cross Sections/...` as **byte
  strings** — decode them (the parser does).
- If the solver value `Froude # Channel` is absent/zero the parser derives
  `Fr = V/√(gD)` with g = 32.174 ft/s² (English).
- `.ONN` is a **binary** legacy file — read the HDF, not `.ONN`.

**Example.** First record (Mixed Flow, Q=500): `ws=71.87, eg=74.66, q=500,
vel_chnl=13.40, froude=1.73, regime=supercritical`.
