# Field Management -- Skill Document

> **Stage ID**: s6_field_management
> **Pipeline order**: 6 of 10
> **Depends on**: none

## Purpose

Configure field management practices that affect soil evaporation and surface water dynamics: mulching (reduces soil evaporation), surface bunds (retain water for paddy rice), curve number adjustments (affect runoff partitioning), and surface runoff inhibition.

## Prerequisites

- [ ] Knowledge of field management practices at the target site
- [ ] For paddy rice: bund height information required

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| mulches | bool | User | Whether mulch is present |
| mulch_pct | float | User | % of soil surface covered (0-100) |
| f_mulch | float | User | Evaporation reduction factor (0-1) |
| bunds | bool | User | Whether surface bunds are present |
| z_bund | float | User | Bund height in METERS |
| bund_water | float | User | Initial water height in bunds (mm) |
| curve_number_adj | bool | User | Whether to adjust CN |
| curve_number_adj_pct | float | User | Percentage change in CN |
| sr_inhb | bool | User | Fully inhibit surface runoff |

## Procedure

### Step 1: Create FieldMngt object

```python
from aquacrop import FieldMngt

# Default (no management practices):
field = FieldMngt()

# With mulching:
field = FieldMngt(mulches=True, mulch_pct=50, f_mulch=0.5)

# With bunds (for paddy rice):
field = FieldMngt(bunds=True, z_bund=0.15, bund_water=0)
# z_bund is 0.15 METERS = 150 mm bund height

# Full management:
field = FieldMngt(
    mulches=True, mulch_pct=60, f_mulch=0.5,
    bunds=False,
    curve_number_adj=True, curve_number_adj_pct=-10,
    sr_inhb=False
)
```

### Step 2: For paddy rice simulation

Bunds are **required** for paddy rice to maintain standing water. Set:
```python
field = FieldMngt(bunds=True, z_bund=0.10, bund_water=0)
```
Use the paddy soil type: `Soil('Paddy')`.

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| FieldMngt object | in-memory | Instance with correct attribute values |

## Validation Checks

1. **Bund height**: If bunds=True, z_bund > 0 (in meters)
2. **Mulch percentage**: 0 <= mulch_pct <= 100
3. **Mulch factor**: 0 <= f_mulch <= 1

## Common Pitfalls

> **PITFALL**: Bund height in mm instead of meters
> z_bund is specified in METERS but internally multiplied by 1000 to store in mm. If you pass 150 (thinking mm), the model stores 150000 mm = 150m bund height.
> **Do this instead**: Pass z_bund in meters: `z_bund=0.15` for a 150mm bund.
> See diagnostic triplet dt_015.

> **PITFALL**: Missing bunds for paddy rice
> Paddy rice requires standing water. Without bunds, water runs off and the simulation produces unrealistic results.
> **Do this instead**: Always set `bunds=True` when using PaddyRice crop.

---

*This skill document is part of the aquacrop-ospy-knowledge infrastructure.*
*Stage 6 of 10 | Tools used: create_field_management | Related triplets: dt_015*
