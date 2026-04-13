# S1: FATES Parameter File Setup

## Purpose

Configure the FATES JSON parameter file for the target simulation site and Plant
Functional Types (PFTs). The parameter file controls all aspects of FATES behavior:
allometry, photosynthesis, mortality, fire, hydraulics, phenology, and output binning.

## Inputs

| Input | Format | Source | Required |
|-------|--------|--------|----------|
| `fates_params_default.json` | JSON | `parameter_files/` in FATES repo | Yes |
| Site characteristics | Manual | Field data, literature | Yes |
| Target PFT list | Manual | Vegetation classification | Yes |

### Parameter File Structure

```json
{
  "attributes": { ... },
  "dimensions": {
    "fates_pft": 14,
    "fates_NCWD": 4,
    "fates_litterclass": 6,
    "fates_hydr_organs": 4,
    "fates_plant_organs": 4,
    "fates_history_size_bins": 13,
    "fates_history_age_bins": 7
  },
  "parameters": {
    "fates_leaf_vcmax25top": {
      "dtype": "float",
      "dims": ["fates_pft"],
      "long_name": "maximum rate of carboxylation at 25C",
      "units": "umol CO2/m^2/s",
      "data": [65.0, 39.0, 62.0, ...]
    }
  }
}
```

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Modified `fates_params.json` | JSON | Customized parameter file |
| Validation report | JSON | Range checks and warnings |

## Procedure

1. **Start from default**: Always begin with `fates_params_default.json`
2. **Identify active PFTs**: Determine which of the 14 PFTs are relevant
   - PFT 0: Broadleaf evergreen tropical tree
   - PFT 1: Needleleaf evergreen extratropical tree
   - PFT 2: Needleleaf cold-deciduous extratropical tree
   - PFT 3: Broadleaf evergreen extratropical tree
   - PFT 4: Broadleaf hydro-deciduous tropical tree
   - PFT 5: Broadleaf cold-deciduous extratropical tree
   - PFT 6-8: Shrubs (evergreen, hydro-deciduous, cold-deciduous)
   - PFT 9-11: Grasses (arctic C3, cool C3, C4)
   - PFT 12-13: Crops (C3, C4)

3. **Modify key parameters**:
   ```bash
   python tools/convert_fates_params.py \
       --fin fates_params_default.json \
       --operation modify \
       --param fates_leaf_vcmax25top \
       --pft-index 0 --value 65.0 \
       --fout custom_params.json
   ```

4. **Validate modified file**:
   ```bash
   python tools/convert_fates_params.py \
       --fin custom_params.json \
       --operation validate \
       --report validation_report.json
   ```

5. **Query specific parameters**:
   ```bash
   python tools/convert_fates_params.py \
       --fin custom_params.json \
       --operation query \
       --param fates_mort_scalar_cstarvation
   ```

## Verification

- [ ] Parameter file is valid JSON (no syntax errors)
- [ ] All PFT-dimensioned arrays have length = `fates_pft` (default 14)
- [ ] Key parameters are within physical ranges (see SKILL.md unit table)
- [ ] No unintended modifications to non-target PFTs
- [ ] File size is reasonable (~96 KB for default 14-PFT file)

## Traps

| Trap ID | Description | Detection |
|---------|-------------|-----------|
| dt_013 | Using legacy CDL/netCDF format instead of JSON | File extension check |
| dt_014 | PFT index off-by-one (0-based JSON vs 1-based Fortran) | Range check |
| dt_015 | PARTEH mass units are kg, not gC or tC | Unit label check |

### Critical: PFT Indexing

The FATES Fortran source uses **1-based** PFT indices. The JSON parameter file uses
**0-based** array indices. When a paper or documentation says "PFT 1 (tropical broadleaf
evergreen)", the JSON array index is **0**.

```python
# WRONG — this modifies PFT 2 (needleleaf), not PFT 1 (tropical broadleaf)
modify_parameter(data, "fates_leaf_vcmax25top", pft_index=1, value=65.0)

# CORRECT — PFT index 0 = tropical broadleaf evergreen
modify_parameter(data, "fates_leaf_vcmax25top", pft_index=0, value=65.0)
```

## Example

**Scenario**: Configure FATES for Barro Colorado Island (BCI), Panama — a tropical
moist forest dominated by broadleaf evergreen trees.

```bash
# 1. Query default values for tropical PFTs
python tools/convert_fates_params.py \
    --fin parameter_files/fates_params_default.json \
    --operation query --param fates_wood_density

# 2. Modify wood density for PFT 0 (tropical broadleaf evergreen)
python tools/convert_fates_params.py \
    --fin parameter_files/fates_params_default.json \
    --operation modify \
    --param fates_wood_density --pft-index 0 --value 0.55 \
    --fout bci_params.json

# 3. Validate the modified file
python tools/convert_fates_params.py \
    --fin bci_params.json --operation validate
```
