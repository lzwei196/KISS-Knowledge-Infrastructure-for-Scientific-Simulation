# S5 -- Output Parsing and Analysis

## Purpose

Parse DNDCv.CAN v9.6.0 output files, extract key variables (crop yield, N2O emissions, N
leaching, SOC change, water balance), process daily output for temporal analysis, and create
validation plots.  This skill covers the structure and content of all major output files
produced by the model.

## Inputs

| Input | Source | Format | Notes |
|---|---|---|---|
| Summary output files | `Result/Record/Site/` or `Result/Record/Batch/` | Tab/space-delimited text | One file per output category; multi-year data appended |
| Daily output files | Same directories | Tab/space-delimited text | Generated only when `Record daily results = 1` |
| Observed data (optional) | Field measurements / literature | CSV or similar | For validation comparisons |

## Outputs

| Output | Description |
|---|---|
| Extracted time series | Annual or daily values of key variables in analysis-ready format |
| Validation statistics | RMSE, bias, R-squared, Nash-Sutcliffe efficiency |
| Diagnostic plots | Time series, scatter plots, water balance diagrams |

## Procedure

### Step 1 -- Locate Output Files

DNDCv.CAN aggregates multi-year output into single files (unlike older DNDC95 which created
per-year files).

**Single-site runs:** `DNDC/Result/Record/Site/`
**Batch runs:** `DNDC/Result/Record/Batch/`
**Intermediate/spinup files:** `DNDC/Result/Inter/`

### Step 2 -- Parse Summary Files

Summary files contain annual aggregated results.  Key files and their contents:

#### Summary_SoilClimate

Annual soil climate summary including:
- Annual precipitation (cm)
- Annual mean air temperature (C)
- Annual mean soil temperature by depth (C)
- Annual evapotranspiration (cm)
- Annual drainage / percolation (cm)
- Snow accumulation

#### Summary_CropYield

The primary crop production output:

| Variable | Units | Description |
|---|---|---|
| Grain yield | kgC/ha | Carbon in harvested grain |
| Leaf biomass | kgC/ha | Carbon in leaf at harvest |
| Stem biomass | kgC/ha | Carbon in stem at harvest |
| Root biomass | kgC/ha | Carbon in root at harvest |
| Total aboveground biomass | kgC/ha | Grain + leaf + stem |
| Crop N uptake | kgN/ha | Total N absorbed by crop |

**Unit conversion for yield reporting:**
```
Yield_kgDM_ha = Yield_kgC_ha / C_fraction
```
Where C_fraction is typically:
- Grain: ~0.45 (corn grain is ~45% C)
- Whole plant: ~0.40-0.45

To convert to common agronomic units:
```
Yield_bu_ac_corn = (Yield_kgC_ha / 0.45) * (1 / 56 * 2.2046) * (1 / 2.471)
```
Or more simply:
```
Yield_tonnes_ha = Yield_kgC_ha / 0.45 / 1000
```

#### Summary_GHG (Greenhouse Gas Emissions)

| Variable | Units | Description |
|---|---|---|
| N2O emissions | kgN/ha/yr | Annual nitrous oxide flux (as N) |
| NO emissions | kgN/ha/yr | Nitric oxide |
| N2 emissions | kgN/ha/yr | Dinitrogen from denitrification |
| NH3 volatilization | kgN/ha/yr | Ammonia losses |
| CO2 soil respiration | kgC/ha/yr | Heterotrophic + autotrophic |
| CH4 flux | kgC/ha/yr | Methane (net; positive = emission) |

#### Summary_WaterBalance

| Variable | Units | Description |
|---|---|---|
| Precipitation | cm/yr | Total input |
| Irrigation | cm/yr | Applied water |
| Evaporation | cm/yr | Soil surface evaporation |
| Transpiration | cm/yr | Crop water use |
| Runoff | cm/yr | Surface runoff |
| Drainage | cm/yr | Bottom drainage + tile flow |
| Tile drain flow | cm/yr | If tile drains are active |
| Change in soil water storage | cm/yr | Should close the balance |

#### Summary_NBalance

