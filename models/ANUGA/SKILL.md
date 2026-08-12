# ANUGA Skill

**Type:** 2D depth-averaged shallow-water hydrodynamics (finite-volume, unstructured triangular mesh)
**Primary use:** tsunami inundation, dam-break, flood modeling
**Authoritative source:** https://github.com/anuga-community/anuga_core
**Installed at:** /home/server/.local/lib/python3.12/site-packages/anuga

## KI Tools

All tools are in `tools/` and use `ki_tools_common.load_forcing` for CMFD/MSWX/NASA POWER data.

| Tool | Purpose |
|------|---------|
| `tools/convert_forcing_to_anuga.py` | Convert CMFD/MSWX/NASA POWER forcing → rainfall time series CSV (m/s) |
| `tools/load_hydat_series.py` | Extract a daily HYDAT flow **or** level series (+ vertical-datum metadata) → tidy `date,value,symbol` CSV |
| `tools/build_inflow_hydrograph.py` | Gauge discharge (China TAB archive **or** tidy CSV) → `time_seconds,discharge_m3s` for `Inlet_operator` |
| `tools/run_anuga.py` | Set up domain from DEM, apply rainfall and/or riverine inflow, run simulation → SWW output |
| `tools/parse_anuga_output.py` | Extract discharge (via cross-section), stage at a gauge, and inundation extent from SWW output |

### Two forcing modes — pick the one the event actually has

* **Rain-on-grid** (`run_anuga.py --forcing_csv`, `Rate_operator`): rainfall
  falls on the whole mesh. Correct for a small headwater box; it CANNOT
  reproduce a flood routed in from upstream.
* **Riverine inflow** (`run_anuga.py --inflow_csv --inlet_latlon`,
  `Inlet_operator`): a prescribed discharge hydrograph enters at a point on the
  channel. This is the dag's first-class `inflow discharge` forcing and the
  right mode for any reach whose water comes from upstream. The two can be
  combined.

### Coordinate frames — the #1 source of silent wrong answers

ANUGA uses **two** frames and they differ by `extent_m/2`:

| Frame | Range | Used by |
|-------|-------|---------|
| mesh-relative | `0 .. extent_m` | `set_quantity()` callables (elevation fitting) |
| absolute (polygon) | `-extent_m/2 .. +extent_m/2` | `anuga.Region` (inlet), SWW `x + xllcorner` (gauge) |

Never hand-convert. Use `--inlet_latlon LAT LON` (run_anuga.py) and
`--gauge_latlon LAT,LON` with `--center_lat/--center_lon`
(parse_anuga_output.py); both route through `run_anuga.latlon_to_domain_xy`.
`run_anuga.py` also carries a post-fit **elevation range guard** that raises if
the fitted terrain escapes the source DEM range — that guard is what catches a
frame/extrapolation bug instead of silently fabricating ±1000 m terrain.

### DEM selection

`run_anuga.py` resolves terrain in this order: `--dem_path` → the China 90 m
DEM (only when the whole domain bbox fits inside it) → the overlapping
**MERIT DEM 90 m** global tiles (`/mnt/datasets/MERIT_DEM/nNNwWWW_dem.tif`,
mosaicked automatically across a seam). MERIT is EGM96 orthometric; the China
DEM is SRTM. There is **no synthetic-terrain fallback** unless you pass
`--allow_synthetic_dem` (smoke tests only).

### Real-world simulation workflow

```bash
# 1. Convert forcing to ANUGA rainfall format
python tools/convert_forcing_to_anuga.py \
    --source cmfd --lat 32.9 --lon 117.4 \
    --start_year 2005 --end_year 2005 \
    --output_dir ./forcing/

# 2. Run ANUGA simulation with DEM and rainfall
python tools/run_anuga.py \
    --lat 32.9 --lon 117.4 --extent_m 5000 \
    --forcing_csv ./forcing/rainfall_timeseries.csv \
    --output_dir ./output/ --finaltime 86400

# 3. Extract discharge at outlet cross-section
python tools/parse_anuga_output.py \
    --sww_file ./output/anuga_sim.sww \
    --cross_section "-2500,0,2500,0" \
    --output_csv ./output/discharge.csv
```

### Riverine workflow — stage at a gauge (worked example, HYDAT)

Validated 2026-08-09 on the Fraser River: inlet driven by observed discharge at
HYDAT `08MF005` (Fraser R. at Hope), stage scored at HYDAT `08MF035` (Fraser R.
near Agassiz) 31 km downstream. Drive from an **upstream** station and score at
a **different, downstream** station — driving and scoring the same gauge only
reproduces its rating curve.

```bash
# 1. Observations: upstream discharge (driver) + downstream level (target)
python tools/load_hydat_series.py --station 08MF005 --variable flow \
    --start 2020-04-01 --end 2020-06-30 --output_csv ./obs/hope_flow.csv
python tools/load_hydat_series.py --station 08MF035 --variable level \
    --start 2020-04-01 --end 2020-06-30 --output_csv ./obs/agassiz_level.csv

# 2. Inlet hydrograph (t=0 at --start, shared origin with the rainfall CSV)
python tools/build_inflow_hydrograph.py --gauge_csv ./obs/hope_flow.csv \
    --start 2020-04-01 --end 2020-06-30 --output_csv ./forcing/inflow.csv

# 3. Run: Inlet_operator on the channel, Transmissive outlet facing downstream
python tools/run_anuga.py --lat 49.230 --lon -121.740 --extent_m 20000 \
    --max_area 30000 --manning_n 0.035 --outlet_side left \
    --inflow_csv ./forcing/inflow.csv \
    --inlet_latlon 49.2745 -121.651 --inlet_radius_m 1200 \
    --finaltime 7862400 --yieldstep 21600 --output_dir ./output/

# 4. Stage at the gauge, snapped to the channel low point
python tools/parse_anuga_output.py --sww_file ./output/anuga_sim.sww \
    --gauge_latlon "49.20369,-121.77583" \
    --center_lat 49.230 --center_lon -121.740 \
    --snap_to_channel_m 400 --output_csv ./output/stage.csv
```

