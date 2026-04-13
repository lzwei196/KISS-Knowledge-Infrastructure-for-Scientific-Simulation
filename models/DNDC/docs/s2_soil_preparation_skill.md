# S2 -- Soil Profile Preparation

## Purpose

Construct the soil input for DNDCv.CAN v9.6.0, either as parameters within the `.dnd` file
(homogeneous profile) or as an external `.spf` soil profile file (heterogeneous profile).
This skill covers deriving soil properties from global datasets (HWSD, SoilGrids), mapping
texture classes, configuring SOC pools, and setting water table / drainage boundary
conditions.

## Inputs

| Input | Source | Units / Format | Notes |
|---|---|---|---|
| Sand / silt / clay fractions | HWSD, SoilGrids, lab analysis | Mass fractions (0-1) or % | Needed per layer for heterogeneous profiles |
| Bulk density | HWSD, SoilGrids, lab analysis | g/cm3 | Typical range 0.8-1.8 |
| Soil organic carbon | HWSD, SoilGrids, lab analysis | kgC/kg_soil (for top 0-10 cm in `.dnd`) or per-layer in `.spf` | Surface SOC drives initial C pool partitioning |
| Soil pH | HWSD, SoilGrids, lab analysis | pH units (0-14) | Affects nitrification, denitrification, NH3 volatilization |
| Field capacity | Pedotransfer or measurement | water-filled pore space (wfps) fraction | Default ~0.841 for silt loam |
| Wilting point | Pedotransfer or measurement | wfps fraction | Default ~0.491 for silt loam |
| Porosity | Pedotransfer or measurement | v/v fraction | Default ~0.465 for silt loam |
| Hydraulic conductivity | Pedotransfer or measurement | m/hr | Saturated conductivity for each layer |
| Profile depth | Model requirement | m | Always 2.0 m for DNDCv.CAN |
| Number of layers | User design | Integer 1-10 | Heterogeneous profiles can have up to 10 layers |
| Landuse type | Site characterization | Integer code | (1) Upland crop field, (2) Rice paddy, etc. |
| Water table configuration | Site hydrology | 0 = dynamic water table ON, 1 = free drainage | Reversed logic -- see Traps |

## Outputs

| Output | Description |
|---|---|
| `.dnd` soil section | Lines encoding top-soil texture, SOC, bulk density, pH, and hydrological parameters |
| `.spf` file (optional) | External heterogeneous soil profile with per-layer properties for up to 10 layers |

## Procedure

### Step 1 -- Determine Profile Type

**Homogeneous profile (default):** The top-soil (0-10 cm) texture is applied uniformly through
the entire 2 m profile.  Simpler to set up but less realistic for sites with strong
horizon differentiation.

**Heterogeneous profile:** Up to 10 layers with individually specified thickness, density, SOC,
pH, texture, clay fraction, field capacity, wilting point, porosity, and hydraulic conductivity.
Saved as a `.spf` file and referenced from the `.dnd`.

Use heterogeneous profiles when:
- Measured soil profile data are available.
- The site has distinct A/B/C horizons with different textures.
- Accurate water table / tile drain simulations are needed.

### Step 2 -- Map Texture to DNDC Texture ID

DNDC uses an integer texture classification:

| ID | Texture Class |
|---|---|
| 1 | Sand |
| 2 | Loamy sand |
| 3 | Sandy loam |
| 4 | Silt loam |
| 5 | Loam |
| 6 | Sandy clay loam |
| 7 | Silty clay loam |
| 8 | Clay loam |
| 9 | Sandy clay |
| 10 | Silty clay |
| 11 | Clay |
| 12 | Organic |

To map from particle-size fractions, use the USDA texture triangle:
1. Plot sand% vs clay% on the triangle.
2. Read the texture class name.
3. Map the name to the DNDC ID above.

Alternatively, use thresholds:
- Clay > 40% and Sand < 45% --> Clay (11)
- Clay > 40% and Sand >= 45% --> Sandy clay (9)
- Clay 27-40% and Sand < 20% --> Silty clay (10)
- Clay 27-40% and Sand 20-45% --> Clay loam (8)
- And so on through the USDA classification rules.

### Step 3 -- Set Soil Hydraulic Properties

For each layer (or for the top-soil in homogeneous mode), define:

| Property | Symbol | Typical Silt Loam | How to Obtain |
|---|---|---|---|
| Bulk density | BD | 1.41 g/cm3 | Direct measurement or SoilGrids `bdod` |
| Field capacity | FC | 0.841 wfps | Pedotransfer (Saxton & Rawls) or lab |
| Wilting point | WP | 0.491 wfps | Pedotransfer or lab |
| Porosity | Por | 0.465 v/v | `1 - (BD / 2.65)` for mineral soils |
| Hydraulic conductivity | Ksat | 0.001 m/hr | Pedotransfer or constant-head test |
| Clay fraction | Clay | 0.12 | From texture analysis |

