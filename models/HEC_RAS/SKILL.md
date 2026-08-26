---
name: hec-ras
description: >-
  HEC-RAS Hydraulic Reference Manual v6.1/6.5 (1-D Saint-Venant + standard-step energy
  equation; 2-D shallow-water equations). Covers 1-D steady-flow water-surface profile
  computations in gradually varied open-channel flow…; 1-D unsteady-flow hydrodynamics via
  Saint-Venant equations (continuity + momentum, implicit…. Use when the task involves
  running, configuring, calibrating or interpreting HEC_RAS.
---

> **MANDATORY EXECUTION POLICY** — READ BEFORE PROCEEDING
>
> You MUST run the **actual model binary or package** described in this document.
> If the model fails to import, compile, or execute, you MUST:
> 1. Check `diagnostics/triplets.yaml` for a matching error pattern
> 2. Try the fix suggested in the triplet's `remedy` section
> 3. If still failing, report the error to the user with full details
>
> You MUST NOT substitute a simplified Python formula, regression equation,
> or hand-coded approximation in place of the real model. Doing so produces
> scientifically invalid results and defeats the purpose of the KI.
>
> Before starting, run: `python3 preflight_check.py` (in this KI directory)
> to verify that the model binary/package and required data are available.
> Use `python3` (/usr/bin) for the validated steady tools — h5py + ki_tools_common
> are on its path; NOT `python` (~/.local/bin lacks h5py). HOWEVER `ras_commander`
> 0.93.0 lives ONLY in the python_env venv site-packages, which is NOT on
> /usr/bin/python3's path. For ANY new-river / authoring step that imports
> `ras_commander` (§10/§11), invoke it with the venv interpreter
> `KISSPATH_PYTHON_ENV/bin/python3` (verified 2026-06-04: it
> imports h5py 3.15.1 + ras_commander 0.93.0 + ki_tools_common together).
>
> **DEBUGGING PROTOCOL** — When something goes wrong (model crashes, wrong output,
> unexpected values), follow this order. Do NOT skip steps or write debug scripts:
> 1. **Check triplets** — `diagnostics/triplets.yaml` may already cover this error
> 2. **Read official docs** — Check the model's own documentation (PDF manual, README,
>    official examples) for expected input formats, variable names, and units
> 3. **Find working examples** — Look in `outputs/` for previous successful runs of
>    this model, or check if the model ships with test/example data
> 4. **Fix the tool** — Now that you know what "correct" looks like, make targeted fixes
>
> Resist the urge to write diagnostic/debug Python scripts. The answers are almost
> always in the official docs and working examples, not in reverse-engineering the binary.

# HEC-RAS (Hydrologic Engineering Center — River Analysis System) — Knowledge Infrastructure

**Package**: `hydrocraft-hec-ras` v2.0.0
**Model**: HEC-RAS 6.7 Beta 5 (USACE Hydrologic Engineering Center) — **real Intel-Fortran solvers under WINE**
**Domain**: River / open-channel hydraulics (1-D & 2-D)
**Binary**: `KISSPATH_HOME/.wine/drive_c/Program Files (x86)/HEC/HEC-RAS/6.7 Beta 5/x64/RasSteady.exe`
**Last updated**: 2026-06-03
**Stats**: 10 tools | 6 docs | ≥15 diagnostic triplets
**Validation status**: `real` — computed vs **observed** water-surface elevations
on the *Mixed Flow Regime Channel* example: **NSE 0.9965, RMSE 0.096 ft,
KGE 0.977, PBIAS −0.09 %** (19 cross sections).

> ⚠️ **This KI was rebuilt 2026-06-03 to drive the ACTUAL HEC-RAS binary.** A
> prior version shipped a **GR4J rainfall-runoff Python surrogate** — that was
> both a KDT-philosophy violation (no real binary) **and** a domain error
> (HEC-RAS is a *hydraulics* model, not a rainfall-runoff model). The surrogate
> has been removed. Every tool here invokes `RasSteady.exe`.

