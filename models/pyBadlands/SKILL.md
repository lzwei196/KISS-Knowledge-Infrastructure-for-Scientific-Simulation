> **MANDATORY EXECUTION POLICY** — READ BEFORE PROCEEDING
>
> You MUST run the **actual model binary or package** described in this document.
> If the model fails to import, compile, or execute, you MUST:
> 1. Check `diagnostics/triplets.yaml` for a matching error pattern
> 2. Try the fix suggested in the triplet's `remedy` section
> 3. If still failing, report the error to the user with full details
>
> You MUST NOT substitute a simplified Python formula, regression equation,
> or hand-coded approximation in place of the real model.
>
>
> Before starting, run: `python preflight_check.py` (in this KI directory)
> to verify that the model binary/package and required data are available.
>
> **DEBUGGING PROTOCOL** — When something goes wrong, follow this order:
> 1. **Check triplets** — `diagnostics/triplets.yaml` may already cover this error
> 2. **Read official docs** — The model's own documentation for expected formats/units
> 3. **Find working examples** — Check `outputs/` or the model's shipped test data
> 4. **Fix the tool** — With knowledge of what "correct" looks like
>
> Do NOT write custom debug scripts. The answers are in the docs and examples.

# pyBadlands — Knowledge Infrastructure

**Package**: `hydrocraft-badlands-geomorph` v1.0.0
**Model**: pyBadlands (Basin and Landscape Dynamics) — Tristan Salles, University of Sydney
**Domain**: Geomorphology / Landscape Evolution Modelling
**License**: GNU LGPL v3
**Language**: Python + Fortran + C extensions
**Build**: Meson + mesonpy

**Stats**: 7 pipeline stages | 4 tools | 116 source files | 20+ diagnostic triplets

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for meteorological forcing documentation.
See `data_ki/USGS_Sediment/SKILL.md` for suspended sediment observations.


## Overview

pyBadlands is a long-term landscape evolution model that simulates the interplay of
tectonic processes, climate forcing, sea-level changes, and sediment transport over
geological time scales (10³–10⁸ years). It operates on an irregular Triangulated
Irregular Network (TIN) mesh derived from a DEM, and solves:

- **Fluvial incision** via Stream Power Law (SPL): E = K · A^m · S^n
- **Hillslope diffusion** (linear and non-linear creep)
- **Wave-driven sediment transport** (Airy wave theory or SWAN coupling)
- **Flexural isostasy** (via gFlex library)
- **Carbonate/reef growth** (fuzzy-logic depth/sediment/wave controls)
- **Orographic rainfall** (elevation-dependent precipitation model)
- **Tectonic displacement** (uplift/subsidence + horizontal displacement maps)

The model reads an **XML configuration file** and a **DEM raster**, then outputs
**HDF5** + **XDMF** time series at user-specified intervals.

**Key References**:
- Salles & Hardiman, 2016, Computers & Geosciences, 91, 1-11
- Salles, 2016, PLoS ONE, 11(4), e0154295
- Braun & Willett, 2013, Geomorphology, 170-179

---

## Installation

### Binary Build (Meson)

```bash
cd source/repo/badlands
python -m venv /path/to/venv
source /path/to/venv/bin/activate
pip install numpy scipy h5py pandas matplotlib scikit-image six gflex triangle
pip install meson-python meson ninja
pip install --no-build-isolation -e .
```

### Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| numpy | < 2 | Array computation |
| scipy | >= 1.2 | Interpolation, spatial |
| h5py | >= 2.8 | HDF5 I/O |
| pandas | >= 0.24 | Data manipulation |
| matplotlib | >= 3.0 | Visualization |
| scikit-image | >= 0.15 | Image processing |
| triangle | any | Delaunay triangulation |
| meshplex | git | Mesh processing |
| gFlex | >= 1.1 | Flexural isostasy |
| six | >= 1.11 | Python 2/3 compat |

### Fortran/C Extensions Built by Meson

| Extension | Source | Function |
|-----------|--------|----------|
| flowalgo | flowalgo.f90 | Flow network routing algorithms |
| fvframe | classfv.f90 | Finite volume discretization |
| pdalgo | pdalgo.f90 | Pit detection and filling |
| ormodel | classoro.f90 | Orographic rainfall model |
| waveseds | waveseds.f90 | Wave-sediment transport |
| sfd | sfd.c | Single-flow-direction algorithm |