When using SoilGrids data, depths are reported at standard intervals (0-5, 5-15, 15-30,
30-60, 60-100, 100-200 cm).  Map these to DNDC layers by aggregating or splitting as needed.
The total profile must always be exactly **2.0 m**.

### Step 4 -- Configure SOC and Pool Partitioning

**Surface SOC** is entered in the `.dnd` as `kgC/kg_soil` for the 0-10 cm layer.  Typical
agricultural soils range from 0.005 to 0.06 kgC/kg_soil.

DNDC partitions total SOC into pools:

| Pool | Fraction (default) | C/N Ratio (default) | Description |
|---|---|---|---|
| Very labile litter | 0 | 5 | Fresh, easily decomposed residue |
| Labile litter | 0 | 25 | Moderately decomposable residue |
| Resistant litter | 0.01 | 100 | Recalcitrant residue |
| Humads | 0.0219 | 10 | Intermediate decomposition products |
| Humus | 0.9681 | 10 | Stable organic matter |
| Biochar | 0 | 500 | Pyrogenic carbon (v9.6.0 addition) |

The fractions must sum to 1.0.  For most agricultural sites, the default partitioning
(~97% humus, ~2% humads, ~1% resistant litter) is appropriate.  Override only when
site-specific C fractionation data are available.

**Depth of topsoil with uniform SOC content:** Default 0.2 m (plow layer).  Below this depth,
SOC decreases exponentially at the rate set by `SOC decrease rate below top soil` (default 2,
range 0.5-5.0; higher = faster decline with depth).

The `Bulk C/N` ratio (default ~10.0903) sets the overall soil organic matter C:N ratio.

**Re-define checkbox:** When enabled, the user can manually set pool fractions and C/N ratios
instead of using defaults.

### Step 5 -- Set Additional Soil Parameters

| Parameter | Default | Range | Notes |
|---|---|---|---|
| Initial N at surface soil | nitrate: 0.5, ammonium: 0.05 mg N/kg | -- | Initial mineral N concentration |
| Microbial activity index | 1 | 0-1 | Scales overall decomposition rate |
| Slope | 1 | 0-90 degrees | Affects runoff via SCS/MUSLE |
| Soil salinity index | 0 | 0-100 | For saline soils |
| Rain water collection index | 1 | -- | Ratio of effective catchment to field area |
| Bypass flow rate | 0 | 0-1 | Fraction of water bypassing the soil matrix |

Enable **Use SCS and MUSLE functions** for erosion and surface runoff calculations (checkbox).

### Step 6 -- Configure Water Table

The water table setting uses **reversed logic**:

| `.dnd` Value | Meaning |
|---|---|
| **0** | Dynamic water table is **ON**; bottom boundary is no-drain at 200 cm; tile drain parameters in TileDrain tab are active |
| **1** | Water table is **OFF**; free drainage at bottom boundary |

**Water Table Depth (m):** When dynamic WT is on, this sets the initial/boundary water table
depth.  Values <= 2.0 m mean the water table is active within the profile.  Values > 2.0 m
effectively mean no water table influence.

For tile-drained fields, set water table = 0 (ON) and configure tile drain parameters
(depth, spacing, radius, bedrock depth, keDrain factor) in the TileDrain and Model Parms tab.

### Step 7 -- Build the `.spf` File (Heterogeneous Profile)

The `.spf` is a plain text file with the following structure:

```
2.000000 9
1 0.050000 1.410000 0.017500 5.700000 4 0.120000 0.841000 0.491000 0.465000 0.001500 0.120000
2 0.100000 1.410000 0.017500 5.700000 4 0.120000 0.841000 0.491000 0.465000 0.001500 0.001000
3 0.200000 1.330000 0.016000 5.700000 4 0.120000 0.797000 0.479000 0.498000 0.001500 0.001000
...
```

Line 1: `<profile_depth_m> <number_of_layers>`

Subsequent lines (one per layer):
```
<layer_number> <thickness_m> <density_g_cm3> <SOC_kgC_kg> <pH> <texture_ID> <clay_frac> <field_cap_wfps> <wilting_pt_wfps> <porosity_v_v> <hydro_cond_m_hr> <additional_param>
```

Layer thicknesses must sum to the profile depth (2.0 m).

### Step 8 -- Save and Link