---

## 1. What HEC-RAS is (and is NOT)

HEC-RAS computes **water-surface profiles and velocities** along a river,
given surveyed **cross-section geometry**, channel **roughness**, **discharge**,
and **boundary conditions**. It solves:

- **Steady flow** — standard-step solution of the 1-D energy (Bernoulli) equation
  for gradually-varied flow → WS / energy grade / velocity per cross section per profile.
- **Unsteady flow** — implicit finite-difference solution of the 1-D Saint-Venant
  equations (and 2-D shallow-water equations) → stage/flow hydrographs in time.
- **Add-ons** — bridge/culvert/gate hydraulics, sediment transport, water quality.

**HEC-RAS is NOT a rainfall-runoff model.** Its forcing is **discharge (cfs or
m³/s)** and **boundary stage** — *not* precipitation, temperature, or radiation.
Do **not** wire `load_daily_forcing` (precip/temp) into HEC-RAS. The Layer-1
tie-in is *discharge* via `ObservedQ` (see `convert_flow_to_hecras.py`).

---

## 2. Installation / environment

HEC-RAS is **proprietary, closed-source USACE Windows software**. There is no
buildable source. A pre-built install (6.7 Beta 5) is staged under **WINE 9.0**:

```
Install:  KISSPATH_HOME/.wine/drive_c/Program Files (x86)/HEC/HEC-RAS/6.7 Beta 5
Solvers:  x64/RasSteady.exe            (steady — VALIDATED here)
          x64/RasUnsteady.exe          (unsteady — loads; needs orchestration)
          x64/RasGeomPreprocess.exe    (geometry property tables)
          x64/RasUnsteadySediment.exe  (sediment)
          x64/RasWaterQuality.exe      (water quality)
          x64/RasQuasiSediment.exe / RasQuasiRVSM.exe
```

Invoke a solver under wine (the tools do this for you):

```bash
env -u LD_PRELOAD WINEPREFIX=KISSPATH_HOME/.wine WINEDEBUG=-all \
  wine ".../6.7 Beta 5/x64/RasSteady.exe" MIXED.r01
```

> **Two environment gotchas** (both handled in `tools/_hecras_env.py`):
> 1. A broken system-wide `LD_PRELOAD` (32-bit libstdc++) breaks wine — strip it (`env -u LD_PRELOAD`).
> 2. `RasSteady` aborts with `HDF_ERROR trying to open HDF output file` unless the
>    plan results skeleton `<prj>.pNN.tmp.hdf` exists — **seed it from `<prj>.gNN.hdf`**.

Python helpers used: `h5py` (read results), `numpy`, `matplotlib`,
`ki_tools_common` (metrics, units). `ras-commander` 0.93.0 is installed but its
project auto-detection does not recognise the "6.7 Beta 5" layout, so this KI
drives the solvers directly rather than through `RasCmdr.compute_plan`.

---

## 3. Execution architecture (why this works headless)

The Fortran solvers do **not** read the human-readable `.prj/.g/.f/.p` files.
The .NET orchestrator `Ras.exe` normally (a) flattens geometry+flow+plan into a
**run file** `.rNN`, and (b) creates the **plan results HDF** `.pNN.tmp.hdf`.
`Ras.exe` needs **Wine Mono**, which is **not installed** here.

**Verified work-around for steady runs** (this is what makes the KI real):

```
1. Start from a project that already has a .rNN run file (every shipped example does).
2. Seed results skeleton:   cp <prj>.gNN.hdf  <prj>.pNN.tmp.hdf
3. Run:  wine RasSteady.exe <prj>.rNN     (cwd = project dir)
4. Results land in <prj>.pNN.tmp.hdf -> /Results/Steady/Output/.../Cross Sections/
```

`run_hecras.py` does all four steps in a temp workspace and collects the output.
The trailing `HDF5-DIAG` lines printed *after* `Finished Steady Flow Simulation`
are **non-fatal** (the solver probes an optional group) — success is keyed on the
"Finished" banner and a populated (>60 kB) results HDF.