| Variable | Units | Description |
|---|---|---|
| N fertilizer input | kgN/ha/yr | Applied N |
| N fixation | kgN/ha/yr | Biological fixation |
| N deposition | kgN/ha/yr | Atmospheric deposition |
| Crop N uptake | kgN/ha/yr | Removed in harvest |
| N leaching | kgN/ha/yr | NO3 leached below root zone or to tiles |
| Gaseous N losses | kgN/ha/yr | N2O + NO + N2 + NH3 |
| Change in soil N | kgN/ha/yr | Net soil N pool change |

#### Summary_SOC

| Variable | Units | Description |
|---|---|---|
| Total SOC | kgC/ha | End-of-year soil organic carbon stock |
| SOC change | kgC/ha/yr | Annual change (positive = sequestration) |
| Litter C input | kgC/ha/yr | From crop residue and roots |
| Decomposition C loss | kgC/ha/yr | CO2 from organic matter decay |

### Step 3 -- Parse Daily Output Files

Daily files provide sub-annual dynamics for detailed analysis.  Only generated when
`Record daily results = 1`.

#### Day_Climate1

Daily climate as read and processed by the model:
- Jday, air temperature (max, min, mean), precipitation, radiation, wind, humidity
- Useful for verifying that climate input was parsed correctly.

#### Day_Crop1

Daily crop state variables:
- Plant Growth Index (PGI, 0-1)
- Leaf Area Index (LAI, m2/m2)
- Biomass accumulation (grain, leaf, stem, root in kgC/ha)
- N uptake
- Water stress index
- Thermal degree days accumulated

#### Day_SoilC1

Daily soil carbon dynamics:
- SOC by pool (litter, humads, humus)
- Daily decomposition rates
- CO2 flux from soil

#### Day_SoilN1

Daily soil nitrogen dynamics:
- NH4 and NO3 concentrations by layer
- Nitrification rate
- Denitrification rate
- N2O, NO, N2 daily fluxes

#### Day_SoilWater1

Daily soil water status:
- Water-filled pore space (WFPS) by layer
- Water table depth
- Drainage volume
- Evapotranspiration components

### Step 4 -- Extract Key Variables

Example Python code for parsing a summary file:

```python
import pandas as pd

def parse_dndc_summary(filepath, skip_header_lines=1):
    """Parse a DNDC summary output file into a DataFrame.

    DNDC summary files typically have a header line followed by
    space/tab delimited data.  Column names may vary by output type.
    """
    df = pd.read_csv(filepath, sep=r'\s+', skiprows=skip_header_lines,
                     header=0, engine='python')
    return df

# Parse crop yield
yield_df = parse_dndc_summary("Result/Record/Site/Summary_CropYield")

# Convert grain yield from kgC/ha to tonnes DM/ha
yield_df["Grain_t_ha"] = yield_df["Grain_kgC_ha"] / 0.45 / 1000

# Parse GHG emissions
ghg_df = parse_dndc_summary("Result/Record/Site/Summary_GHG")

# Extract annual N2O
n2o_annual = ghg_df["N2O_kgN_ha"]
print(f"Mean annual N2O: {n2o_annual.mean():.2f} kgN/ha/yr")
```

**Note:** Column names in actual DNDC output may differ from those shown here.  Always
inspect the header line of each output file to determine exact column names before parsing.
Some output files may not have fully defined units in headers (known issue).

### Step 5 -- Water Balance Closure Check

A key diagnostic is verifying that the water balance closes:

```
P + I = ET + R + D + dS
```

Where:
- P = Precipitation
- I = Irrigation
- ET = Evapotranspiration (Evaporation + Transpiration)
- R = Runoff
- D = Drainage (bottom + tile)
- dS = Change in soil water storage

```python
wb = parse_dndc_summary("Result/Record/Site/Summary_WaterBalance")

wb["Balance_residual"] = (
    wb["Precipitation"] + wb["Irrigation"]
    - wb["Evaporation"] - wb["Transpiration"]
    - wb["Runoff"] - wb["Drainage"]
    - wb["DeltaStorage"]
)

# Residual should be < 1% of precipitation
for i, row in wb.iterrows():
    pct_residual = abs(row["Balance_residual"]) / row["Precipitation"] * 100
    print(f"Year {i+1}: residual = {row['Balance_residual']:.2f} cm "
          f"({pct_residual:.1f}% of precip)")
```

