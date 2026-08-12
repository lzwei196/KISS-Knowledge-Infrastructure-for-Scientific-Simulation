# HEC-RAS — Input Preparation Plan (KDT Phase 1c)

> Extracted from the HEC-RAS file ecosystem (USACE HEC-RAS 6.x), the shipped
> example projects, and empirical inspection of the WINE-staged solver
> (`RasSteady.exe` 6.7 Beta 5). HEC-RAS is a **1-D/2-D river-hydraulics** model,
> **NOT a rainfall-runoff model**. Its "forcing" is *discharge* and *boundary
> stage*, not meteorology. Do not feed it precip/temp/radiation.

## 0. What kind of model is this?

HEC-RAS solves the open-channel flow equations on a network of surveyed
**cross sections**:

* **Steady** — standard-step solution of the 1-D energy equation
  (gradually-varied flow) → water-surface profile for a set of fixed discharges.
* **Unsteady** — implicit finite-difference solution of the 1-D Saint-Venant
  equations (and 2-D shallow-water equations) → time series of stage/flow.
* Add-ons: sediment transport, water quality, bridge/culvert/gate hydraulics.

The **validated, headless-drivable** capability in this environment is **steady
flow** (see `docs/03_steady_execution.md` and the Execution-architecture note
below). Unsteady/sediment/WQ solvers are present and load, but their full run
needs the `.NET` orchestrator `Ras.exe` (Wine Mono — not installed here) to
write the plan-HDF skeleton; they are documented but not end-to-end validated.

## 1. The HEC-RAS file ecosystem (per project `<PRJ>`)

| Ext        | Format     | Role | Who writes it |
|------------|------------|------|----------------|
| `.prj`     | text       | project: title, units, current plan, file list | GUI / template |
| `.gNN`     | text       | **geometry**: reaches, cross sections (Sta/Elev), Manning n, bank stations, reach lengths, exp/contr | GUI / `edit_geometry.py` |
| `.gNN.hdf` | HDF5       | geometry as HDF (preprocessed tables) | RasGeomPreprocess / GUI |
| `.fNN`     | text       | **steady flow**: profiles, discharges, boundary conditions, observed WS | GUI / `convert_flow_to_hecras.py` |
| `.uNN`     | text       | unsteady flow: hydrographs, boundary time series | GUI |
| `.pNN`     | text       | **plan**: which geom+flow, solver tolerances, flow regime (sub/super/mixed) | GUI / template |
| `.rNN`     | text       | **steady run file**: flattened geom+flow+job-control the Fortran solver reads | normally `Ras.exe`; we **edit an existing one** |
| `.pNN.tmp.hdf` | HDF5   | **plan results skeleton** the solver opens and writes results into | normally `Ras.exe`; we **seed from `.gNN.hdf`** |
| `.ONN`     | binary     | legacy detailed-output (binary) | RasSteady |
| `.cNN`     | binary     | geometry-preprocessor output (unsteady) | RasGeomPreprocess |

### CRITICAL execution architecture (verified empirically)

The Intel-Fortran solvers do **not** read the human-readable `.prj/.g/.f/.p`
files directly. `Ras.exe` (.NET, needs Wine Mono) normally:
1. flattens `.g+.f+.p` → the **`.rNN` run file**, and
2. creates the **`.pNN.tmp.hdf`** results skeleton (a copy of the geometry HDF).

Wine Mono is **not** installed here, so we cannot run `Ras.exe`. The verified
work-around for **steady** runs (which makes this KI real, not a surrogate):

```
1. Start from an existing project that already has a .rNN run file
   (every shipped example does; the GUI/ras-commander writes one).
2. Seed results skeleton:   cp <PRJ>.gNN.hdf  <PRJ>.pNN.tmp.hdf
3. Run:  wine RasSteady.exe <PRJ>.rNN      (cwd = project dir)
4. Results land in <PRJ>.pNN.tmp.hdf  ->  /Results/Steady/Output/...
```

This was proven on the *Mixed Flow Regime Channel* example: the solver printed
`Finished Steady Flow Simulation` and wrote 2 profiles × 19 cross sections of
WS/EG/Q/V (computed WS matched the example's observed WS to RMSE 0.096 ft,
NSE 0.9965). The trailing `HDF5-DIAG` lines after "Finished" are non-fatal
(the solver probes an optional group).

## 2. Required inputs & parameters (what a NEW case must supply)