### Quick Test

```python
from badlands.model import Model
model = Model()
model.load_xml("input.xml", verbose=True)
model.run_to_time(1000000)  # Run 1 Myr
```

---

## Pipeline Stages

| Stage | Name | Tools | Description |
|-------|------|-------|-------------|
| s0 | Configuration | — | Set up project directory, select DEM, define time span |
| s1 | Domain Setup | — | Prepare DEM raster, define boundary conditions, resolution |
| s2 | DEM Preparation | convert_dem | Reproject/resample DEM, verify units (metres) |
| s3 | Forcing Preparation | convert_forcing | Create rainfall maps, sea-level curves, tectonic displacement maps |
| s4 | Parameter Setup | convert_params | Set SPL coefficients, diffusion rates, erodibility layers |
| s5 | Execution | run_badlands | Execute model, monitor time stepping |
| s6 | Output Analysis | parse_output | Extract HDF5 results to CSV, compute erosion/deposition budgets |

---

## Tools Reference

| Tool | Stage | Script | Lines | Purpose |
|------|-------|--------|-------|---------|
| convert_forcing | s3 | `tools/s3_forcing/convert_forcing_to_badlands.py` | ~200 | Convert climate/tectonic data → badlands format |
| convert_params | s4 | `tools/s4_parameters/convert_soil_params.py` | ~150 | Convert soil/rock parameters → erodibility layers |
| run_badlands | s5 | `tools/s5_run/run_badlands.py` | ~140 | Execute model with XML config |
| parse_output | s6 | `tools/s6_output/parse_badlands_output.py` | ~180 | Extract HDF5 → CSV with erosion/deposition budgets |

---

## Critical Domain Knowledge

### 1. [dt_001] Rainfall units: m/year, NOT mm/year

pyBadlands expects precipitation in **metres per year**. Global datasets (CMFD, ERA5,
CRU) typically provide mm/day or mm/month. A missing conversion produces a 1000×
over-estimate of runoff, causing catastrophic erosion in the first time step.

**Detection**: Check max `rval` in XML — should be 0.1–5.0 m/year for most climates.
**Remedy**: `rain_m_per_year = rain_mm_per_day * 365.25 / 1000`

### 2. [dt_002] Sediment load (rQs) in Mt/year, internally converted to m³/year

River source sediment loads (`rQs`) are specified in **megatonnes per year** in the XML.
The code internally converts: `qs_kg = rQs * 1.0e9` then `qs_m3 = qs_kg / rhoS`.
If you supply values already in kg/year, you get a 10⁹× error.

**Detection**: Typical river Qs is 0.001–100 Mt/year. Values > 1000 are suspect.
**Remedy**: Verify units before entry; use Mt/year as stated in XML schema.

### 3. [dt_003] DEM elevation must be in metres

The DEM raster must have elevation values in **metres**. Some datasets use cm or mm.
The model does no unit detection — wrong units silently produce wrong erosion rates.

**Detection**: Check DEM z-range. Typical landscapes: -500 to +8000 m.
**Remedy**: Convert before ingestion: `z_m = z_cm / 100`

### 4. [dt_004] Sea-level curve: time in years, elevation in metres

The sea-level curve file (2 columns) uses **years** for time and **metres** for elevation.
If time is in ka (kiloyears), all sea-level changes happen 1000× too fast.

**Detection**: First column should span the simulation time range (e.g., -1e6 to 0).
**Remedy**: `time_years = time_ka * 1000`

### 5. [dt_005] Displacement maps: cumulative vs. rate

Tectonic displacement maps specify **total displacement** over the event duration, NOT
a rate. If you provide a rate map (m/year), the model will under-displace by a factor
equal to the event duration.

**Detection**: Compare max displacement to expected total uplift (e.g., 1000 m over 10 Myr).
**Remedy**: `disp_total_m = rate_m_per_year * duration_years`

### 6. [dt_006] SPL erodibility coefficient (Kd) is dimensionally complex

The stream power erodibility `SPLero` has units of m^(1−2m)/year. This is NOT a simple
rate. When m=0.5, units are dimensionless/year. When m≠0.5, the coefficient must be
adjusted. Literature values assume specific m,n combinations.

**Detection**: Typical Kd for bedrock: 1e-8 to 1e-5. For alluvial: 1e-5 to 1e-3.
**Remedy**: Always cite the m,n values alongside Kd from literature.