**Limitation (documented honestly):** brand-new geometry requires a `.rNN` run
file, which only `Ras.exe`/the GUI/`ras-commander` can write from scratch.
Unsteady/sediment/WQ solvers **load and execute** (proven) but their full run
needs the plan-HDF skeleton `Ras.exe` builds with boundary conditions baked in —
so they are documented but not end-to-end validated in this environment.

---

## 4. Capability inventory (Phase 1b) → tools

| # | Capability | Status | Tool(s) |
|---|------------|--------|---------|
| 1 | **Steady water-surface profiles** (PRIMARY) | ✅ validated | `run_hecras.py` |
| 2 | Prepare/parameterise a steady project | ✅ | `prepare_steady_run.py` |
| 2b | **Author NEW-river steady geometry from a DEM** (no Wine Mono) | ✅ NEW 2026-06-04 | `author_steady_geometry.py` |
| 3 | Set discharges/profiles (incl. from `ObservedQ`) | ✅ | `convert_flow_to_hecras.py` |
| 4 | Edit Manning n / expansion-contraction / geometry | ✅ | `edit_geometry.py` |
| 5 | Set up/downstream boundary conditions | ✅ | `edit_boundaries.py` |
| 6 | Stage-discharge **rating curve** (flow sweep) | ✅ | `rating_curve.py` |
| 7 | Geometry preprocessing (build geom HDF) | ⚠️ needs orchestration | `preprocess_geometry.py` |
| 8 | Parse all hydraulic results (WS/EG/Q/V/Froude/…) | ✅ | `parse_output_hecras.py` |
| 9 | **Validate** computed vs observed WS | ✅ | `validate_hecras.py` |
| 10 | Unsteady / sediment / water quality | ⚠️ solver loads; needs Wine Mono `Ras.exe` | documented (§7) |

---

## 5. Pipeline (typical steady workflow)

```bash
cd knowledge_infrastructure

# 0. environment check
python3 preflight_check.py

# 1. prepare a parameterised project from the template
python3 tools/prepare_steady_run.py --out-dir /tmp/myproj \
        --flows 600,1200 --dn-slope 0.0008

# 2. run the REAL steady solver
python3 tools/run_hecras.py --project /tmp/myproj --prj MIXED --plan 01 \
        --out /tmp/myproj_out

# 3. parse results to CSV/JSON
python3 tools/parse_output_hecras.py --hdf /tmp/myproj_out/MIXED.p01.tmp.hdf \
        --csv /tmp/myproj_out/results.csv

# 4. validate against observed WS (real-tier)
python3 tools/validate_hecras.py --hdf /tmp/myproj_out/MIXED.p01.tmp.hdf \
        --flow examples/MixedFlowSteady/MIXED.f01 --figure figures/s8_validation.png

# (optional) stage-discharge rating curve at cross section #9
python3 tools/rating_curve.py --xs-index 9 --flows 300,500,800,1200,2000 \
        --out /tmp/rating.csv
```

Every tool returns a JSON status with a `validation` block and exits non-zero on
failure (validate→process→validate contract).

---

## 6. Input / output reference

### Inputs (per project `<PRJ>`)

| File | Role | Edited by |
|------|------|-----------|
| `.prj` | project: title, **unit system**, current plan | template |
| `.gNN` | geometry: cross sections (Sta/Elev), Manning n, reach lengths, exp/contr | `edit_geometry.py` |
| `.gNN.hdf` | geometry hydraulic-property tables (HDF5) | `preprocess_geometry.py` (or ships with example) |
| `.fNN` | steady flow: profiles, **discharges**, boundary conditions, **Observed WS** | `convert_flow_to_hecras.py` |
| `.pNN` | plan: geom+flow refs, tolerances, **flow regime** | template |
| `.rNN` | **steady run file** the Fortran solver reads (flattened) | `convert_flow_to_hecras.py`, `edit_boundaries.py` |