### Step 6 -- Create Validation Plots

#### Time Series Plot (Simulated vs. Observed Yield)

```python
import matplotlib.pyplot as plt

years = range(2018, 2021)
sim_yield = [8.5, 3.2, 9.1]   # tonnes DM/ha from DNDC
obs_yield = [8.2, 3.5, 8.8]   # field observations

fig, ax = plt.subplots(figsize=(8, 5))
ax.plot(years, sim_yield, 'b-o', label='DNDC simulated')
ax.plot(years, obs_yield, 'r-s', label='Observed')
ax.set_xlabel('Year')
ax.set_ylabel('Grain yield (t DM/ha)')
ax.set_title('DNDC Yield Validation')
ax.legend()
plt.tight_layout()
plt.savefig('yield_validation.png', dpi=150)
```

#### Daily N2O Flux Comparison

```python
# Parse daily soil N output
day_n = pd.read_csv("Result/Record/Site/Day_SoilN1", sep=r'\s+',
                     skiprows=1, header=0, engine='python')

fig, ax = plt.subplots(figsize=(12, 4))
ax.plot(day_n["Jday"], day_n["N2O_gN_ha_day"], 'b-', alpha=0.7,
        label='DNDC daily N2O')
ax.set_xlabel('Julian Day')
ax.set_ylabel('N2O flux (gN/ha/day)')
ax.set_title('Daily N2O Emissions')
ax.legend()
plt.tight_layout()
plt.savefig('daily_n2o.png', dpi=150)
```

#### Scatter Plot with Statistics

```python
import numpy as np

sim = np.array(sim_yield)
obs = np.array(obs_yield)

rmse = np.sqrt(np.mean((sim - obs)**2))
bias = np.mean(sim - obs)
r2 = np.corrcoef(sim, obs)[0, 1]**2

fig, ax = plt.subplots(figsize=(6, 6))
ax.scatter(obs, sim, s=60, c='blue', edgecolors='black')
lims = [min(obs.min(), sim.min()) * 0.9, max(obs.max(), sim.max()) * 1.1]
ax.plot(lims, lims, 'k--', alpha=0.5, label='1:1 line')
ax.set_xlim(lims)
ax.set_ylim(lims)
ax.set_xlabel('Observed (t DM/ha)')
ax.set_ylabel('Simulated (t DM/ha)')
ax.set_title(f'Yield: RMSE={rmse:.2f}, Bias={bias:.2f}, R2={r2:.2f}')
ax.legend()
plt.tight_layout()
plt.savefig('yield_scatter.png', dpi=150)
```

### Step 7 -- SOC Trend Analysis

For long-term simulations, track SOC change to assess carbon sequestration:

```python
soc = parse_dndc_summary("Result/Record/Site/Summary_SOC")

# Annual SOC change
soc_change = soc["SOC_kgC_ha"].diff()

# Cumulative change from baseline
soc_cumulative = soc["SOC_kgC_ha"] - soc["SOC_kgC_ha"].iloc[0]

print(f"Initial SOC: {soc['SOC_kgC_ha'].iloc[0]:.0f} kgC/ha")
print(f"Final SOC:   {soc['SOC_kgC_ha'].iloc[-1]:.0f} kgC/ha")
print(f"Total change: {soc_cumulative.iloc[-1]:.0f} kgC/ha over {len(soc)} years")
print(f"Mean annual change: {soc_change.mean():.1f} kgC/ha/yr")
```

## Verification

- All summary files contain the expected number of year-rows (matching simulation years).
- Water balance residual is < 1% of annual precipitation.
- Crop yield values are within agronomically plausible ranges:
  - Corn grain: 3,000-8,000 kgC/ha (6.7-17.8 t DM/ha)
  - Soybean grain: 800-2,500 kgC/ha (1.8-5.6 t DM/ha)
  - Winter wheat grain: 1,500-4,500 kgC/ha
