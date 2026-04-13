# S1 — Domain Setup

## Purpose

Define the spatial and temporal domain for a pyBadlands landscape evolution simulation.
This includes selecting the study area, choosing the DEM extent and resolution, defining
boundary conditions, and setting the simulation time span.

## Inputs

| Input | Format | Units | Source |
|-------|--------|-------|--------|
| Study area extent | lat/lon or projected coords | degrees or m | User-defined |
| DEM raster | GeoTIFF, netCDF, CSV | m (elevation) | SRTM, ALOS, ASTER |
| Simulation time span | start, end | years | Literature / research question |
| Output frequency | display interval | years | User-defined |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Project directory | folder | Contains XML, DEM, forcing data |
| XML skeleton | `.xml` | Template configuration file |
| Domain extent | metadata | Bounding box and resolution |

## Procedure

1. **Select study area** — Identify the basin or region of interest. For basin-scale
   studies (10–1000 km), ensure the DEM captures the full drainage area plus a buffer
   zone of at least 10% on each side.

2. **Obtain DEM** — Download from SRTM (30 m or 90 m) or ALOS (30 m). For geological
   time scale simulations (> 1 Myr), lower resolution (500 m – 5 km) is typical.
   Ensure elevation is in **metres** (dt_003).

3. **Choose resolution factor** — The `resfactor` parameter in `<grid>` sub-samples the
   DEM by this integer factor. Set `resfactor=1` for full resolution. For large domains,
   `resfactor=2–5` reduces mesh size significantly.

4. **Set boundary conditions** — Choose based on domain geometry:
   - `slope`: Open boundary, gradient extrapolation (default, for most cases)
   - `flat`: Fixed zero-gradient boundary
   - `wall`: No-flow boundary (closed basin)
   - `fixed`: Fixed elevation at boundary
   - `outlet`: Single outlet point (for catchment studies)

5. **Define time parameters** — Set `start`, `end`, `display` in XML `<time>` section.
   All times in **years**. Set adaptive timestep bounds: `mindt` (typically 1–100 yr)
   and `maxdt` (typically 1e4–1e6 yr).

6. **Create output directory** — `mkdir -p output` before running (dt_009).

## Verification

- [ ] DEM elevation values are in metres (check z-range)
- [ ] DEM spatial extent covers study area with buffer
- [ ] Boundary condition matches domain geometry (dt_008)
- [ ] Time span is physically reasonable for the process being modeled
- [ ] Output directory exists
- [ ] `resfactor` does not reduce resolution below meaningful scale

## Traps

| ID | Trap | Consequence |
|----|------|-------------|
| dt_003 | DEM in cm or ft instead of m | All erosion rates wrong |
| dt_008 | Fixed boundary on open landscape | Artificial water ponding |
| dt_009 | Output folder missing | Silent crash at first output step |
| dt_013 | resfactor too large | Mesh too coarse, features lost |

## Example

```xml
<grid>
    <demfile>dem_500m.csv</demfile>
    <boundary>slope</boundary>
    <resfactor>1</resfactor>
</grid>

<time>
    <start>0</start>
    <end>5000000</end>
    <display>50000</display>
    <mindt>10</mindt>
    <maxdt>500000</maxdt>
</time>

<outfolder>output</outfolder>
```
