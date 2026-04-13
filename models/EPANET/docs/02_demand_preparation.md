# Stage 1-2: Demand Preparation and Network Parameterization

## Purpose

Convert water demand data and network infrastructure parameters into EPANET-compatible format, handling unit conversions, time pattern generation, and multiple demand categories per junction.

## Inputs

| Input | Source | Format | Units |
|-------|--------|--------|-------|
| Base demands per junction | Billing records, metering, population estimates | CSV | Flow units (match [OPTIONS]) |
| Demand patterns | SCADA, diurnal curves, seasonal data | Time series | Dimensionless multipliers |
| Pipe inventory | GIS/asset database | CSV | Diameter, length, roughness |
| Tank specifications | Engineering data | CSV | Elevation, levels, diameter |
| Pump curves | Manufacturer specs | CSV | Head vs. Flow pairs |

## Outputs

| Output | Format | Used By |
|--------|--------|---------|
| Complete .inp file | EPANET text input | Stage 7 (run_epanet) |
| Validation report | Console/log | Operator review |

## Procedure

### 1. Determine Unit System

**Critical decision**: Choose flow units first — this cascades to ALL other units.

```
US Customary:  CFS, GPM, MGD, IMGD, AFD  →  ft, in, psi
SI Metric:     LPS, LPM, MLD, CMH, CMD   →  m, mm, meters(pressure)
```

### 2. Prepare Base Demands

Base demand is the average water withdrawal rate at each junction.

**From billing data**:
```python
# Monthly billing (gallons) → GPM base demand
demand_gpm = monthly_gallons / (days * 24 * 60)
```

**From population**:
```python
# Per-capita demand (typically 80-100 gpd in US)
demand_gpm = population * per_capita_gpd / (24 * 60)
```

**Sign convention**: Positive demand = water leaves network. Negative demand = water enters network (e.g., well injection).

### 3. Create Demand Patterns

Patterns are dimensionless multiplier sequences applied to base demands.

```
[PATTERNS]
;ID    Multipliers (one per pattern timestep)
;      12am  6am   12pm  6pm
PAT1   0.5   1.3   1.0   1.2
```

- Pattern timestep is set in [TIMES] (default: 6 hours if 4 multipliers for 24h)
- Multiplier of 1.0 = base demand; 1.3 = 130% of base
- Pattern repeats cyclically over simulation duration

### 4. Handle Multiple Demand Categories

Use [DEMANDS] section for junctions with multiple demand types:

```
[DEMANDS]
;Junction  Demand  Pattern   ;Category
J1         100     PAT_DOM   ;Domestic
J1         25      PAT_COM   ;Commercial
J1         50      PAT_IND   ;Industrial
```

### 5. Run Unit Conversion Tool

```bash
python tools/convert_demands_to_inp.py \
    --junctions junctions.csv \
    --pipes pipes.csv \
    --units LPS \
    --headloss H-W \
    --input-units SI \
    --duration 72 \
    --timestep 1 \
    --output network.inp
```

### 6. Validate Parameter Ranges

```bash
python tools/convert_network_params.py \
    --pipes pipes.csv \
    --tanks tanks.csv \
    --source-units SI \
    --target-units SI \
    --headloss H-W \
    --output params_check.json
```

## Verification

- [ ] All junction demands sum to expected total system demand
- [ ] Pattern multipliers average close to 1.0 (unless seasonal scaling intended)
- [ ] Pipe roughness matches headloss formula (H-W C-factor ≠ D-W roughness height)
- [ ] Elevations are in correct units (ft for US, m for SI)
- [ ] Tank init_level is between min_level and max_level
- [ ] All referenced pattern IDs exist in [PATTERNS] section
- [ ] All referenced curve IDs exist in [CURVES] section

## Traps

| Trap | Symptom | Prevention |
|------|---------|------------|
| **H-W roughness with D-W formula** | Unrealistic headloss (0.001 used as D-W height vs 100 as H-W C) | Verify roughness interpretation matches [OPTIONS] Headloss |
| **Demand in wrong flow units** | Total demand off by orders of magnitude | Double-check: GPM demand ≈ 15.85× LPS demand |
| **Elevation in wrong length units** | Pressures off by 3.28× (ft/m confusion) | Verify unit system matches flow unit choice |
| **Pattern timestep mismatch** | Demand peaks at wrong times | Ensure [TIMES] Pattern Timestep matches multiplier count |
| **Pipe diameter in wrong units** | 12 mm pipe (should be 12 in = 305 mm) | Pipes use in (US) or mm (SI), NOT ft or m |
| **Tank diameter in wrong units** | 70 mm tank (should be 70 ft) | Tanks use ft (US) or m (SI), NOT in or mm |
| **Missing default pattern** | Demand stays constant despite pattern intent | Set `Pattern 1` in [OPTIONS] or define Pattern 1 |

## Example

Converting SI data for a US-unit EPANET model:

```python
# SI source data
elevation_m = 213.36    # meters
pipe_diam_mm = 304.8    # millimeters
demand_lps = 4.1        # liters/second

# Convert to US
elevation_ft = elevation_m / 0.3048     # = 700 ft
pipe_diam_in = pipe_diam_mm / 25.4      # = 12 in
demand_gpm = demand_lps * 15.8503       # = 65 GPM
```
