# DuMux — Workflow (KDT-validated 2026-04-30)

Validated across 6 real-case runs spanning 3 continents and 4 aquifer types.
See `diagnostics/triplets.yaml` for failure modes; see SKILL.md for validation metrics.

---

## Pipeline Stages

### Stage 0: Configuration + Domain Selection (`s0_config`)

**Critical — check all conditions before proceeding.**

Run the 5-condition pre-check on candidate well observations:
```python
wtd = alt_w - p_obs             # water table depth (positive=below ground)
# Condition 1: no artesian wells
assert wtd.min() >= 0, "Artesian wells present — not suitable for 1p model (dt_019)"
# Condition 2: flat terrain
assert alt_w.max() - alt_w.min() < 100, "Terrain too variable — split domain (dt_020)"
# Condition 3: dominant gradient direction
r_ew = np.corrcoef(lons_w, p_obs)[0,1]
r_ns = np.corrcoef(lats_w, p_obs)[0,1]
assert max(abs(r_ew), abs(r_ns)) > 0.3, "No clear gradient — unsuitable aquifer (dt_020)"
# Condition 4: pick flow direction
FlowDir = 0 if abs(r_ew) > abs(r_ns) else 2   # 0=E-W, 2=N-S
# Condition 5: enough interior wells
# (≥10 after excluding boundary wells)
```

**Aquifer type compatibility:**
| Aquifer type | Suitable for 1p uniform-K? | Alternative |
|---|---|---|
| Flat unconfined alluvial plain (High Plains, Ogallala) | ✓ Best | — |
| Flat coastal alluvial (Veneto flat subset) | Partial (NSE~0.26) | Add heterogeneous K |
| Artesian/confined basin (Po Plain, NCP deep) | ✗ Fan WTD fails | Use GRACE TWS budget |
| Mountain-adjacent domain (NCP edge, Alpine) | ✗ Terrain contamination | Restrict to flat cells |
| Complex multi-layer (Garonne/France) | ✗ Topography dominates | Needs variable K |

---

### Stage 1: Domain Setup (`s1_domain`)

1. Set domain bounds with 0.2–0.3° buffer around well cluster
2. Check SRTM tile availability (`ls /mnt/disk4/SRTMGL1/N{lat}E{lon}.SRTMGL1.hgt.zip`)
3. Build SRTM mosaic → resample to 50×50 grid
4. Check: `np.nanmin(elev_g)` should be > −10m for flat plain

**BC extraction (preferred: from observed well data):**
```python
lon_range = LON_MAX - LON_MIN
if FlowDir == 0:  # E-W
    h_left  = np.mean(p_obs[lons_w < LON_MIN + lon_range*0.25])
    h_right = np.mean(p_obs[lons_w > LON_MAX - lon_range*0.25])
elif FlowDir == 2:  # N-S
    lat_range = LAT_MAX - LAT_MIN
    h_south = np.mean(p_obs[lats_w < LAT_MIN + lat_range*0.25])  # PressureLeft
    h_north = np.mean(p_obs[lats_w > LAT_MAX - lat_range*0.25])  # PressureRight
# Convert: p = 101325 + 1000*9.81*h_m
```

**Gradient sanity check:** `|h_left − h_right| / DX_km` should be 0.05–2.0 m/km.
If < 0.05 m/km: gradient too flat → model will be unresponsive to K.
If > 2.0 m/km: check for mountain influence.

---

### Stage 2: Data Preparation — GLHYMPS K (`s2_data`)

```python
import geopandas as gpd
glhymps = gpd.read_file("/mnt/disk1/Hydrocraft_server/data/groundwater/glhymps/GLHYMPS.shp")
clip = gpd.clip(glhymps, domain_bbox.to_crs(glhymps.crs))
# logK_Ferr_ = log10(k [m²]) × 100 (integer)
k_raw = clip["logK_Ferr_"].dropna(); k_raw = k_raw[(k_raw > -3000) & (k_raw < 0)]
k_m2 = 10 ** float(np.median(k_raw / 100.0))  # intrinsic permeability [m²]
k_ms = k_m2 * 1e7                              # hydraulic conductivity [m/s]
# Typical ranges: High Plains ~1e-13 m², Alluvial Italy/France ~1.58e-12 m²
```

**Unit trap (dt_001):** GLHYMPS gives hydraulic conductivity; DuMux needs intrinsic permeability.
Conversion: `k [m²] = K [m/s] × μ / (ρg) ≈ K × 1e-7` — equivalently `k_m2 = k_ms / 1e7`.

---

### Stage 3: Build params.input (`s3_forcing`)

Required sections and validated values:
```ini
[Grid]
LowerLeft = 0 0
UpperRight = {DX_m} {DY_m}      # in meters
Cells = 50 50                    # 50×50 standard; adjust for larger domains

[SpatialParams]
Permeability = {k_m2}           # m² from GLHYMPS (see Stage 2)
PermeabilityLens = {k_m2*0.1}   # 10× lower for heterogeneity test
LensLowerLeft = ...              # 40-60% of domain extent (lens centered)
LensUpperRight = ...
Porosity = 0.20                  # 0.18-0.28 for alluvial

[TimeLoop]
DtInitial = 86400               # 1 day (steady-state reached in <1 solve)
MaxTimeStepSize = 2592000       # 30 days
TEnd = 315360000                # 10 years (irrelevant for steady-state)

[Problem]
Name = {run_name}
EnableGravity = false            # ALWAYS false for plan-view horizontal flow
FlowDirection = 0                # 0=E-W, 2=N-S (from Stage 0 analysis)
PressureLeft = {P_ATM + rho*g*h_left}   # Pa (absolute pressure)
PressureRight = {P_ATM + rho*g*h_right} # Pa

[Vtk]
AddVelocity = true
Precision = Float64

[LinearSolver]
MaxIterations = 50000
Tolerance = 1e-12
```