### Outputs

| File | Role | Read by |
|------|------|---------|
| `.pNN.tmp.hdf` | results HDF: WS / EG / Q / V + 50+ hydraulic variables | `parse_output_hecras.py` |
| `.ONN` | legacy binary detailed output | (not parsed; HDF preferred) |

Key results HDF path:
`/Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Cross Sections/`
holds `Water Surface`, `Energy Grade`, `Flow` (shape `[n_profiles, n_xs]`) and an
`Additional Variables/` group with velocity, depth, top width, area, Froude, shear, etc.

### Unit trap table

| Quantity | English (default) | SI | Trap |
|----------|-------------------|-----|------|
| Discharge | **cfs** (ft³/s) | m³/s | `1 m³/s = 35.3147 cfs`. Feeding m³/s into an English project under-states flow ~35×. Use `--in-units m3/s` to auto-convert. |
| Elevation / WS | **ft** | m | `1 m = 3.28084 ft`. Geometry, observed WS, and computed WS must share units. |
| Velocity | ft/s | m/s | g = 32.174 ft/s² (English) vs 9.81 m/s² (SI) in the Froude calc. |
| Length / station | ft | m | reach lengths & cross-section stations follow the project unit system. |
| Slope | ft/ft (= m/m) | m/m | dimensionless — same in both systems; do NOT scale. |
| Manning n | dimensionless | dimensionless | same in both systems, but the conveyance formula carries a 1.486 (English) vs 1.0 (SI) factor *inside the solver* — never convert n between systems. |

The unit system is declared in the `.prj` (`English Units` / `SI Units`); changing
discharge units without changing the project unit system silently corrupts results.

---

## 7. Unsteady / sediment / water quality (documented, not validated here)

The unsteady, sediment, and water-quality solvers are present and **execute under
wine** (`RasUnsteady.exe` prints `Performing Unsteady Flow Simulation HEC-RAS 6.7
Beta 5`). Their full headless run is blocked because the plan results skeleton —
which `Ras.exe` writes with the boundary-condition time series baked in — cannot
be produced without **Wine Mono** (`~/.wine/drive_c/windows/mono` absent;
`dl.winehq.org` unreachable in this sandbox). To run them you must either install
Wine Mono and use `Ras.exe -c project.prj plan.pNN`, or run on a native Windows /
licensed HEC-RAS install. See `docs/06_capabilities.md` and triplets
`unsteady_needs_mono`, `wine_mono_missing`.

---

## 8. Validation summary

| Item | Value |
|------|-------|
| Benchmark | HEC-RAS *Mixed Flow Regime Channel* example (ships with HEC-RAS) |
| Reference | **Observed WS** lines in `MIXED.f01` (19 cross sections, PF1 @ Q=500 cfs) |
| Tier | **real** (independent observed water-surface elevations) |
| NSE | 0.9965 |
| KGE | 0.977 |
| RMSE | 0.096 ft |
| PBIAS | −0.09 % |
| r | 0.999 |
| max abs err | 0.28 ft |
| Figure | `figures/s8_validation.png` |

The computed profile correctly reproduces the supercritical→subcritical
transition (hydraulic jump) of the mixed-flow regime — Froude > 1 in the steep
upstream reach, < 1 downstream.

---

## 9. Tool reference