- Save the `.spf` file with a descriptive name (e.g., `SoyET-01.spf`).
- In the `.dnd` file, the heterogeneous profile radio button must be selected and the `.spf`
  path must be correctly referenced.
- Click **Accept / Save Changes** in the Soil tab before proceeding.

## Verification

- Verify layer thicknesses sum to exactly 2.0 m.
- Confirm SOC pool fractions sum to 1.0.
- Check that bulk density, field capacity, wilting point, and porosity are physically
  consistent (FC > WP; porosity > FC; BD consistent with porosity).
- For heterogeneous profiles, open the `.spf` in a text editor and verify the number of
  data lines matches the declared layer count.
- Run a 1-year simulation and inspect initial soil carbon output to confirm SOC was
  initialized correctly.

## Traps

| Trap | Consequence | Prevention |
|---|---|---|
| **Water table logic is reversed** (0=ON, 1=OFF) | Setting 1 thinking it enables water table actually disables it | Memorize: 0=Yes, 1=No for water table |
| Layer thicknesses do not sum to 2.0 m | Model may crash or produce incorrect layer depths | Compute sum explicitly before saving |
| SOC pool fractions do not sum to 1.0 | Unaccounted carbon; mass balance errors | Verify sum after editing fractions |
| Editing heterogeneous profile resets SOC fractions to default | User's custom SOC partitioning is silently overwritten | Re-enter SOC fractions after every edit to the heterogeneous soil tab |
| SOC in wrong units (% instead of kgC/kg) | 100x overestimate of soil carbon | 1% SOC = 0.01 kgC/kg; convert explicitly |
| Porosity < field capacity | Physically impossible; model may produce negative air-filled porosity | Ensure porosity > FC > WP |
| Forgetting to save `.spf` file | Model reads stale or missing profile data | Always save the `.spf` even if no changes were made (known GUI requirement) |
| Texture ID out of range (0 or >12) | Undefined texture class; unpredictable hydraulic properties | Use only IDs 1-12 |
| Very thin layers (< 1 cm) with Dynamic Layer Depth enabled | Simulation may crash (known issue in v9.5.6+) | Keep minimum layer thickness >= 2 cm |

## Example

Creating a heterogeneous `.spf` for a silt loam site using SoilGrids data:

```python
# SoilGrids depths: 0-5, 5-15, 15-30, 30-60, 60-100, 100-200 cm
# Map to 9 DNDC layers summing to 2.0 m

layers = [
    # (thickness_m, BD, SOC_kgC_kg, pH, texID, clay, FC, WP, porosity, Ksat_m_hr)
    (0.05,  1.41, 0.0175, 5.7, 4, 0.12, 0.841, 0.491, 0.465, 0.0015),  # 0-5 cm
    (0.10,  1.41, 0.0175, 5.7, 4, 0.12, 0.841, 0.491, 0.465, 0.0015),  # 5-15 cm
    (0.20,  1.33, 0.0160, 5.7, 4, 0.12, 0.797, 0.479, 0.498, 0.0015),  # 15-35 cm
    (0.10,  1.36, 0.0140, 5.7, 4, 0.12, 0.806, 0.501, 0.486, 0.0015),  # 35-45 cm
    (0.10,  1.36, 0.0140, 5.7, 4, 0.12, 0.806, 0.501, 0.486, 0.0015),  # 45-55 cm
    (0.30,  1.36, 0.0110, 5.7, 4, 0.12, 0.806, 0.501, 0.486, 0.0015),  # 55-85 cm
    (0.30,  1.31, 0.0060, 5.7, 4, 0.12, 0.772, 0.436, 0.505, 0.0015),  # 85-115 cm
    (0.35,  1.31, 0.0030, 5.7, 4, 0.12, 0.772, 0.436, 0.505, 0.0015),  # 115-150 cm
    (0.50,  1.31, 0.0010, 5.7, 4, 0.12, 0.772, 0.436, 0.505, 0.0015),  # 150-200 cm
]

total = sum(l[0] for l in layers)
assert abs(total - 2.0) < 0.001, f"Layers sum to {total}, must be 2.0"

with open("site_profile.spf", "w") as f:
    f.write(f"2.000000 {len(layers)}\n")
    for i, L in enumerate(layers, 1):
        f.write(f"{i} {L[0]:.6f} {L[1]:.6f} {L[2]:.6f} {L[3]:.6f} "
                f"{L[4]} {L[5]:.6f} {L[6]:.6f} {L[7]:.6f} "
                f"{L[8]:.6f} {L[9]:.6f} 0.120000\n")
```

This produces a 9-layer profile totaling exactly 2.0 m with progressively decreasing SOC
down the profile.
