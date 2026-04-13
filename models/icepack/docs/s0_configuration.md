# Stage 0: Configuration

## Purpose

Define the glacier simulation setup: choose glacier name/location, model type
(IceShelf, IceStream, ShallowIce, HybridModel), time period, mesh resolution,
and data sources. This stage produces a Python configuration dictionary or script
that drives all subsequent stages.

## Inputs

| Parameter | Type | Units | Example | Notes |
|-----------|------|-------|---------|-------|
| glacier_name | str | — | "larsen-2019" | Must match icepack.datasets.get_glacier_names() or provide custom outline |
| model_type | str | — | "ice_shelf" | One of: ice_shelf, ice_stream, shallow_ice, hybrid |
| region | str | — | "antarctica" | For dataset selection |
| start_year | int | — | 2015 | Observation period start |
| end_year | int | — | 2020 | Observation period end |
| dt | float | years | 0.5 | Timestep for prognostic solver |
| num_steps | int | — | 100 | Number of time steps |
| mesh_resolution | float | meters | 5000 | Characteristic element length |
| temperature | float | Kelvin | 254.15 | Bulk ice temperature for rate factor |
| element_degree | int | — | 2 | Polynomial degree for FEM spaces |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| config dict | Python dict / JSON | Complete simulation configuration |
| glacier outline | GeoJSON | Outline for mesh generation |

## Procedure

1. **Select glacier**: Choose from built-in list or provide custom GeoJSON outline
2. **Choose physics model**:
   - IceShelf: floating ice only (no bed interaction)
   - IceStream: fast-flowing grounded ice (SSA + basal friction)
   - ShallowIce: slow-flowing grounded ice (SIA)
   - HybridModel: full 3D velocity (extruded mesh required)
3. **Set temperature**: Typical values −30°C to 0°C (243 to 273 K)
4. **Set mesh resolution**: 500 m (high-res local) to 10 km (continental)
5. **Set timestep**: dt should satisfy CFL; typical 0.01–1.0 years
6. **Validate**: Ensure all required fields for chosen model type are available

## Verification

- [ ] glacier_name is valid or custom GeoJSON exists
- [ ] model_type matches available physics models
- [ ] Temperature is in Kelvin (not Celsius) — common mistake
- [ ] Mesh resolution is in meters, not km
- [ ] dt is in years, not seconds or days

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Temperature in °C instead of K | rate_factor returns ~0 or infinity | Add 273.15 to convert °C → K |
| dt too large | Negative thickness, oscillations | Reduce dt; typical < 1 yr |
| Wrong model for physics | Solver divergence | IceShelf for floating, IceStream for grounded fast |
| Mesh too coarse | Poor representation of geometry | Reduce lcar / increase nx,ny |

## Example

```python
config = {
    "glacier_name": "larsen-2019",
    "model_type": "ice_shelf",
    "region": "antarctica",
    "temperature": 254.15,  # -19°C in Kelvin
    "dt": 0.5,              # years
    "num_steps": 100,
    "mesh_params": {
        "type": "geojson",
        "geojson_path": "larsen.geojson",
        "lcar": 5000,  # 5 km mesh resolution
    },
    "dirichlet_ids": [1],
    "element_degree": 2,
}
```
