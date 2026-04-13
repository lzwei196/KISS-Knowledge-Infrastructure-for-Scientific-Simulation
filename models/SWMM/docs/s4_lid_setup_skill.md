# LID / Green Infrastructure Setup — Skill Document

> **Stage ID**: s4_lid_setup
> **Pipeline order**: 4 of 7
> **Depends on**: s1_subcatchment_delineation

## Purpose

Low Impact Development (LID) controls represent green infrastructure practices that manage stormwater at the source. SWMM models LID as multi-layer systems within subcatchments that intercept, store, infiltrate, and slowly release rainfall before it becomes runoff. LID modeling enables evaluation of green infrastructure performance for volume reduction, peak flow attenuation, and water quality improvement.

SWMM supports 8 LID types, each with distinct physical layers and hydrologic behavior. LID controls are defined globally (specifying the physical properties of each LID type) and then assigned to specific subcatchments with placement details (area, number of units, routing).

This stage is optional — skip it for conventional (gray infrastructure only) drainage models. However, for green infrastructure design, climate adaptation, or combined gray-green infrastructure analysis, LID setup is essential.

## Prerequisites

Before starting this stage, verify:

- [ ] Subcatchments are delineated (S1 complete) — LID controls are placed on subcatchments
- [ ] LID design specifications are available (type, dimensions, soil media properties)
- [ ] Decision on which subcatchments receive LID and what percentage of area
- [ ] Soil infiltration rates at LID locations are known (for native soil infiltration below LID)
- [ ] Python environment has: numpy

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| LID type | string | Design specification | BC, RG, GR, IT, PP, RB, RD, or VS |
| LID dimensions | config | Design drawings, guidelines | Layer thicknesses, media properties |
| Subcatchment assignments | config | Design plan | Which subcatchments get which LID, how much area |
| Native soil Ksat | number | Soil survey, field test | Infiltration rate of soil below LID (mm/hr) |

## Procedure

### Step 1: Select LID Types

SWMM supports 8 LID types:

| Code | Type | Layers | Typical Application |
|------|------|--------|---------------------|
| BC | Bioretention Cell | Surface + Soil + Storage + Drain | Roadside rain gardens, parking lot islands |
| RG | Rain Garden | Surface + Soil | Shallow landscape depressions, no underdrain |
| GR | Green Roof | Surface + Soil + DrainMat | Building rooftops |
| IT | Infiltration Trench | Surface + Storage | Linear trenches along roads, parking lots |
| PP | Permeable Pavement | Surface + Pavement + Soil + Storage + Drain | Parking lots, driveways, walkways |
| RB | Rain Barrel | Storage + Drain | Downspout collection |
| RD | Rooftop Disconnection | Surface | Redirect roof runoff to pervious areas |
| VS | Vegetative Swale | Surface | Roadside grass channels |

### Step 2: Define LID Control Parameters

Each LID type uses a subset of the available parameter layers. Define parameters for each layer:

#### Surface Layer (all LID types)

| Parameter | Description | Units | Typical Range |
|-----------|-------------|-------|---------------|
| Berm Height | Maximum ponding depth | mm | 50-300 (BC); 0 (GR, PP) |
| Vegetation Volume | Fraction of volume occupied by vegetation | fraction | 0.0-0.2 |
| Surface Roughness | Manning's n for surface flow | — | 0.01-0.40 |
| Surface Slope | Surface slope | % | 0-5 (BC, GR); 1-5 (VS) |
| Swale Side Slope | Side slope for swale (VS only) | run/rise | 3-5 |

#### Soil Layer (BC, RG, GR, PP)

| Parameter | Description | Units | Typical Range |
|-----------|-------------|-------|---------------|
| Thickness | Soil media depth | mm | 300-900 (BC); 75-150 (GR) |
| Porosity | Total pore space | fraction | 0.40-0.55 |
| Field Capacity | Moisture at field capacity | fraction | 0.15-0.30 |
| Wilting Point | Moisture at wilting point | fraction | 0.05-0.15 |
| Conductivity | Saturated hydraulic conductivity | mm/hr | 10-150 |
| Suction Head | Wetting front suction head | mm | 30-100 |

**CRITICAL CONSTRAINT**: Wilting Point < Field Capacity < Porosity. Violating this constraint is a common error that makes the soil layer non-functional (no water retention or no drainage). See dt_011.

#### Storage Layer (BC, IT, PP, RB)

| Parameter | Description | Units | Typical Range |
|-----------|-------------|-------|---------------|
| Height | Storage layer depth | mm | 150-600 |
| Void Ratio | Volume of voids / volume of solids | fraction | 0.40-0.80 (gravel) |
| Seepage Rate | Native soil infiltration rate below storage | mm/hr | 0-25 |
| Clog Factor | Clogging potential (0=none) | — | 0 (clean) to 100 (heavy) |

#### Drain Layer (BC, PP, RB)

| Parameter | Description | Units | Typical Range |
|-----------|-------------|-------|---------------|
| Coefficient | Drain flow coefficient | mm/hr | 0-100 |
| Exponent | Drain flow exponent | — | 0.5 |
| Offset | Drain pipe offset from bottom | mm | 0-150 |
| Delay | Hours to drain after rain stops | hours | 0-12 |

The drain flow equation is: Q = Coeff * (h - Offset)^Exponent, where h is the depth of water in the storage layer above the drain offset.