- N2O emissions: 0.5-10 kgN/ha/yr for fertilized cropland (higher in wet years or with
  heavy N application).
- N leaching: 5-80 kgN/ha/yr depending on soil type, drainage, and N application rate.
- SOC change: typically -500 to +500 kgC/ha/yr for cropland.

## Traps

| Trap | Consequence | Prevention |
|---|---|---|
| **Yield reported in kgC/ha, not kgDM/ha or bu/ac** | Apparent yield is ~45% of expected value | Always convert: divide kgC by C fraction (~0.45) to get dry matter |
| Column names not matching assumed names | Parser reads wrong columns or crashes | Inspect the actual header line of each file before writing the parser |
| Multi-year data in single file vs. per-year | Parser expects wrong file structure | DNDCv.CAN aggregates years into single files; old DNDC95 scripts will break |
| Daily output not generated | Parser fails to find Day_* files | Verify `Record daily results = 1` was set in S0 configuration |
| Missing or incomplete last year | Simulation crashed mid-year; partial data | Check that row count matches expected years; rerun if incomplete |
| Units not labeled in output headers | Wrong unit assumptions in analysis | Cross-reference with this skill document and the user guide |
| Confusing N2O (kgN/ha) with N2O (kgN2O/ha) | 1.57x error in GHG reporting | DNDC reports N2O as kgN/ha; multiply by 44/28 = 1.571 to get kgN2O/ha |
| SOC trend dominated by spinup artifact | First years show unrealistic SOC change | Exclude spinup years from trend analysis; use only post-equilibration years |
| Comparing simulation years to wrong calendar years | Misaligned validation | Year 1 in DNDC = first climate file year; map explicitly |
| Tile drain N leaching not in main leaching total | Underestimated N losses | Check if tile N is reported separately and add to total leaching |

## Example

Complete analysis workflow for a 3-year corn-soybean-corn simulation:

```python
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

output_dir = "/home/user/DNDC/Result/Record/Site/"

# 1. Parse all summary files
yield_data = parse_dndc_summary(f"{output_dir}/Summary_CropYield")
ghg_data   = parse_dndc_summary(f"{output_dir}/Summary_GHG")
water_data = parse_dndc_summary(f"{output_dir}/Summary_WaterBalance")
soc_data   = parse_dndc_summary(f"{output_dir}/Summary_SOC")

# 2. Convert yield to standard units
yield_data["Grain_t_DM_ha"] = yield_data["Grain_kgC_ha"] / 0.45 / 1000

# 3. Convert N2O to CO2-equivalent (GWP100 = 298)
ghg_data["N2O_kgCO2eq_ha"] = ghg_data["N2O_kgN_ha"] * (44/28) * 298

# 4. Check water balance closure
water_data["Residual_cm"] = (
    water_data["Precip_cm"] + water_data["Irrig_cm"]
    - water_data["ET_cm"] - water_data["Runoff_cm"]
    - water_data["Drain_cm"] - water_data["dStorage_cm"]
)

# 5. Print summary report
for yr in range(len(yield_data)):
    print(f"Year {yr+1}:")
    print(f"  Grain yield:  {yield_data['Grain_t_DM_ha'].iloc[yr]:.1f} t DM/ha")
    print(f"  N2O emission: {ghg_data['N2O_kgN_ha'].iloc[yr]:.2f} kgN/ha")
    print(f"  N leaching:   {ghg_data['Nleach_kgN_ha'].iloc[yr]:.1f} kgN/ha")
    print(f"  SOC change:   {soc_data['SOC_kgC_ha'].diff().iloc[yr]:+.0f} kgC/ha")
    print(f"  Water bal:    {water_data['Residual_cm'].iloc[yr]:.3f} cm residual")
    print()
```

Expected output for a well-calibrated corn year in eastern Canada:
```
Year 1:
  Grain yield:  10.2 t DM/ha
  N2O emission: 2.15 kgN/ha
  N leaching:   25.3 kgN/ha
  SOC change:   +120 kgC/ha
  Water bal:    0.002 cm residual
```
