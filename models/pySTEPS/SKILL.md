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
> Before starting, run: `python preflight_check.py` (in this KI directory)
> to verify that the model binary/package and required data are available.
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

<!-- KI-MAP:BEGIN (projected by generate_skill_map.py — edit the KI, not this table) -->
## KI map — what to read, and when

| when you need | read | why |
|---|---|---|
| FIRST, always | `preflight_check.py` | run it (`python preflight_check.py`): proves env/binary/data are usable and emits a machine-readable `PREFLIGHT_REPORT=` line. Do not debug a run that never had a healthy environment. |
| to run the pipeline stages | `tools/` (5 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (5 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (20 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (16 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/s1_data_import/import_radar_data.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s1_data_import/import_radar_data.py --help` |
| `tools/s2_motion_estimation/estimate_motion.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s2_motion_estimation/estimate_motion.py --help` |
| `tools/s3_nowcast/run_nowcast.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s3_nowcast/run_nowcast.py --help` |
| `tools/s4_verification/verify_nowcast.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s4_verification/verify_nowcast.py --help` |
| `tools/s5_postprocess/export_nowcast.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s5_postprocess/export_nowcast.py --help` |

*5 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

---
model: pySTEPS
version: 1.20.0
domain: precipitation_nowcasting
not_a_hydrological_model: true
---

# pySTEPS -- Knowledge Infrastructure

> **Version**: 1.20.0
> **Domain**: precipitation_nowcasting
> **Last updated**: 2026-08-18
> **Validation status**: binary_only

---

## 1. Model Identity

| Property | Value |
|----------|-------|
| Full name | pySTEPS |
| Version | 1.20.0 |
| Language | Python |
| License | See the installed pySTEPS package metadata |
| Repository | See the installed pySTEPS package metadata |
| Citation | See `docs/gathered_papers.json` and `docs/papers_index.md` |
| Primary domain | precipitation_nowcasting |
| Spatial mode | Distributed gridded radar precipitation fields |
| Install path | `KISSPATH_HOME/.local/lib/python3.12/site-packages/pysteps/` |
| Config file | `pystepsrc` in the install directory |

pySTEPS is a Python library, not a standalone binary. The package version is 1.20.0 via
`importlib.metadata`; the module itself has no `__version__` attribute.

It is NOT a hydrological model and cannot be validated directly against hydrocraft.db
station discharge or water-quality observations.

---

## 2. What This Model Does

pySTEPS performs deterministic and probabilistic precipitation nowcasting from radar QPE
sequences. It estimates atmospheric precipitation advection with optical-flow methods and
advects observed precipitation intensity fields forward on the same radar grid.

This KI treats pySTEPS as a physics/signal-processing library. The validated path exercises
the real pySTEPS code paths for Proesmans motion estimation, extrapolation nowcast, and
`det_cat_fct`/`fss` verification.

---

## 3. Input Requirements

Exact shapes live in `docs/format_spec.yaml`, projected from `dag.yaml` and
`diagnostics/triplets.yaml`. Regenerate that file after changing either source; do not
hand-edit it.

### 3.1 Radar Precipitation Sequence

| Variable | Unit model expects | Source dataset | Source unit | Conversion |
|----------|-------------------|----------------|-------------|------------|
| Precipitation intensity | mm/h | Radar QPE sequence | mm/h or radar-native unit | Keep mm/h when already converted; convert radar reflectivity before nowcasting |
| Radar reflectivity | dBZ | Radar product | dBZ | Convert to mm/h with the Marshall-Palmer relation before nowcasting |
| Log rainfall rate | dBR | Derived from precipitation intensity | mm/h | Apply pySTEPS log transform when a method requires log-domain rainfall |

Input is a sequence of 2-D precipitation intensity fields on a uniform radar grid,
typically 3-4 past frames at 5-15 min cadence. Supported importers include BoM RF3,
DWD HDF5, FMI PGM, KNMI HDF5, MCH GIF, OPERA HDF5, and SAF NetCDF.

### 3.2 Static Inputs

| Input | Source | Tool that prepares it |
|-------|--------|----------------------|
| Radar grid metadata | Radar importer metadata | `tools/` import and postprocess stages |
| Domain mask / NaN handling | Radar product metadata and stage docs | `docs/s1_data_import.md` |

### 3.3 Configuration Files

| File | Format | Notes |
|------|--------|-------|
| `pystepsrc` | pySTEPS configuration file | Lives in the pySTEPS install directory |
| `docs/format_spec.yaml` | YAML | Exact I/O contract projected from the KI |

---

## 4. Build Instructions

pySTEPS is used as the installed Python package in this environment. Before any run, verify
the package, data expectations, and KI structure:

```bash
cd KISSPATH_KI_ROOT/pySTEPS/knowledge_infrastructure
python3 preflight_check.py
```

Known build issues must be handled through `diagnostics/triplets.yaml` first, then the
official pySTEPS docs and working examples.

---

## 5. Execution

```bash
cd KISSPATH_KI_ROOT/pySTEPS/knowledge_infrastructure
python3 preflight_check.py
python3 diagnostics/run_synthetic_advection.py
```

The synthetic runner writes `diagnostics/last_run.json` with per-lead CSI/POD/FAR/FSS
scores plus timing. A `tester_result.json` is also written to the KI root for the
orchestrator.

Expected runtime is the local runtime of the synthetic analytical test on a 200x200 grid
with 4 past frames and 5 lead times.

---

## 6. Output Description

This section restates `dag.yaml`. If this section and `dag.yaml` disagree, `dag.yaml` wins.

**Headline output** (the dag's `validation_rank: 1` variable -- the one this model is
judged by):

> `motion_field` -- Estimated 2-D atmospheric radar precipitation advection velocity field (2, ny, nx) from the optical-flow stage on the radar precipitation frame sequence; an intermediate product also returnable on its own. (`pixels/timestep`)

| Output variable (dag `var`) | Rank | Unit | Description |
|-----------------------------|------|------|-------------|
| `motion_field` | 1 | pixels/timestep | Estimated 2-D atmospheric radar precipitation advection velocity field (2, ny, nx) from the optical-flow stage on the radar precipitation frame sequence; an intermediate product also returnable on its own. |
| `precipitation_intensity` | dag output | See `dag.yaml` | Listed by the dag as an output variable. |
| `exceedance_probability` | dag output | See `dag.yaml` | Listed by the dag as an output variable. |

---

## 7. Tool Inventory

| Tool | Purpose | Inputs | Outputs |
|------|---------|--------|---------|
| `preflight_check.py` | Verify environment, package, and required KI data | KI directory | Machine-readable `PREFLIGHT_REPORT=` line |
| `diagnostics/run_synthetic_advection.py` | Run the synthetic analytical validation path | Synthetic advected precipitation sequence | `diagnostics/last_run.json`, `tester_result.json`, stdout JSON |
| `tools/` | Executable pipeline stages | Radar frames, metadata, stage arguments | Model-ready inputs, motion fields, nowcasts, verification outputs |

### Stage Docs

- `docs/s1_data_import.md` - import radar frames, metadata, units, and NaN handling.
- `docs/s2_motion_estimation.md` - estimate pySTEPS optical-flow motion fields.
- `docs/s3_nowcast.md` - run extrapolation, STEPS, or ANVIL nowcasts.
- `docs/s4_verification.md` - score forecasts against held-out radar frames.
- `docs/s5_postprocess.md` - export nowcasts to NetCDF, GeoTIFF, or CSV.

Before composing a command, read each tool's argparse help and the corresponding stage doc.

---

## 8. Unit Conversion Table

pySTEPS operates on 2-D precipitation fields. This table documents the units and conversions
encountered in this KI pipeline.

| Variable | Source unit (verified) | Model unit | Factor / conversion | Type |
|----------|------------------------|------------|---------------------|------|
| `motion_field` | pixels/timestep | pixels/timestep | x1 | none |
| `precipitation_intensity` | mm/h | mm/h | x1 | none |
| `exceedance_probability` | dimensionless probability | dimensionless probability | x1 | none |
| Radar reflectivity | dBZ | mm/h | `R = (10**(dBZ/10) / 200)**(1/1.6)` | nonlinear |
| Log rainfall rate | mm/h | dBR | `dBR = 10 * log10(R)` with `R > 0` | logarithmic |
| Accumulated precipitation depth | mm/h | mm | `depth_mm = rate_mm_h * timestep_minutes / 60.0` | timestep integration |

### 8c. Sign Conventions and Output Units

| Variable | Convention in this model | Common alternative | Impact if wrong |
|----------|--------------------------|--------------------|-----------------|
| `motion_field` | 2-D advection velocity in pixels/timestep, shaped `(2, ny, nx)` | Physical velocity such as m/s | Advection displacement is scaled incorrectly |
| `precipitation_intensity` | Instantaneous or timestep-rate rainfall intensity in mm/h | Accumulated depth in mm | Accumulation and categorical thresholds are wrong |
| `exceedance_probability` | Dimensionless probability | Deterministic rainfall intensity | Probabilistic verification is invalid |

Primary units encountered:

| Unit | Description | Typical Range | Context |
|------|-------------|---------------|---------|
| **mm/h** | Rainfall intensity (linear) | 0 - 100 | Standard input/output unit for pySTEPS nowcast routines. Motion estimation and extrapolation operate in this space or its log transform. |
| **dBZ** | Radar reflectivity (logarithmic) | -10 to 60 | Raw radar measurement unit. Must be converted to mm/h before nowcasting via the Marshall-Palmer Z-R relation. |
| **dBR** | Log-transformed rainfall rate | -10 to 20 | Used internally by STEPS cascade decomposition for spectral analysis. |
| **mm** | Accumulated precipitation depth | 0 - 200+ | Obtained by integrating mm/h over time. Common accumulation periods: 5 min, 10 min, 15 min, 1 h, 6 h, 24 h. |

Critical unit conversion rules:

- dBZ to mm/h: `R = (10**(dBZ/10) / 200)**(1/1.6)` using the default `Z=200*R^1.6`.
- mm/h to dBR: `dBR = 10 * log10(R)`; set a threshold first because `R > 0` is required.
- mm/h to mm: `depth_mm = rate_mm_h * timestep_minutes / 60.0`.
- Radar frame timestep (`metadata['accutime']`) is in minutes. Common values are 5 for OPERA and BoM, 10 for FMI, and 15 for DWD.

Accumulation period pitfalls:

- A "5-minute rainfall rate" in mm/h means the average rate during a 5-min window, not 5 mm/h.
- To get 1-hour accumulation from 5-min frames, sum 12 consecutive frames in mm/h and multiply each by 5/60.
- STEPS ensemble output is instantaneous rate at each lead time, not accumulated between lead times.

---

## 9. Diagnostic Triplets (Top 5)

Check `diagnostics/triplets.yaml` before debugging any model crash, wrong output, or
unexpected values. The full corpus contains 20 entries; cite the real triplet ids from that
file in run notes instead of duplicating or renumbering them here.

| # | Error | Diagnosis | Remedy |
|---|-------|-----------|--------|
| 1 | `dt_pysteps_001`: unrealistic precipitation values or chaotic motion vectors | Input fields are dBZ but pySTEPS nowcast routines expect mm/h | Convert dBZ to mm/h before nowcasting |
| 2 | `dt_pysteps_002`: nowcast output values are near zero everywhere | Already-linear mm/h data was passed through an extra dB transform | Check `metadata['transform']` and remove the redundant transform |
| 3 | `dt_pysteps_003`: accumulated totals are 2-12x too high or too low | Radar frame timestep and assumed accumulation period differ | Multiply each rate frame by the timestep in hours from `metadata['accutime']` |
| 4 | `dt_pysteps_004`: importer raises file or parse errors for existing radar files | Wrong importer was selected for the radar file format | Identify source and format, then use the matching pySTEPS importer |
| 5 | `dt_pysteps_005`: HDF5 radar field is rotated, flipped, or transposed | Agency-specific HDF5 axis conventions differ | Verify orientation and flip or transpose data and metadata when needed |

---

## 10. Coupling Interfaces

| Upstream model | Variable exchanged | Unit | Temporal resolution |
|----------------|-------------------|------|---------------------|
| Radar QPE source | `precipitation_intensity` input frames | mm/h | 5-15 min cadence |

| Downstream model | Variable exchanged | Unit | Temporal resolution |
|------------------|-------------------|------|---------------------|
| Hydrologic or impact model | `precipitation_intensity` nowcast frames | mm/h or accumulated mm after conversion | Nowcast lead timestep |
| Warning/verification workflow | `exceedance_probability` | dimensionless probability | Nowcast lead timestep |

For real-data extension, see `examples/README.md`.

---

## 11. Validated Results

### Test Case: `synthetic_advection`

| Property | Value |
|----------|-------|
| Comparison type | `analytical` |
| Grid | 200x200 |
| Synthetic precipitation | Gaussian blob |
| Sigma | 18 |
| Peak intensity | 8 mm/h |
| Translation | `u=2`, `v=1` px/frame |
| Past frames | 4 |
| Lead times | 5 |
| Motion method | Proesmans |
| Nowcast method | extrapolation |
| Verification | Held-out truth frames |

Because no real radar archive is mounted, this KI validates pySTEPS against a synthetic
advected precipitation sequence where the true future frames are known exactly.

### Performance Metrics -- judged against the field's bar, not intuition

The convention bars below restate `docs/validation_convention.yaml`. A null convention band
is written as "no cited threshold"; no substitute threshold is implied.

| Dag variable | Metric | Direction | Satisfactory band | Good band | Very good band | Citation keys |
|--------------|--------|-----------|-------------------|-----------|----------------|---------------|
| `motion_field` | csi | maximize | no cited threshold | no cited threshold | no cited threshold | no cited threshold |
| `motion_field` | endpoint_error | minimize | no cited threshold | no cited threshold | no cited threshold | no cited threshold |
| `exceedance_probability` | roc_auc | maximize | 0.8 (`pulkkinen2019`, `foresti2016`) | 0.85 (`pulkkinen2019`, `foresti2016`) | 0.9 (`pulkkinen2019`, `foresti2016`) | `pulkkinen2019`, `foresti2016` |
| `exceedance_probability` | brier_skill_score | maximize | 0.0 (`foresti2016`, `flowerdew2014`) | no cited threshold | 1.0 (`foresti2016`, `flowerdew2014`) | `foresti2016`, `flowerdew2014` |

The synthetic runner reports CSI, POD, FAR at threshold 0.5 mm/h and FSS at scale 20 px.
Its synthetic-test expectations are mean CSI > 0.95 and mean FSS > 0.99; these are runner
checks, not convention pass-bands for `motion_field`.

### Data Replacement Tracking

| Component | Source | Status | Notes |
|-----------|--------|--------|-------|
| Radar forcing | Synthetic analytical sequence | Validated for the default KI test | Real radar archive is not mounted |
| Motion field | pySTEPS Proesmans optical flow | Validated by the synthetic runner | Rank-1 dag output is `motion_field` |
| Nowcast frames | pySTEPS extrapolation nowcast | Validated by the synthetic runner | Writes per-lead verification outputs |
| Verification | pySTEPS `det_cat_fct` and `fss` | Validated by the synthetic runner | Writes `diagnostics/last_run.json` |

---

## 12. Parameter Selection by Region

These are physically informed starting points for pySTEPS runs, not calibration against
hydrocraft.db discharge or water-quality observations.

### Motion Estimation Parameters

| Parameter | Default | Range | Description |
|-----------|---------|-------|-------------|
| `motion_method` | `'LK'` | `'LK'`, `'VET'`, `'proesmans'`, `'DARTS'` | Optical flow algorithm. Lucas-Kanade is robust for most cases; Proesmans is faster for uniform translation; VET and DARTS handle rotational or divergent flow. |
| `fd_method` (LK) | `'shitomasi'` | `'shitomasi'`, `'blob'`, `'tstorm'` | Feature detection method for Lucas-Kanade. |
| `maxCorners` (LK) | 500 | 100 - 5000 | Maximum features to track. |
| `qualityLevel` (LK) | 0.1 | 0.001 - 0.5 | Minimum feature quality. |
| `winSize` (LK) | `(50, 50)` | `(10,10)` - `(100,100)` | Lucas-Kanade window size in pixels. |
| `n_iter` (VET) | 3 | 1 - 10 | Number of VET optimization iterations. |

### Nowcast Parameters

| Parameter | Default | Range | Description |
|-----------|---------|-------|-------------|
| `n_leadtimes` | varies | 1 - 72 | Number of forecast time steps. At 5-min resolution, 12 is 1 hour, 36 is 3 hours, and 72 is 6 hours. |
| `n_ens_members` | 24 | 1 - 200 | Number of STEPS ensemble members. Minimum 20 for stable probability estimates; 48-100 for research; 1 means deterministic. |
| `n_cascade_levels` | 6 | 1 - 12 | Number of cascade decomposition levels. Should satisfy `2^n_levels <= min(nx, ny)`. |
| `noise_method` | `'nonparametric'` | `'nonparametric'`, `'parametric'`, `None` | Stochastic noise generation method for STEPS. |
| `ar_order` | 2 | 1 - 3 | Autoregressive model order for temporal evolution of cascade levels. |
| `extrap_method` | `'semilagrangian'` | `'semilagrangian'`, `'eulerian'` | Advection scheme. |
| `interp_order` | 1 | 1 - 3 | Interpolation order for semi-Lagrangian advection. |
| `n_iter` (extrap) | 1 | 1 - 5 | Sub-steps per advection step. |

### Verification Parameters

| Parameter | Description | Common Values |
|-----------|-------------|---------------|
| `thr` (`det_cat_fct`) | Rainfall threshold for categorical scores in mm/h | 0.1, 0.5, 1.0, 5.0, 10.0 |
| `scale` (`fss`) | Spatial scale for Fractions Skill Score in pixels | 1, 5, 10, 20, 50 |
| `scores` (`det_cat_fct`) | Categorical scores to compute | `['CSI', 'POD', 'FAR', 'HSS', 'ETS']` |

### Domain Size Guidelines

| Domain (pixels) | Recommended `n_cascade_levels` | Max `n_ens_members` with 16 GB RAM | Typical use case |
|-----------------|--------------------------------|------------------------------------|------------------|
| 128 x 128 | 4-6 | 200 | City-scale, single radar |
| 256 x 256 | 6-7 | 100 | Regional composite |
| 512 x 512 | 6-8 | 48 | National composite |
| 1024 x 1024 | 6-8 | 20 | Continental composite |
| 2048 x 2048 | 6-8 | 10 | Full OPERA European composite |