**CRITICAL**: Drain Offset must be < Storage Height. If Offset >= Height, the drain never activates and the LID fills up permanently. See dt_019.

```bash
python tools/s4_lid_setup/create_lid_control.py \
  --lid_type BC \
  --lid_name Bioretention_Standard \
  --surface_params '{"berm_height": 150, "veg_volume": 0.1, "roughness": 0.1, "slope": 1.0}' \
  --soil_params '{"thickness": 600, "porosity": 0.5, "field_capacity": 0.2, "wilting_point": 0.1, "ksat": 25, "suction_head": 50}' \
  --storage_params '{"height": 300, "void_ratio": 0.75, "ksat": 10}' \
  --drain_params '{"coefficient": 5.0, "exponent": 0.5, "offset": 100, "delay": 6}' \
  --output_file outputs/swmm_run/lid/bioretention.txt
```

### Step 3: Assign LID Controls to Subcatchments

LID_USAGE links globally-defined LID controls to specific subcatchments:

| Parameter | Description |
|-----------|-------------|
| Subcatchment | ID of subcatchment receiving the LID |
| LID Process | Name of the LID control (from LID_CONTROLS) |
| Number | Number of replicate LID units |
| Area | Area of each LID unit (m2 or ft2) |
| Width | Width of each unit's outflow face (m or ft) |
| InitSat | Initial soil saturation (0-100%) |
| FromImperv | % of subcatchment's impervious runoff routed to LID |
| ToPerv | 1 = LID overflow goes to pervious area; 0 = goes to outlet |
| RptFile | Optional file for detailed LID performance report |

```bash
python tools/s4_lid_setup/assign_lid_to_subcatchment.py \
  --lid_assignments '[{"subcatch_id": "S1", "lid_name": "Bioretention_Standard", "number": 5, "area": 50, "width": 10, "init_sat": 0, "from_imperv": 25, "to_perv": 0}]' \
  --subcatchment_areas '{"S1": 25000}' \
  --output_file outputs/swmm_run/lid/lid_usage.txt
```

**CRITICAL**: Total LID area per subcatchment (Number * Area for all LID types) must not exceed the subcatchment total area. If it does, SWMM silently reduces the effective subcatchment area, producing wrong results. See dt_019.

### Step 4: Validate LID Parameters

```bash
python tools/s4_lid_setup/validate_lid_params.py \
  --lid_controls outputs/swmm_run/lid/bioretention.txt \
  --lid_usage outputs/swmm_run/lid/lid_usage.txt \
  --subcatchment_areas '{"S1": 25000}'
```

## Expected Outputs

| Output | Path Pattern | Description |
|--------|-------------|-------------|
| LID control definitions | `{output_dir}/lid_controls.txt` | Physical properties of each LID type |
| LID usage assignments | `{output_dir}/lid_usage.txt` | Placement on subcatchments |
| Validation report | (stdout/JSON) | Parameter consistency checks |

## Validation Checks

1. **Soil physical consistency**: Wilting Point < Field Capacity < Porosity (MANDATORY)
2. **Storage void ratio**: In range (0, 1)
3. **Drain offset**: Less than storage height (if both exist)
4. **Area constraint**: Total LID area <= subcatchment area per subcatchment
5. **Required layers**: Each LID type has its required layers defined
6. **Conductivity**: Ksat > 0 for soil and storage layers
7. **Berm height**: > 0 for bioretention, rain gardens; can be 0 for green roofs
8. **From_imperv total**: Sum of from_imperv for all LIDs on a subcatchment <= 100%

## Common Pitfalls

**Soil params WP >= FC or FC >= Porosity (dt_011)**: The most common LID error. If wilting_point = 0.25 and field_capacity = 0.20 (WP > FC), the soil has negative available water capacity. SWMM may run but the soil layer behaves unrealistically — either not retaining water or not draining.

**LID area exceeds subcatchment area (dt_019)**: If Number * Area > subcatchment total area, SWMM clips the LID area. The user sees no error, but LID performance is underestimated because the reported LID area is larger than what SWMM actually uses.

**Drain coefficient = 0 with underdrain**: If a bioretention cell has a storage layer with low native soil Ksat (clay soil) and the drain coefficient is 0, the storage fills permanently after a few storms. The LID becomes a pond, not a bioretention cell.

**Green roof on pervious subcatchment**: Green roofs (GR) should be placed on subcatchments representing impervious roof areas (high %imperv). Placing a GR on a 20%-impervious residential subcatchment produces odd hydrology.

**InitSat too high**: Starting a continuous simulation with InitSat=100 (fully saturated soil) means the first rainfall event produces maximum runoff regardless of antecedent conditions. For long continuous simulations, the effect washes out after a few days. For short event simulations, use InitSat=30-50 (typical field capacity range).

**Missing storage Ksat for infiltration-based LID**: Infiltration trenches and permeable pavement rely on water infiltrating into the native soil below the storage layer. If Storage Ksat = 0 (impermeable bottom), the LID fills up and overflows. Set Ksat to the native soil infiltration rate.

## Tools Reference

| Tool ID | Script | Purpose |
|---------|--------|---------|
| `create_lid_control` | `tools/s4_lid_setup/create_lid_control.py` | Define LID control physical parameters |
| `assign_lid_to_subcatchment` | `tools/s4_lid_setup/assign_lid_to_subcatchment.py` | Place LID on subcatchments |
| `validate_lid_params` | `tools/s4_lid_setup/validate_lid_params.py` | Validate parameter consistency |
