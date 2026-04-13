# Stage 4: Water Demand and Abstraction Configuration

## Purpose

Configure human water use in PCR-GLOBWB 2, including irrigation, domestic, industrial, and livestock water demand. This stage also covers groundwater abstraction limits, desalination, and water allocation zones.

## Inputs

| Input | Format | Unit | Description |
|-------|--------|------|-------------|
| Irrigation area | NetCDF | hectares | Historical irrigated area time series |
| Irrigation efficiency | NetCDF | fraction (0-1) | Conveyance + application efficiency |
| Domestic water demand | NetCDF | m/day | Per-cell domestic demand depth |
| Industry water demand | NetCDF | m/day | Per-cell industrial demand depth |
| Livestock water demand | NetCDF | m/day | Per-cell livestock demand depth |
| Desalination supply | NetCDF | m/day | Maximum desalination capacity |
| Allocation zones | NetCDF | integer IDs | Spatial zones for water allocation |
| Pumping capacity | NetCDF | billion m3/year | Regional groundwater abstraction limits |

## Outputs

| Output | Variable | Unit | Description |
|--------|----------|------|-------------|
| Actual irrigation abstraction | irrPaddyWaterWithdrawal, irrNonPaddyWaterWithdrawal | m/day | Realized irrigation withdrawal |
| Domestic withdrawal | domesticWaterWithdrawal | m/day | Realized domestic withdrawal |
| GW abstraction | totalGroundwaterAbstraction | m/day | Total groundwater pumping |
| Surface water abstraction | surfaceWaterAbstraction | m/day | Total surface water withdrawal |

## Procedure

### Step 1: Enable Water Demand Components

In `[landSurfaceOptions]`:
```ini
includeIrrigation = True
includeDomesticWaterDemand = True
includeIndustryWaterDemand = True
includeLivestockWaterDemand = True
```

### Step 2: Configure Demand Data Files

```ini
# Water demand files (unit MUST be m/day - depth over cell area)
domesticWaterDemandFile  = global_05min/waterUse/waterDemand/domestic/domestic_water_demand.nc
industryWaterDemandFile  = global_05min/waterUse/waterDemand/industry/industry_water_demand.nc
livestockWaterDemandFile = global_05min/waterUse/waterDemand/livestock/livestock_water_demand.nc
```

### Step 3: Configure Source Partitioning

PCR-GLOBWB allocates demand between surface water and groundwater:
```ini
# Surface water fraction for irrigation (from Siebert's GMIA)
irrigationSurfaceWaterAbstractionFractionData = .../AEI_SWFRAC.nc

# Thresholds for source preference
treshold_to_maximize_irrigation_surface_water = 0.50
treshold_to_minimize_fossil_groundwater_irrigation = 0.70

# Non-irrigation surface water fraction (from McDonald, 2014)
maximumNonIrrigationSurfaceWaterAbstractionFractionData = .../max_city_sw_fraction.nc
```

### Step 4: Configure Groundwater Limits

In `[groundwaterOptions]`:
```ini
limitFossilGroundWaterAbstraction = True
estimateOfRenewableGroundwaterCapacity = 0.0
maximumDailyGroundwaterAbstraction = 0.050        # m/day
maximumDailyFossilGroundwaterAbstraction = 0.020  # m/day
pumpingCapacityNC = .../regional_abstraction_limit.nc
```

### Step 5: Natural-only Runs

For runs without human water use:
```ini
includeIrrigation = False
includeDomesticWaterDemand = False
includeIndustryWaterDemand = False
includeLivestockWaterDemand = False
```

## Verification

- [ ] Water demand files have unit m/day (depth, NOT volume)
- [ ] `irrigationEfficiency` is fraction 0-1 (1.0 = no loss)
- [ ] Allocation zone IDs cover entire landmask
- [ ] Total abstraction < total available water (no persistent deficits)
- [ ] Surface water + groundwater fractions sum to ~1.0

## Traps

| Trap ID | Symptom | Root Cause | Fix |
|---------|---------|-----------|-----|
| dt_005 | Rivers run dry, excessive abstraction | Water demand in mm/day or m3/day instead of m/day | Convert to m/day depth |
| dt_006 | GW depletion too fast | GW abstraction in wrong units | Ensure m/day depth over cell |
| - | No irrigation occurring | `includeIrrigation = False` | Set to `True` |
| - | 100% irrigation efficiency assumed | `irrigationEfficiency` not set | Provide efficiency map (typical 0.4-0.7) |

## Example

```ini
# Natural run (no human influence)
[landSurfaceOptions]
includeIrrigation = False
includeDomesticWaterDemand = False
includeIndustryWaterDemand = False
includeLivestockWaterDemand = False

# Non-natural run (with human influence)
[landSurfaceOptions]
includeIrrigation = True
includeDomesticWaterDemand = True
includeIndustryWaterDemand = True
includeLivestockWaterDemand = True
domesticWaterDemandFile = global_05min/waterUse/waterDemand/domestic/domestic_water_demand_version_april_2015.nc
```
