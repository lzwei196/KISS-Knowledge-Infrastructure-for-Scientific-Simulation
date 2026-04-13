# S5: Terrain Constraints & Economic Suitability (Modules V–VI) Skill Document

## Purpose

**Module V** applies terrain-based yield reduction (fc5) using the Modified Fournier
Index (erosion proxy) crossed with slope class. **Module VI** evaluates economic
viability through net revenue analysis based on production costs and farm-gate prices.

---

## Module V: Terrain Constraints

### Inputs

| Variable | Type | Shape | Unit | Source |
|----------|------|-------|------|--------|
| `soil_yield_rain` | NumPy | (H,W) | kg/ha | Module IV |
| `soil_yield_irr` | NumPy | (H,W) | kg/ha | Module IV |
| `precipitation` | NumPy | (H,W,12) | mm/day | S0 |
| `slope` | NumPy | (H,W) | percent (%) | GeoTIFF |
| Terrain reduction Excel (rain) | .xlsx | — | — | User |
| Terrain reduction Excel (irr) | .xlsx | — | — | User |

### Outputs

| Variable | Shape | Unit | Description |
|----------|-------|------|-------------|
| `terrain_yield_rain` | (H,W) | kg/ha | Terrain-constrained yield (rainfed) |
| `terrain_yield_irr` | (H,W) | kg/ha | Terrain-constrained yield (irrigated) |
| `fc5_rain` | (H,W) | 0–1 | Terrain constraint factor (rainfed) |
| `fc5_irr` | (H,W) | 0–1 | Terrain constraint factor (irrigated) |
| `fournier_index` | (H,W) | unitless | Modified Fournier Index |

### Procedure

```python
from pyaez import TerrainConstraints

tc = TerrainConstraints.TerrainConstraints()
tc.importTerrainReductionSheet(irr_file_path='maiz_terrain_constraints_irr.xlsx',
                                rain_file_path='maiz_terrain_constraints_rain.xlsx')
tc.setClimateTerrainData(precipitation, slope)
tc.calculateFI()

# Apply constraints (separately for rainfed/irrigated)
terrain_yield_rain = tc.applyTerrainConstraints(soil_yield_rain, 'R')
fc5_rain = tc.getTerrainReductionFactor()
terrain_yield_irr = tc.applyTerrainConstraints(soil_yield_irr, 'I')
fc5_irr = tc.getTerrainReductionFactor()
fi = tc.getFI()
```

### Key Algorithm: Modified Fournier Index

```
FI = Σ(Pi²) / ΣPi × 12
```
Where Pi = monthly precipitation. Higher FI indicates greater erosion risk.
Combined with slope, this determines the terrain reduction factor.

### Verification (Module V)

1. **FI range**: Tropical humid areas: FI > 200; arid: FI < 50
2. **fc5 vs slope**: Flat areas (slope < 5%) should have fc5 ≈ 1.0
3. **Slope units**: Must be percent, not degrees (45° = 100%)
4. **Precipitation**: Must be monthly totals for FI calculation

### Traps (Module V)

| Trap | Symptom | Fix |
|------|---------|-----|
| Slope in degrees | fc5 too low for gentle slopes | `slope_pct = tan(radians(degrees)) * 100` |
| Precip in mm/day not mm/month | FI way too low | Multiply by days in month |
| Excel table mismatch | Out-of-range FI/slope → fc5=0 | Extend table ranges |

---

## Module VI: Economic Suitability

### Inputs

| Variable | Type | Unit | Source |
|----------|------|------|--------|
| `terrain_yield_rain` | NumPy (H,W) | kg/ha or ton/ha | Module V |
| `terrain_yield_irr` | NumPy (H,W) | kg/ha or ton/ha | Module V |
| `crop_cost` | 1D array | currency/ha | User (4+ data points) |
| `crop_yield` | 1D array | ton/ha | User (matching cost) |
| `farm_price` | 1D array | currency/ton | User (historical prices) |

### Outputs

| Variable | Shape | Unit | Description |
|----------|-------|------|-------------|
| `net_revenue` | (H,W) | currency/ha | Net revenue per pixel |
| `revenue_class` | (H,W) | 1–7 | Classified net revenue |
| `revenue_norm` | (H,W) | 0–1 | Normalized net revenue |

### Procedure

```python
from pyaez import EconomicSuitability

econ = EconomicSuitability.EconomicSuitability()

# Define economic parameters
cost = np.array([30100, 30000, 27000, 25500])    # THB/ha
yield_pts = np.array([4.8, 5.5, 6.1, 8.7]) / 2  # ton/ha
prices = np.arange(6.5, 9.5, 0.5) * 1000         # THB/ton

# Convert yield to tons if needed
yield_map_tons = terrain_yield_rain / 1000  # kg/ha → ton/ha

econ.addACrop('maize_rain', cost, yield_pts, prices, yield_map_tons)

revenue = econ.getNetRevenue('maize_rain')
rev_class = econ.getClassifiedNetRevenue('maize_rain')
rev_norm = econ.getNormalizedNetRevenue('maize_rain')
```

### Key Algorithm: Break-Even Analysis

1. Linear regression: Cost = slope × Yield + intercept
2. Break-even yield: `y_min = intercept / (mean_price - slope)`
3. Net revenue: `(yield - y_min) × mean_price` (clamped to ≥ 0)
4. Classification: 7 classes using percentile breakpoints

### Verification (Module VI)

1. **Revenue range**: Should be ≥ 0 (clamped); high-yield areas have highest revenue
2. **Break-even**: y_min should be realistic (check linear regression R²)
3. **Yield units**: Module V output is kg/ha; Module VI may expect ton/ha
4. **Revenue classification**: Classes 1–7 with reasonable spread

### Traps (Module VI)

| Trap | Symptom | Fix |
|------|---------|-----|
| Yield in kg/ha, expects ton/ha | Revenue 1000× too high | Divide yield by 1000 |
| All revenue = 0 | Break-even > all yields | Check cost/price data |
| Negative regression slope | Revenue formula breaks | Check cost/yield data quality |
| Currency mismatch | Incomparable results | Ensure cost and price in same currency |

## Example (Full V+VI Pipeline)

```python
# Module V
tc = TerrainConstraints.TerrainConstraints()
tc.importTerrainReductionSheet('maiz_terrain_constraints_irr.xlsx',
                                'maiz_terrain_constraints_rain.xlsx')
tc.setClimateTerrainData(precip, slope)
tc.calculateFI()
final_yield = tc.applyTerrainConstraints(soil_yield_rain, 'R')

# Module VI
econ = EconomicSuitability.EconomicSuitability()
econ.addACrop('maize_rain', cost, yield_pts, prices, final_yield / 1000)
revenue = econ.getNetRevenue('maize_rain')
print(f"Mean net revenue: {revenue[mask>0].mean():.0f} THB/ha")
```