**BC pressure conversion:** `p [Pa] = 101325 + 1000 × 9.81 × h [m_asl]`

---

### Stage 4: Build & Execute (`s4_build`)

```bash
DUMUX_BIN=/home/server/knowledge-dissection-toolkit/auto_dissect/_work/DuMux/dumux/dumux/build-cmake/examples/1ptracer/example_1ptracer
# The binary uses the MODIFIED problem_1p.hh (supports FlowDirection=0,2)
# Source: auto_dissect/_work/DuMux/dumux/dumux/examples/1ptracer/problem_1p.hh

cd {RUN_DIR}
$DUMUX_BIN params_{name}.input > /tmp/dumux_{name}.log 2>&1 &
# Kill after 1p.vtu appears (steady-state completes in ~0.1s)
# The tracer transport that follows is NOT needed for head validation
until [ -f 1p.vtu ]; do sleep 1; done
kill $! 2>/dev/null
```

Expected terminal output for successful 1p solve:
```
Assembling linear system ... took 0.07 seconds.
Solving linear system ... took 0.015 seconds.
Simulation took 0.11 seconds on 1 processes.
```

---

### Stage 5: Execution (`s5_run`)

Parse `1p.vtu` → hydraulic head:
```python
import xml.etree.ElementTree as ET
import numpy as np

def parse_vtu_head(path, NX, NY, P_ATM=101325, RHO=1000, G=9.81):
    for da in ET.parse(str(path)).getroot().iter("DataArray"):
        if da.get("Name") in ("p", "pressure"):
            p = np.array([float(x) for x in da.text.split()], dtype=np.float64)
            return ((p - P_ATM) / (RHO * G)).reshape(NY, NX)
    raise RuntimeError("Pressure field 'p' not found in 1p.vtu")

head_sim = parse_vtu_head(RUN/"1p.vtu", NX=50, NY=50)
# head_sim[row, col]: row=lat index (0=south), col=lon index (0=west)
```

---

### Stage 6: Validation + Metrics (`s6_output`)

```python
# Map each well to nearest grid cell
lons_c = np.linspace(LON_MIN+(LON_MAX-LON_MIN)/(2*NX), LON_MAX-(LON_MAX-LON_MIN)/(2*NX), NX)
lats_c = np.linspace(LAT_MIN+(LAT_MAX-LAT_MIN)/(2*NY), LAT_MAX-(LAT_MAX-LAT_MIN)/(2*NY), NY)
sim_at_wells = np.array([
    head_sim[np.argmin(np.abs(lats_c-la)), np.argmin(np.abs(lons_c-lo))]
    for lo, la in zip(lons_interior, lats_interior)
])

# Metrics (interior wells only — exclude BC boundary wells)
obs = p_obs_interior
bias  = np.mean(sim_at_wells - obs)
rmse  = np.sqrt(np.mean((sim_at_wells - obs)**2))
pbias = 100 * np.sum(sim_at_wells - obs) / np.sum(obs)
nse   = 1 - np.sum((obs - sim_at_wells)**2) / np.sum((obs - obs.mean())**2)
r2    = np.corrcoef(obs, sim_at_wells)[0,1]**2
```

**Expected performance by aquifer type:**
| Aquifer | Reference | NSE | R² | RMSE |
|---|---|---|---|---|
| High Plains 2019 | D2WT Zenodo #5851676 | 0.74 | 0.85 | 53.5m |
| High Plains 1989 | D2WT Zenodo #5851676 | 0.71 | 0.83 | 55.4m |
| Veneto flat plain | Zenodo #12800734 | 0.26 | 0.30 | 10.4m |
| Complex/mountain | any | < 0 | < 0.1 | > 50m |

**Darcy flux cross-check:**
```python
darcy_ms = -k_ms * (h_right - h_left) / (DX_KM * 1000)  # m/s
darcy_mm_yr = darcy_ms * 86400 * 365 * 1000
# Typical ranges: alluvial plain 50-400mm/yr; High Plains ~160mm/yr
```

---

## Validated Observation Sources

| Dataset | ID in obs_datasets | Best use |
|---|---|---|
| US D2WT 2019 + 1989 (14,351 wells) | `d2wt_us_ngwmn` | High Plains, any US unconfined aquifer |
| Veneto 42 wells (m asl 2019) | `veneto_wt_2019` | NE Italy flat alluvial |
| FrenchPiezo 1026 wells (m NGF 2015-2021) | `frenchpiezo_2015_2021` | French flat unconfined domains |
| China TWSA 0.1° (GRACE, 2002-2019) | `china_twsa_01deg` | NCP basin storage budget |
| GRACE/GRACE-FO TWS (global) | `grace` | Any basin-scale storage cross-check |
| Fan WTD global | `fan_wtd_global` | Coarse BCs only, not artesian/confined |

---

## C++ Modifications (problem_1p.hh)

The validated binary supports three flow modes via `params.input`:

| FlowDirection | BCs | Dirichlet faces | Use case |
|---|---|---|---|
| 0 (default) | PressureLeft (x=0), PressureRight (x=xMax) | Left + Right | E-W flow (High Plains) |
| 2 | PressureLeft (y=0=south), PressureRight (y=yMax=north) | Bottom + Top | N-S flow (Veneto, Garonne) |
| 1 | Hardcoded legacy formula | Bottom + Top | Not for real-world use |

Source modified: `auto_dissect/_work/DuMux/dumux/dumux/examples/1ptracer/problem_1p.hh`
Binary: `auto_dissect/_work/DuMux/dumux/dumux/build-cmake/examples/1ptracer/example_1ptracer`
