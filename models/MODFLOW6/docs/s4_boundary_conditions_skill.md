# Boundary Conditions — Skill Document

> **Stage ID**: s4_boundary_conditions
> **Pipeline order**: 4 of 9
> **Depends on**: s2_grid_discretization

## Purpose

Boundary conditions define how water enters and leaves the groundwater system. Without them, the model has no driving forces and produces trivial solutions. MODFLOW 6 provides seven standard stress packages (CHD, WEL, DRN, RIV, GHB, RCH, EVT) and four advanced packages (SFR, LAK, MAW, UZF). In HydroCraft, the most important are RCH (coupled to VIC), RIV (coupled to CaMa-Flood), and DRN (baseflow to routing).

## Prerequisites

Before starting this stage, verify:

- [ ] DIS package exists with IDOMAIN defined (S2 complete)
- [ ] Recharge data available (VIC baseflow output or estimated recharge rate)
- [ ] River network known (locations, stages, bed elevations, conductance)
- [ ] Pumping well data available (if applicable)
- [ ] Units are consistent: length in meters, time in days (if those are model units)

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| recharge_rate | config | VIC output / estimate | Recharge rate in m/day |
| vic_recharge_nc | file | VIC coupling | NetCDF with VIC deep percolation (optional) |
| river_cells | config | GIS / CaMa-Flood | River cell locations, stages, conductances |
| cama_stage_nc | file | CaMa-Flood | Dynamic river stage NetCDF (optional) |
| drain_cells | config | GIS / DEM | Drain locations and elevations |
| well_data | config | user | Well locations and pumping rates |
| chd_cells | config | user | Constant head boundary cells |

## Procedure

### Step 1: Determine Required Boundary Packages

Every model needs at least one source and one sink of water. Typical configurations:

| Scenario | Packages | Notes |
|----------|----------|-------|
| Simple basin | RCH + DRN | Recharge drives flow, drains remove water at surface |
| With rivers | RCH + RIV | Rivers can gain or lose water |
| With pumping | RCH + WEL + DRN | Wells extract, drains provide baseflow |
| Full coupling | RCH + RIV + DRN + WEL | VIC->RCH, CaMa->RIV, DRN->routing |
| Fixed boundaries | CHD + RCH | Constant head at domain edges |

### Step 2: Build RCH Package (Recharge)

Recharge is the primary inflow for most models. RCH applies areal recharge to the **highest active cell** in each column.

```bash
python tools/s4/build_rch_package.py
```

**Critical unit conversion for VIC coupling**:
- VIC OUT_BASEFLOW is in **mm/day**
- MODFLOW RCH expects **m/day** (if LENGTH_UNITS = meters)
- Conversion: `recharge_m_day = vic_baseflow_mm_day / 1000.0`

**Typical recharge rates** (m/day):
- Arid: 0.00001 - 0.0001 (0.01-0.1 mm/day)
- Semi-arid: 0.0001 - 0.001 (0.1-1 mm/day)
- Humid: 0.001 - 0.01 (1-10 mm/day)

**Expected result**: RCH package attached to model.

**If this fails**: See dt_mf6_004 (unit error) or dt_mf6_008 (wrong layer).

### Step 3: Build RIV Package (Rivers) — If Applicable

Each river cell requires four values:
1. **cellid**: (layer, row, col) — 0-indexed in FloPy
2. **stage**: water surface elevation (m)
3. **conductance**: riverbed conductance (m2/day) = K_bed * L * W / M_bed
   - K_bed: riverbed hydraulic conductivity (m/day)
   - L: reach length within cell (m)
   - W: river width (m)
   - M_bed: riverbed thickness (m), typically 0.5-2 m
4. **rbot**: river bottom elevation (m) — must be < stage

```bash
python tools/s4/build_riv_package.py
```

For CaMa-Flood coupling, provide `cama_stage_nc` to use dynamic stages.

**Expected result**: RIV package attached to model.

### Step 4: Build DRN Package (Drains) — If Applicable

Drains remove water when head > drain elevation. Used for:
- Springs and seeps
- Stream baseflow generation
- Tile drainage systems