| Tool | Purpose | Key args |
|------|---------|----------|
| `prepare_steady_run.py` | copy template → set flows/boundaries/roughness | `--out-dir --flows --dn-slope --mann-scale` |
| `author_steady_geometry.py` | **NEW-river**: DEM+centerline → cross sections injected into a runnable `.rNN` (no Wine Mono) | `--dem --out-dir [--centerline-wkt] --half-width --flows-m3s/--observedq --dn-slope` |
| `convert_flow_to_hecras.py` | set discharges in the run file (Layer-1 / ObservedQ tie-in) | `--run --out --flows` or `--observedq --quantiles --in-units` |
| `edit_geometry.py` | scale/set Manning n; set exp/contr | `--geom --out --mann-scale --mann-set --exp --contr` |
| `edit_boundaries.py` | set normal-depth slopes (up/dn/all) in run file | `--run --out --dn-slope --up-slope --all-slope` |
| `preprocess_geometry.py` | run RasGeomPreprocess to build geom HDF | `--project --prj --plan` |
| `run_hecras.py` | **run the real RasSteady solver**; collect HDF | `--project --prj --plan --out` |
| `parse_output_hecras.py` | results HDF → per-XS records (CSV/JSON) | `--hdf --csv --json` |
| `rating_curve.py` | sweep discharges → stage-discharge curve | `--xs-index --flows --out` |
| `validate_hecras.py` | computed vs observed WS metrics + figure | `--hdf --flow --profile-index --figure` |
| `_hecras_env.py` | shared binary paths + wine/seed/run helpers | (imported) |

---

## 10. Data requirements & sources

> ✅ **NEW-RIVER STEADY NOW WORKS — no Wine Mono, no ras_commander (2026-06-04).**
> The repeated "structurally impossible without Wine Mono" verdict was a
> **FALSE NEGATIVE**. The steady Fortran solver reads cross-section
> station/elevation **directly from the `.rNN` run file** — the `.gNN.hdf` is only
> the results-skeleton seed. Proven by controlled experiment: bumping every bed
> elevation in `MIXED.r01` by +5 ft and re-running `RasSteady.exe` under plain
> wine raised the computed WS by exactly +5 ft (66.00..72.93 → 71.00..77.93).
> New geometry therefore needs only an **edited `.rNN`**, which is now authored by
> **`tools/author_steady_geometry.py`** (DEM + centerline →
> `ki_tools_common.terrain_ops.cut_cross_sections` → trapezoidal cross sections
> injected into the template `.rNN`, keeping 19 XS / 4 pts so the
> "Section - Arrays Sizes" header stays valid). **Demonstrated end-to-end on
> Bengbu** (`china_dem_90m`, 19 DEM cross sections, observed Q quantiles
> 3810/6812 m³/s → WS 69.33..81.22 ft, `RasSteady.exe` rc=0, real hydraulics in
> the results HDF). Limitation: this value-swap path inherits the template's
> longitudinal layout (reach lengths / river stations); fully general XS
> count/spacing additionally needs regenerating the array-size header (next
> `tool_build`). And steady **produces stage, consumes discharge** — a
> `discharge_m3s` validation target is the *forcing input*, not an output; for
> discharge-vs-discharge routing fidelity use unsteady (§11, still needs the
> plan-HDF skeleton — open question whether the unsteady solver is likewise
> `.rNN`/`.uNN`-authoritative).
>
> **(superseded note — ras_commander path) CORRECTION (2026-06-04, diagnosis retry):** the prior \"ras_commander not
> installed\" verdict was a FALSE NEGATIVE — it ran `import ras_commander` under
> `/usr/bin/python3`. `ras_commander` **0.93.0 IS installed** in the python_env
> venv and imports cleanly from
> `KISSPATH_PYTHON_ENV/bin/python3`, exposing the full
> authoring stack: `GeomCrossSection.set_station_elevation`, `GeomPreprocessor`,
> `RasGeo`, `RasCmdr.compute_plan_linux`, `HdfResultsXsec`. The ONLY remaining gap
> is that **no tool in `tools/` yet wraps these into a DEM→cross-section authoring +
> run pipeline** — a `tool_build` TODO, NOT a missing library. Author new-river
> steps with the venv interpreter (see §2). Verified-working scope today
> is **steady water-surface profiles on geometry that already ships a
> `.gNN.hdf` + `.rNN`** (the bundled MixedFlowSteady example, NSE 0.9965 §8).
>
> The intended (currently non-executable) workflow for a new basin would be:
>
> 1. **Start from a bundled template** (`RasExamples.extract_project('MixedFlowSteady')`
>    or any project that ships a `.gNN.hdf` + a `.pNN`).
> 2. **Replace cross-section geometry** using `RasGeo` / `GeomCrossSection` —
>    overwrite station-elevation tables with DEM-extracted cross sections
>    (MERIT-Hydro 3-arcsec tiles, river centerline from MERIT-Hydro `dir`).
> 3. **Set flow / boundary conditions** via `RasUnsteady` for unsteady routing
>    or `RasPlan` for steady. Upstream BC = observed discharge time series.
> 4. **Run via `RasCmdr.compute_plan()`** — this calls the Fortran solvers
>    (`HEC-RAS.exe`, `RasUnsteady.exe`) which work under **plain WINE without
>    Wine Mono** (verified Tier 3 v1, 2026-06-02). Do NOT invoke `Ras.exe`
>    (the .NET GUI) — that DOES need Wine Mono.
> 5. **Read modelled output** via `HdfResultsMesh` (cross-section results) or
>    `HdfPlot` — produces water-surface stage, modelled discharge at downstream
>    nodes, velocity profiles.
>
> What still requires Wine Mono (and is still blocked here): `Ras.exe -c`
> compute (the .NET command-line driver), RAS Mapper GIS exports, the GUI
> itself. Anything that goes through `HECRASController` COM.
>
> What still requires human engineering: choosing channel/overbank Manning n
> (use 0.035/0.06 default), picking cross-section spacing (Δx ≈ 50–500 m),
> calibrating against observed water-surface or downstream Q.
>
> ⚠️ **ORCHESTRATION TARGET VARIABLE.** HEC-RAS **consumes** discharge and
> **produces** water-surface stage. A verifier target of `Variable=discharge_m3s`
> is wrong for this domain — discharge is the *forcing input*, not an output.
> The comparison variable must be **water-surface stage** (the observed `z`
> column / observed-WS lines), as validated in §8.