| # | Input / parameter | Units the model expects | Where it lives | NEW case: supply how | If unavailable |
|---|-------------------|-------------------------|----------------|----------------------|----------------|
| 1 | Channel geometry (cross sections: station, elevation) | ft or m (per project unit system) | `.gNN` `#Sta/Elev` blocks | survey / DEM-extracted XS, or copy a template reach and edit elevations | abort — geometry is the irreducible input; cannot be defaulted |
| 2 | Reach lengths (LOB/Channel/ROB between XS) | ft or m | `.gNN` `Type RM Length L Ch R` | from station spacing | estimate from XS river-station spacing |
| 3 | Manning's roughness *n* | dimensionless | `.gNN` `#Mann` blocks | land-cover lookup (channel 0.025–0.05) | default 0.035 channel / 0.06 overbank |
| 4 | Discharge(s) Q per profile | **cfs** (English) or **m³/s** (SI) | `.fNN` flow line / `.rNN` Flow Data | design floods, or `ObservedQ` peaks via `convert_flow_to_hecras.py` | derive from regional flood-frequency or routed model output |
| 5 | Upstream boundary | type code + value | `.fNN`/`.rNN` `Up Type/Slope` | normal depth (energy slope) is robust default `Up Type=3` | use bed slope as energy slope |
| 6 | Downstream boundary | type code + value | `.fNN`/`.rNN` `Dn Type/Slope` | normal depth slope, known WS, or rating curve | use bed slope |
| 7 | Flow regime | Subcritical/Supercritical/Mixed | `.pNN` | Mixed if unsure (handles hydraulic jumps) | Mixed |
| 8 | Unit system | English / SI | `.prj` (`English Units` / `SI Units`) | match the geometry survey | English (US default) |
| 9 | Exp/Contr coefficients | dimensionless | `.gNN` per-XS / `.rNN` | 0.1/0.3 (gradual), 0.3/0.5 (bridges) | 0.1 contr / 0.3 exp |

**Observed WS (validation, optional):** `.fNN` `Observed WS=` lines carry
measured water-surface elevations per cross section — used by
`validate_hecras.py` for real-tier validation. Not an input to the solve.

## 3. Layer-1 (ki_tools_common) integration

HEC-RAS consumes **discharge**, so the meteorological `load_daily_forcing`
loader is *not* the right Layer-1 entry point. The discharge tie-in is:

* `convert_flow_to_hecras.py` accepts discharge values directly **or** reads an
  `ObservedQ` CSV (see `data_ki/ObservedQ/SKILL.md`) and writes the chosen
  design discharges (e.g. annual peaks / quantiles) into a steady `.fNN`/`.rNN`
  as flow profiles. Units are converted with
  `ki_tools_common.units.convert` (m³/s ↔ cfs, factor 35.3147).
* `validate_hecras.py` uses `ki_tools_common.metrics.all_metrics`
  (NSE/KGE/PBIAS/RMSE/r) for the computed-vs-observed WS comparison.

### Shared-library schema verification (done, recorded here)

```python
from ki_tools_common.metrics import all_metrics
all_metrics(obs, sim) -> {'NSE','KGE','PBIAS','RMSE','r'}   # all float
from ki_tools_common.units import convert
convert(1.0, 'm3/s', 'ft3/s')  # -> 35.3147  (used for Q unit conversion)
```

`load_daily_forcing` returns met variables (`precip_mm`, `temp_*`, `srad_wm2`,
`pres_pa`, `shum_kgkg`, `wind_*`) — **none** are HEC-RAS inputs, so the forcing
loader is intentionally NOT called by any HEC-RAS tool. This is documented so a
future maintainer does not "fix" the KI by wiring in precip.

## 4. Fixed-width / template notes

HEC-RAS text files are **keyword=value** and **comma-delimited**, NOT Fortran
fixed-width — so the APEX-style column-position trap does not apply to the
`.prj/.g/.f/.p` files. **However** the `.rNN` run file *is* a flattened
fixed-column Fortran dump (see the `Section - Flow Data` block: a right-justified
integer field for Q). Therefore every tool follows the **copy-first** rule:
copy a working template project, then replace specific values by string/line
substitution — never regenerate a `.rNN` or geometry from a Python dict.

## 5. Capability → tool trace (covers Phase 1b)

| Capability | Tool(s) |
|------------|---------|
| Steady WS-profile run (PRIMARY) | `run_hecras.py` |
| Prepare/parameterise a steady project | `prepare_steady_run.py` |
| Set discharges / profiles (incl. from ObservedQ) | `convert_flow_to_hecras.py` |
| Edit Manning n / exp-contr / station-elev | `edit_geometry.py` |
| Set upstream/downstream boundary conditions | `edit_boundaries.py` |
| Stage-discharge rating curve (flow sweep) | `rating_curve.py` |
| Geometry preprocessing (build geom HDF) | `preprocess_geometry.py` |
| Parse all hydraulic results from HDF | `parse_output_hecras.py` |
| Validate computed vs observed WS | `validate_hecras.py` |
| Unsteady / sediment / water-quality | documented in SKILL.md (solver present; needs Ras.exe orchestration) |