Each drain cell requires: cellid, elevation, conductance.

```bash
python tools/s4/build_drn_package.py
```

**Expected result**: DRN package attached to model.

### Step 5: Build WEL Package (Wells) — If Applicable

Well rates are **volumetric** (m3/day):
- **Negative** = pumping (extraction)
- **Positive** = injection

```bash
python tools/s4/build_wel_package.py
```

**Expected result**: WEL package attached to model.

### Step 6: Build CHD Package (Constant Head) — If Applicable

Constant head cells fix the head at a specified value. Use sparingly — they are infinite sources/sinks.

```bash
python tools/s4/build_chd_package.py
```

Common uses:
- Ocean boundary (head = 0)
- Large lake boundary
- Lateral model boundaries with known head

**Expected result**: CHD package attached to model.

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| RCH package | `workspace/gwf.rch` | Recharge values in correct units |
| RIV package | `workspace/gwf.riv` | Stage > rbot for all river cells |
| DRN package | `workspace/gwf.drn` | Drain elevations within model domain |
| WEL package | `workspace/gwf.wel` | Pumping rates negative |
| CHD package | `workspace/gwf.chd` | Heads within physical range |

## Validation Checks

1. **Recharge units**: Multiply recharge by cell area and total time; compare total volume to expected annual recharge depth * basin area
   - Expected: Within 20% of literature/VIC values
   - If unexpected: See dt_mf6_004

2. **River stage > rbot**: For all RIV cells, stage must exceed river bottom
   - Command: Check all RIV entries
   - Expected: stage - rbot > 0 for every cell
   - If unexpected: River bottom is above water surface — check DEM/bathymetry data

3. **Well cells active**: All WEL cells have IDOMAIN > 0
   - Expected: No wells in inactive cells
   - If unexpected: Well will be silently ignored

4. **CHD not everywhere**: Model should have non-CHD active cells to solve
   - Expected: CHD cells < 50% of active cells
   - If unexpected: Over-constrained model — MODFLOW will warn

5. **Water budget closure potential**: Sources (RCH + WEL injection + RIV gaining) should roughly balance sinks (DRN + WEL pumping + RIV losing)
   - Expected: Order-of-magnitude balance
   - If unexpected: Missing source or sink package

## Common Pitfalls

> **PITFALL**: Recharge in mm/day instead of m/day
> VIC outputs deep percolation in mm/day. Passing this directly to MODFLOW RCH without dividing by 1000 gives recharge 1000x too high. The model may still converge, but heads will be unrealistically high and water table will be above land surface.
> **Do this instead**: Always divide by 1000: `rch_m_day = vic_baseflow_mm_day / 1000.0`
> See diagnostic triplet dt_mf6_004.

> **PITFALL**: RCH applied to wrong layer
> By default, MODFLOW 6 RCH (`READASARRAYS`) applies recharge to the highest active cell in each column. If you use the list-based RCH and specify cellid with layer > 0, recharge bypasses the unsaturated zone.
> **Do this instead**: Use `flopy.mf6.ModflowGwfrcha` (array-based RCH) which auto-applies to the top active cell.
> See diagnostic triplet dt_mf6_008.

> **PITFALL**: River conductance too high or too low
> Too high (>10000 m2/day): river is essentially a constant head — dominates the solution.
> Too low (<1 m2/day): river has no influence on groundwater.
> **Do this instead**: Start with K_bed=1 m/day, width=10-50 m, length=cell_size, bed_thickness=1 m. Conductance = K_bed * L * W / M_bed.

> **PITFALL**: Drain elevation above land surface
> If drain elevation > TOP, the drain is always active and acts like a constant head boundary, removing unlimited water.
> **Do this instead**: Set drain elevation at or below the land surface (TOP array).

---

*This skill document is part of the modflow6-knowledge-infrastructure package.*
*Stage 4 of 9 | Tools used: build_chd_package, build_rch_package, build_riv_package, build_drn_package, build_wel_package | Related triplets: dt_mf6_004, dt_mf6_008, dt_mf6_013*