**Vertical datum — check BEFORE scoring stage.** ANUGA carries no datum
awareness, so an absolute stage comparison is only meaningful when the gauge
datum is geodetic. `load_hydat_series.py` writes `<csv>.meta.json` with
`datum_name`, `datum_id` and every published `STN_DATUM_CONVERSION` offset.
Many HYDAT stations use `ASSUMED DATUM` (id 10) whose zero is arbitrary — e.g.
`08MF005` levels need `+27.926 m` to reach the GSC geodetic datum. Score
against a station whose own datum is geodetic (`08MF035` = id 35), or apply the
published conversion; never compare a raw arbitrary-datum level to DEM
elevations.

**`--snap_to_channel_m` is not cosmetic.** A published gauge lat/lon is a bank
or bridge position. On a 30–90 m DEM the nearest mesh vertex is routinely a
bank cell that never wets, so the extracted "stage" is a CONSTANT equal to the
bank elevation. `parse_anuga_output.py` warns when the extraction vertex is wet
in <50 % of stored timesteps — treat that warning as a hard stop, not noise.

**Known limitation of a 90 m DEM for absolute stage.** MERIT/SRTM record the
*water surface* at acquisition, not the bed, and resolve neither the channel
bathymetry nor engineered dikes. On a large diked river the model therefore
conveys the flood across the whole floodplain and the absolute stage is biased
low. Prefer `r` / timing for a KI-validity verdict on such a reach and read
`nse`/`pbias` as a terrain-data statement, not a solver statement.

### Key variables

| Variable | Source | Unit |
|----------|--------|------|
| stage | direct ANUGA output (SWW) | m |
| depth | stage − elevation | m |
| discharge | `anuga.get_flow_through_cross_section()` on SWW | m³/s |

### Unit conversions (forcing)

- CMFD precip: kg/m²/s → mm/timestep (×timestep_s) → m/s (÷1000 ÷ timestep_s)
- ANUGA `Rate_operator` expects rainfall in **m/s**

## Parameters

| Parameter | Description | Typical Range | Unit |
|-----------|-------------|---------------|------|
| `maximum_triangle_area` | Maximum mesh element area; controls spatial resolution | 100–10000 | m² |
| `Manning's n` | Surface roughness coefficient for friction model | 0.01–0.15 | s/m^(1/3) |
| `finaltime` | Simulation end time | 50–86400 | s |
| `flow_algorithm` | Shallow water solver variant (`DE0`, `DE1`, `1_5Dkp`) | — | — |
| `minimum_storable_height` | Minimum depth below which cell is considered dry | 0.001–0.01 | m |
| `minimum_allowed_height` | Absolute minimum water depth for numerical stability | 1e-5–1e-3 | m |

Calibration is typically limited to Manning's n and mesh resolution. ANUGA is a physics-based solver; most parameters are physical constants, not tuneable coefficients.

## Output Description

ANUGA writes simulation results to **SWW files** (NetCDF-like format):

| Output Variable | Description | Unit | File |
|----------------|-------------|------|------|
| `stage` | Water surface elevation | m | SWW |
| `xmomentum` | Depth-averaged x-momentum | m²/s | SWW |
| `ymomentum` | Depth-averaged y-momentum | m²/s | SWW |
| `elevation` | Bed elevation (static) | m | SWW |
| `depth` | Water depth (stage − elevation) | m | derived |
| `discharge` | Flow through cross-section | m³/s | derived via `get_flow_through_cross_section()` |

Use `parse_anuga_output.py` to extract stage/discharge time series to CSV. SWW files can also be visualized with `anuga_viewer` or converted to raster grids for GIS analysis.

## Validation strategy

ANUGA is a physics solver, not a forecasting model. The correct validation is against
**analytical / closed-form solutions**, not gauge NSE/KGE. Treat `comparison_type='analytical'`
as the default mode for ANUGA tests.

Standard benchmarks shipped under `validation_tests/analytical_exact/` in the source repo:

| Test | Analytical reference | Use |
|------|----------------------|-----|
| `dam_break_wet` | Stoker / Ritter (Riemann) | quick wet-bed dam-break benchmark (default) |
| `dam_break_dry` | Ritter | dry-bed benchmark |
| `carrier_greenspan_transient` | Carrier & Greenspan 1958 | canonical linear-slope runup |
| `parabolic_basin` | Thacker 1981 | oscillating parabolic basin |
| `runup_on_beach` | steady-state flat lake | smoke test |

## Default test

`dam_break_wet`: 1D Stoker dam-break on a 1000 m x 5 m flat channel, h1=10 m (left),
h0=1 m (right), no friction, finaltime=50 s. Compare modeled stage along the centerline
at t=50 s against `anuga.validation_tests.analytical_exact.dam_break_wet.analytical_dam_break_wet.vec_dam_break`.

## Execution

```
python -c "import anuga" # sanity
# runner: diagnostics/run_dam_break_wet.py — loads numerical + analytical, writes NSE/R/KGE
```

Metric reporting: NSE, Pearson R, KGE computed on 1D centerline stage profile
(numerical_stage at t_final vs analytical h at the same x).

## Notes on previous failure

The earlier run used `examples/simple_examples/runup.py` (synthetic 10x10 rectangular beach)
with `comparison_type='none'`, yielding null metrics. The fix is to switch to an
analytical-solution benchmark and compare pointwise.
