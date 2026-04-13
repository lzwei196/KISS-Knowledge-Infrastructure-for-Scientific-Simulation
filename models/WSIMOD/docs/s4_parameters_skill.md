# Stage 4: Parameter Configuration

## Purpose

Set physical parameters for each WSIMOD node: surface areas, storage capacities,
residence times, pollutant loads, treatment efficiencies, and soil properties.
Incorrect parameters produce silent errors because the model runs regardless.

## Inputs

| Input                | Format   | Source                     | Notes                        |
|----------------------|----------|----------------------------|------------------------------|
| Catchment area       | Number   | GIS/satellite data         | Must convert to m²           |
| Soil properties      | Dict     | HWSD/field surveys         | Depth in m, FC/WP fractions  |
| Land use fractions   | Dict     | MODIS/Corine/surveys       | Must sum to 1.0              |
| Sewer capacity       | Number   | Utility records            | m³/d (NOT ML/d)              |
| Demand per capita    | Number   | Census + utility data      | ML/person/d                  |
| Treatment params     | Dict     | Facility design specs      | Throughput, efficiency        |
| Pollutant loads      | Dict     | Literature/monitoring      | kg/timestep per surface      |

## Outputs

| Output              | Format   | Destination               | Notes                          |
|---------------------|----------|---------------------------|--------------------------------|
| Node config dicts   | List     | `model.add_nodes()`       | Ready for model construction   |
| Surface configs     | List     | Within Land node dict     | Per-surface parameters         |
| Arc configs         | List     | `model.add_arcs()`        | Capacity and preference        |

## Procedure

1. **Convert catchment area to m²**:
   ```python
   from wsimod.core.constants import KM2_TO_M2, HA_TO_M2
   area_m2 = area_km2 * KM2_TO_M2  # 1e6
   ```

2. **Configure Land surfaces**:
   ```python
   surfaces = [
       {"type_": "ImperviousSurface", "surface": "urban",
        "area": area_m2 * 0.3,  # 30% urban
        "pollutant_load": {"phosphate": 1e-7}},
       {"type_": "PerviousSurface", "surface": "rural",
        "area": area_m2 * 0.7,  # 70% rural
        "depth": 0.5,  # m (soil depth)
        "pollutant_load": {"phosphate": 1e-7}},
   ]
   ```

3. **Configure storage nodes**:
   ```python
   gw = {"type_": "Groundwater", "name": "gw",
         "area": area_m2,
         "capacity": area_m2 * soil_depth * field_capacity}
   ```

4. **Configure Sewer** (capacity in m³/d, NOT ML/d):
   ```python
   sewer = {"type_": "Sewer", "name": "sewer",
            "capacity": urban_area_m2 * 0.001}  # ~1 mm/d design storm
   ```

5. **Configure Demand node**:
   ```python
   demand = {"type_": "Demand", "name": "demand",
             "per_capita": 0.00015,  # ML/person/d (~150 L/d)
             "population": 50000}
   ```

6. **Configure Treatment Works**:
   ```python
   wwtw = {"type_": "WWTW", "name": "wwtw",
           "treatment_throughput": 10.0,  # ML/d
           "stormwater_storage_capacity": 2.0}  # ML
   ```

7. **Configure arcs with capacity and preference**:
   ```python
   arc = {"type_": "Arc", "name": "supply_pipe",
          "in_port": "fwtw", "out_port": "demand",
          "capacity": 15.0,  # ML/d
          "preference": 1.0}  # higher = preferred route
   ```

## Verification

- [ ] All areas in m² (not km² or ha)
- [ ] Soil depth in m (not mm)
- [ ] Sewer capacity in m³/d (not ML/d)
- [ ] Land use fractions sum to ~1.0
- [ ] Storage capacity > 0 for all storage nodes
- [ ] Pollutant loads are physically reasonable (1e-8 to 1e-5 kg/timestep typical)
- [ ] Per-capita demand ~0.00010 to 0.00020 ML/person/d (100–200 L/d)

## Traps

| Trap   | Symptom                                    | Fix                                        |
|--------|--------------------------------------------|--------------------------------------------|
| dt_008 | Runoff volume 1e6× too high or too low     | Area in km² not m² — multiply by 1e6      |
| dt_006 | No CSO events despite heavy rain           | Sewer capacity in ML not m³ — 1000× wrong |
| dt_011 | Soil fills instantly or never              | Depth in mm not m — multiply by 1e-3      |
| dt_012 | Nutrient export 1000× off                  | Load in g/m² not kg/km² — convert units   |
| dt_002 | Mass balance violation in storage nodes     | Mixing ML and m³ units                     |

## Example

```python
from wsimod.core.constants import KM2_TO_M2, MM_TO_M

# Catchment: 50 km², 30% urban, loam soil
area_m2 = 50.0 * KM2_TO_M2  # 50e6 m²
soil_depth = 500 * MM_TO_M   # 0.5 m

nodes = [
    {"type_": "Land", "name": "land",
     "data_input_dict": land_inputs,
     "surfaces": [
         {"type_": "ImperviousSurface", "surface": "urban",
          "area": area_m2 * 0.3, "pollutant_load": {"phosphate": 1e-7}},
         {"type_": "PerviousSurface", "surface": "rural",
          "area": area_m2 * 0.7, "depth": soil_depth,
          "pollutant_load": {"phosphate": 1e-7}},
     ]},
    {"type_": "Groundwater", "name": "gw",
     "area": area_m2, "capacity": area_m2 * soil_depth * 0.3},
    {"type_": "Sewer", "name": "sewer",
     "capacity": area_m2 * 0.3 * 0.001},  # m³/d
    {"type_": "Node", "name": "river"},
    {"type_": "Waste", "name": "outlet"},
]
```