### 7. [dt_007] Diffusion coefficient units: m²/year

Hillslope diffusion coefficients (`caerial`, `cmarine`) are in **m²/year**. Literature
often reports in m²/kyr. A 1000× error produces unrealistic hillslope smoothing.

**Detection**: Typical aerial: 0.001–1.0 m²/year. If > 10, suspect kyr→year error.
**Remedy**: `kappa_m2_per_year = kappa_m2_per_kyr / 1000`

### 8. [dt_008] Boundary type must match domain geometry

Setting `boundary=fixed` on a DEM that doesn't have a natural outlet causes water
to pool indefinitely. Setting `boundary=slope` on a flat DEM produces no flow.

**Detection**: Inspect DEM edges — does an outlet exist? Is the boundary flat?
**Remedy**: Use `outlet` for single-outlet basins; `slope` for continuous landscapes.

### 9. [dt_009] Output folder must exist before run

The XML `outfolder` path is NOT created automatically in all versions. A missing
directory causes a silent crash when writing the first HDF5 output.

**Detection**: Check for error at first output step.
**Remedy**: `mkdir -p <outfolder>` before running.

---

## Input File Specification

### XML Configuration Structure

**CRITICAL**: The actual XML tag names differ from some online documentation.
The erosion section uses `<sp_law>` (not `<erosion>`), with child tags `<m>`, `<n>`,
`<erodibility>` (not `<SPLm>`, `<SPLn>`, `<SPLero>`). Displacement files must be
single-column (z-values only, no x,y coordinates), with no header row.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<badlands xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">

    <!-- Grid definition -->
    <grid>
        <demfile>dem.csv</demfile>
        <boundary>slope</boundary>
        <resfactor>1</resfactor>
    </grid>

    <!-- Time control -->
    <time>
        <start>0</start>
        <end>1000000</end>
        <display>10000</display>
        <mindt>1.0</mindt>
        <maxdt>100000</maxdt>
    </time>

    <!-- Precipitation -->
    <precipitation>
        <climates>1</climates>
        <rain>
            <rstart>0</rstart>
            <rend>1000000</rend>
            <rval>1.0</rval>    <!-- m/year -->
        </rain>
    </precipitation>

    <!-- Stream power erosion: tag is sp_law, NOT erosion -->
    <sp_law>
        <m>0.5</m>                      <!-- discharge exponent -->
        <n>1.0</n>                      <!-- slope exponent -->
        <erodibility>1.0e-6</erodibility> <!-- Kd coefficient -->
    </sp_law>

    <!-- Hillslope diffusion -->
    <creep>
        <caerial>0.02</caerial>
        <cmarine>0.05</cmarine>
    </creep>

    <!-- Output -->
    <outfolder>output</outfolder>