- **Geometry** — surveyed cross sections (station, elevation) in the project unit
  system. The bundled template (`examples/MixedFlowSteady/`) is a prismatic
  trapezoidal reach; for a new river, geometry comes from survey or DEM-extracted
  cross sections (authored in the HEC-RAS GUI / `ras-commander`).
- **Discharge** — design floods or `ObservedQ` peaks. See
  `data_ki/ObservedQ/SKILL.md` for the observed-discharge dataset format;
  `convert_flow_to_hecras.py` can read it and convert m³/s → cfs.
- **Roughness** — Manning n from land cover / channel material (channel 0.025–0.05,
  overbank 0.04–0.15). Default 0.035 channel / 0.06 overbank if unknown.
- **Why this data?** HEC-RAS is a hydraulics model: it consumes discharge and
  geometry, *not* meteorology. The CMFD/MSWX/NASA-POWER met loaders in
  `ki_tools_common` are therefore intentionally **not** used here.

See `docs/` for stage-by-stage procedures and `diagnostics/triplets.yaml` for the
error→remedy catalogue (HDF seeding, LD_PRELOAD, unit traps, Wine Mono, etc.).

---

## 11. Routing-test recipe (Wangjiaba → Bengbu, Huai River)

> ⚠️ **STEADY new-river now works (§10); this §11 UNSTEADY Q→Q routing recipe is
> still blocked.** For a steady water-surface profile on a new reach use
> `tools/author_steady_geometry.py` (no Wine Mono). The unsteady routing below
> needs the plan-HDF skeleton with boundary time series baked in — open question
> whether the unsteady solver is likewise flat-file (`.uNN`/`.rNN`) authoritative
> the way the steady solver proved to be.
>
> ⚠️ **PARTIALLY EXECUTABLE — library present, wrapper missing (corrected
> 2026-06-04).** This recipe depends on `ras_commander` (`RasExamples`, `RasGeo`,
> `GeomCrossSection`, `RasUnsteady`, `RasCmdr.compute_plan_linux`) and a
> DEM→cross-section authoring step. `ras_commander` 0.93.0 **IS installed** — import
> it via `KISSPATH_PYTHON_ENV/bin/python3`; the only missing
> piece is a `tools/` wrapper that authors geometry from a DEM. Every Bengbu run to date has therefore been
> **structurally blocked at the authoring stage** — the Bengbu Q/stage metrics
> are *uncomputable*, not poor. The recipe is kept as the design target for when
> those dependencies are added. Until then HEC-RAS validates only on geometry
> that already ships a `.gNN.hdf` + `.rNN` (dev example, §8).