</badlands>
```

### Complete Parameter Table

| XML Path | Parameter | Units | Default | Range | Description |
|----------|-----------|-------|---------|-------|-------------|
| grid/demfile | DEM path | — | required | — | Path to elevation raster |
| grid/boundary | boundary type | — | slope | slope,flat,wall,fixed,outlet | Edge boundary condition |
| grid/resfactor | resolution factor | — | 1 | 1–10 | DEM sub-sampling factor |
| time/start | start time | years | required | — | Simulation start |
| time/end | end time | years | required | — | Simulation end |
| time/display | output interval | years | required | — | Output frequency |
| time/mindt | min timestep | years | 1.0 | 0.1–1e3 | Minimum adaptive dt |
| time/maxdt | max timestep | years | 1e6 | mindt–1e8 | Maximum adaptive dt |
| precipitation/rain/rval | rainfall rate | m/year | 0.0 | 0–10 | Uniform rainfall |
| precipitation/rain/map | rainfall map | — | — | — | Spatial rainfall raster |
| erosion/SPLm | discharge exponent | — | 0.5 | 0.3–0.7 | Stream power m |
| erosion/SPLn | slope exponent | — | 1.0 | 0.7–2.0 | Stream power n |
| erosion/SPLero | erodibility | m^(1-2m)/yr | 0.0 | 1e-8–1e-3 | SPL Kd coefficient |
| creep/caerial | aerial diffusion | m²/year | 0.0 | 0.001–1.0 | Subaerial hillslope κ |
| creep/cmarine | marine diffusion | m²/year | 0.0 | 0.001–5.0 | Submarine hillslope κ |
| creep/cslp | critical slope | — | 0.0 | 0–1 | Non-linear threshold Sc |
| creep/sfail | failure slope | — | 0.0 | 0–1 | Mass failure threshold |
| creep/cfail | failure coeff | m²/year | 0.0 | 0–10 | Failure diffusion rate |
| sea/position | sea level | m | 0.0 | — | Fixed sea-level elevation |
| sea/curve | sea-level file | — | — | — | Time-varying sea level |
| tectonic/disp/dstart | start time | years | — | — | Displacement event start |
| tectonic/disp/dend | end time | years | — | — | Displacement event end |
| tectonic/disp/dfile | horiz. disp. | — | — | — | Horizontal displacement map |
| tectonic/disp/ufile | vert. disp. | — | — | — | Vertical (uplift) displacement map |
| rivers/river/rQw | discharge | m³/s | — | 0.01–1e5 | River mean annual discharge |
| rivers/river/rQs | sediment load | Mt/year | — | 0.001–100 | River sediment load |
| rivers/river/rhoS | sed. density | kg/m³ | 2650 | 1500–3000 | Sediment grain density |
| flexure/dmantle | mantle density | kg/m³ | 3300 | 3100–3500 | Mantle density |
| flexure/dsediment | sed. density | kg/m³ | 2500 | 2000–2700 | Bulk sediment density |
| flexure/youngMod | Young's modulus | Pa | 6.5e10 | 1e10–1e11 | Elastic modulus |
| flexure/elasticH | elastic thickness | m | — | 5e3–100e3 | Lithospheric thickness |
| waveglobal/wbase | wave base | m | 20 | 5–200 | Depth of wave influence |
| waveglobal/d50 | grain D50 | m | 1e-4 | 1e-6–1e-2 | Median grain diameter |
| carb/species1/growth_sp1 | growth rate | m/year | 0.0 | 0–0.01 | Carbonate growth rate |

---

## Output Format

### Directory Structure
```
output/
├── h5/
│   ├── tin.time0.hdf5     # TIN mesh + elevation
│   ├── tin.time1.hdf5
│   ├── flow.time0.hdf5    # Flow network + discharge
│   ├── flow.time1.hdf5
│   └── sed.time0.hdf5     # Sediment layers
├── xmf/
│   ├── tin.time0.xmf      # XDMF visualization metadata
│   └── flow.time0.xmf
├── tin.series.xdmf         # Time series descriptor
└── flow.series.xdmf
```

### Key Output Variables (HDF5)

| Variable | Units | Description |
|----------|-------|-------------|
| elevation | m | Current topographic elevation |
| cumdiff | m | Cumulative erosion (−) / deposition (+) |
| cumhill | m | Cumulative hillslope diffusion change |
| cumfail | m | Cumulative slope-failure change |
| cumflex | m | Cumulative flexural isostasy change |
| discharge | m³/year | Water discharge at each node |
| slopeTIN | — | Local slope gradient |
| rain | m/year | Local rainfall rate |

---

## Calibration Parameters (Priority Order)

| Priority | Parameter | Typical Range | Sensitivity | Notes |
|----------|-----------|--------------|-------------|-------|
| 1 | SPLero (Kd) | 1e-8 – 1e-4 | VERY HIGH | Controls denudation rate |
| 2 | rainfall (rval) | 0.1 – 5.0 m/yr | HIGH | Drives discharge |
| 3 | SPLm | 0.3 – 0.7 | HIGH | Discharge–erosion scaling |
| 4 | SPLn | 0.7 – 2.0 | HIGH | Slope–erosion scaling |
| 5 | caerial | 0.001 – 1.0 m²/yr | MEDIUM | Hillslope smoothing |
| 6 | cmarine | 0.001 – 5.0 m²/yr | MEDIUM | Submarine smoothing |
| 7 | maxdt | 1e3 – 1e6 yr | LOW | Timestep control |

---

## Unit Trap Table

| Parameter | Model Units | Common Dataset Units | Conversion | Trap ID |
|-----------|-------------|---------------------|------------|---------|
| Rainfall (rval) | m/year | mm/day | × 365.25 / 1000 | dt_001 |
| Sediment load (rQs) | Mt/year | kg/year | ÷ 1e9 | dt_002 |
| DEM elevation | m | cm, mm, ft | ÷ 100, ÷ 1000, × 0.3048 | dt_003 |
| Sea-level time | years | ka, Ma | × 1e3, × 1e6 | dt_004 |
| Tectonic displacement | m (total) | m/year (rate) | × duration_years | dt_005 |
| Erodibility (Kd) | m^(1-2m)/yr | varies | dimension-check m,n | dt_006 |
| Diffusion coeff | m²/year | m²/kyr | ÷ 1000 | dt_007 |
| Grain size D50 | m | mm, μm | ÷ 1000, ÷ 1e6 | dt_010 |
| Discharge (rQw) | m³/s | L/s | ÷ 1000 | dt_011 |
| Wave height | m | cm | ÷ 100 | dt_014 |
| Elastic thickness | m | km | × 1000 | dt_015 |

---

## Diagnostic Triplets Summary

| ID | Severity | Domain | Symptom |
|----|----------|--------|---------|
| dt_001 | silent | unit_conversion | 1000× rainfall over-estimate |
| dt_002 | silent | unit_conversion | 10⁹× sediment load error |
| dt_003 | silent | unit_conversion | Wrong DEM elevation units |
| dt_004 | silent | unit_conversion | Sea-level time in ka not years |
| dt_005 | silent | unit_conversion | Displacement rate vs. total |
| dt_006 | degraded | parameter_format | Kd units mismatch with m,n |
| dt_007 | silent | unit_conversion | Diffusion in kyr not year |
| dt_008 | fatal | parameter_format | Boundary type vs DEM mismatch |
| dt_009 | fatal | path_resolution | Output folder does not exist |
| dt_010 | silent | unit_conversion | Grain size in mm not m |
| dt_011 | silent | unit_conversion | Discharge in L/s not m³/s |
| dt_012 | fatal | runtime | NaN in elevation array |
| dt_013 | degraded | parameter_format | resfactor too large for DEM |
| dt_014 | silent | unit_conversion | Wave height in cm not m |
| dt_015 | silent | unit_conversion | Elastic thickness in km not m |
| dt_016 | fatal | runtime | Timestep too large → instability |
| dt_017 | degraded | silent_error | No precipitation defined |
| dt_018 | fatal | dependency_mismatch | numpy >= 2 incompatible |
| dt_019 | degraded | parameter_format | Carbonate depth curve non-monotonic |
| dt_020 | silent | silent_error | Porosity params ignored when 0 |

---

## Quick Start Examples

### 1. Minimal landscape evolution (uniform rainfall, no tectonics)
```python
from badlands.model import Model
m = Model()
m.load_xml("examples/simple/input.xml")
m.run_to_time(1000000)
```

### 2. With tectonic uplift
```python
m = Model()
m.load_xml("examples/uplift/input.xml")
m.run_to_time(5000000)
```

### 3. Extract final elevation
```python
import h5py
f = h5py.File("output/h5/tin.time10.hdf5", "r")
coords = f["coords"][:]  # (N, 3) array: x, y, z
elev = coords[:, 2]
cumdiff = f["cumdiff"][:]
```

### 4. Restart from checkpoint
```xml
<time>
    <restart>
        <rfolder>output</rfolder>
        <rstep>5</rstep>
    </restart>
</time>
```

---

## File Structure

```
ki/
├── SKILL.md                                    ← this file
├── knowledge_infrastructure.yaml               ← schema
├── tools/
│   ├── s3_forcing/
│   │   └── convert_forcing_to_badlands.py      ← climate/tectonic data converter
│   ├── s4_parameters/
│   │   └── convert_soil_params.py              ← rock/soil → erodibility converter
│   ├── s5_run/
│   │   └── run_badlands.py                     ← execution wrapper
│   └── s6_output/
│       └── parse_badlands_output.py            ← HDF5 → CSV extractor
├── docs/
│   ├── s1_domain_setup.md                      ← domain & DEM skill
│   ├── s2_dem_preparation.md                   ← DEM processing skill
│   ├── s3_forcing_preparation.md               ← forcing data skill
│   ├── s4_parameter_calibration.md             ← parameter tuning skill
│   ├── s5_execution.md                         ← model execution skill
│   └── s6_output_analysis.md                   ← output interpretation skill
├── diagnostics/
│   └── triplets.yaml                           ← symptom→diagnosis→remedy
└── workflow/
    └── workflow.md                             ← pipeline DAG
```