This is the orchestrator's primary real-case validation for HEC-RAS. It tests
**hydrodynamic routing fidelity** (attenuation + lag) on a real river reach,
which is the natural validation for HEC-RAS (the model consumes upstream Q and
routes it downstream — it does not produce Q de novo).

**Reach.** Huai River, China. Upstream gage **Wangjiaba** (id `wangjiaba_51030`,
32.43 N, 115.60 E, `KISSPATH_OBS/WJB/HUAIH-51030-wangjiaba.txt`)
→ downstream gage **Bengbu** (id `bengbu_51080`, 32.93 N, 117.38 E,
`KISSPATH_OBS/BB/51080_bengbu.txt`). ~200 km reach.
Both files share period 1952-05-30 to 1997-12-31, daily resolution, columns
include `discharge_m3s` and `water_level_m`.

**Pattern.**
1. **Authoring (ras-commander HDF-direct, no Wine Mono).**
   - Start from a bundled template via `RasExamples.extract_project('MixedFlowSteady')`
     (or any project shipping `.gNN.hdf` + a plan file).
   - Use `RasGeo` / `GeomCrossSection` to overwrite station-elevation tables
     with cross sections sampled from MERIT-Hydro DEM (`KISSPATH_DATA/MERIT_Hydro/`,
     3-arcsec tiles) along the Wangjiaba→Bengbu centerline. Δx ≈ 200-500 m.
   - Use `RasUnsteady` to set:
     * Upstream BC = Wangjiaba `discharge_m3s` time series (read with
       `read_obs_q.py` or `data_ki/ObservedQ/SKILL.md` recipe).
     * Downstream BC = normal-depth (friction slope) or stage-Q rating.
     * Plan title, time window matching the obs overlap.
2. **Run (plain WINE, no Mono).** `RasCmdr.compute_plan(prj, plan_id, num_cores=4)`
   invokes the Fortran solvers (`HEC-RAS.exe`, `RasUnsteady.exe`) under WINE.
3. **Extract modelled Q at Bengbu.** `HdfResultsMesh` (or `parse_output_hecras.py`
   for 1D unsteady) — pull discharge time series at the cross-section nearest
   Bengbu (32.93 N, 117.38 E).
4. **Compare** modelled Bengbu Q vs observed Bengbu Q over a common 1–3 year
   window (NSE, KGE, r, PBIAS, peak-lag). Use the standard validators.

**Why this is the right test.** HEC-RAS is a 1D/2D hydrodynamic solver — its
job is to take Q at an upstream boundary and route it downstream with proper
wave attenuation and lag. Comparing modelled-discharge-at-a-different-station
to observed-discharge-at-that-station directly measures routing fidelity. (A
stage-vs-stage test is the other valid choice; see §10 ⚠️ note. We use Q-vs-Q
here because both gages have long contiguous daily Q records.)

**Pitfalls.** (a) Make sure the unsteady time step Δt is small enough for the
Courant condition along the reach (`Δt ≤ Δx / c` with `c ≈ √(g h)`). (b) The
~200 km reach has tributaries; for a first cut, ignore them — the model will
under-predict peaks. To add lateral inflow, use `RasUnsteady` flow-distributions
on internal cross sections. (c) Normal-depth downstream BC induces an error
band near the downstream end; place the Bengbu extraction cross section ≥ 5 km
upstream of the downstream BC to avoid it.
