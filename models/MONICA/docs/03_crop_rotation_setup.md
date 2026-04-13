# Stage 3: Crop Rotation Setup

## Purpose

Configure the crop rotation and management calendar in `crop.json`. This file
defines which crops are grown, when they are sown and harvested, and what
fertilisation, irrigation, and tillage operations are applied.

## Inputs

| Source              | Information needed                                |
|---------------------|--------------------------------------------------|
| Agronomic calendar  | Sowing/harvest dates, crop varieties              |
| Fertiliser records  | Application dates, amounts, fertiliser types      |
| Irrigation schedule | Dates, amounts                                    |
| Tillage records     | Dates, depths                                     |
| MONICA parameters   | Crop species/cultivar JSON files from monica-parameters |

## Outputs

File: `crop.json` — JSON defining crop library, fertiliser library, and
rotation worksteps.

### Structure

```json
{
  "crops": {
    "WW": {
      "is-winter-crop": true,
      "cropParams": {
        "species": ["include-from-file", "crops/wheat.json"],
        "cultivar": ["include-from-file", "crops/wheat/winter-wheat.json"]
      },
      "residueParams": ["include-from-file", "crop-residues/wheat.json"]
    }
  },
  "fert-params": {
    "AN": ["include-from-file", "mineral-fertilisers/AN.json"]
  },
  "cropRotation": [
    {
      "worksteps": [
        { "type": "Sowing", "date": "1991-10-01", "crop": ["ref", "crops", "WW"] },
        { "type": "MineralFertilization", "date": "1992-03-15",
          "amount": [120, "kg N"], "partition": ["ref", "fert-params", "AN"] },
        { "type": "AutomaticHarvest", "latest-date": "1992-08-15" }
      ]
    }
  ]
}
```

## Procedure

1. **Identify crops** — list crops in the rotation and find matching species/cultivar
   files in `monica-parameters/crops/`
2. **Define crop entries** — for each crop, set `is-winter-crop`, link species
   and cultivar parameter files
3. **Define fertiliser library** — link mineral and organic fertiliser parameter files
4. **Build workstep sequences** — for each crop rotation cycle, add:
   - `Sowing` with date and crop reference
   - `MineralFertilization` with date, amount in **kg N ha⁻¹**, partition
   - `OrganicFertilization` with amount in **kg FM ha⁻¹**, parameters
   - `Irrigation` with amount in **mm**
   - `Tillage` with depth in **m**
   - `AutomaticHarvest` with latest harvest date
5. **Validate** — check date ordering, amounts, crop-fertiliser consistency

## Available Crops (from monica-parameters)

Common crops with species JSON files:
- `wheat.json` (winter wheat, spring wheat cultivars)
- `barley.json` (winter barley, spring barley)
- `maize.json` (silage maize, grain maize)
- `rape.json` (winter rapeseed)
- `sugar-beet.json`
- `potato.json`
- `rye.json`
- `triticale.json`
- `soybean.json`
- `sunflower.json`

## Workstep Types

| Type                    | Key parameters                                  | Units                |
|-------------------------|------------------------------------------------|----------------------|
| Sowing                  | date, crop, plantDensity                        | plants m⁻²          |
| AutomaticSowing         | min-temp, min-%-ASW, max-%-ASW, earliest/latest| °C, %, date          |
| MineralFertilization    | date, amount, partition                         | kg N ha⁻¹            |
| OrganicFertilization    | date, amount, params, incorporation             | kg FM ha⁻¹           |
| Irrigation              | date, amount, nitrateConcentration              | mm, mg dm⁻³          |
| Tillage                 | date, depth                                     | m                    |
| AutomaticHarvest        | latest-date, min/max-%-ASW                      | date, %              |
| Cutting                 | date, cutMaxAssimilationRatePercentage          | fraction             |

## Verification

- [ ] All `"include-from-file"` paths resolve in monica-parameters
- [ ] Sowing dates precede harvest dates
- [ ] Winter crops sown in autumn, spring crops in spring
- [ ] Fertiliser amounts are in kg N ha⁻¹ (not kg product ha⁻¹)
- [ ] Tillage depth in m (not cm)
- [ ] Irrigation in mm (not m)
- [ ] No overlapping crop growth periods (unless intercropping)

## Traps

| ID   | Symptom                         | Cause                                   | Fix                       |
|------|--------------------------------|------------------------------------------|---------------------------|
| UT11 | N surplus 5× too high          | Fertiliser in kg product, not kg N       | Multiply by N fraction    |
| —    | Crop doesn't emerge            | Winter crop sown in spring               | Use correct crop type     |
| —    | No harvest in output           | Harvest date before maturity             | Extend latest-date        |
| —    | Parameter file not found       | MONICA_PARAMETERS not set                | Set env variable          |

## Example

Minimal winter wheat rotation:

```json
{
  "crops": {
    "WW": {
      "is-winter-crop": true,
      "cropParams": {
        "species": ["include-from-file", "crops/wheat.json"],
        "cultivar": ["include-from-file", "crops/wheat/winter-wheat.json"]
      },
      "residueParams": ["include-from-file", "crop-residues/wheat.json"]
    }
  },
  "fert-params": {
    "AN": ["include-from-file", "mineral-fertilisers/AN.json"]
  },
  "cropRotation": [
    {
      "worksteps": [
        { "type": "Sowing", "date": "0000-10-01", "crop": ["ref", "crops", "WW"] },
        { "type": "MineralFertilization", "date": "0001-03-20",
          "amount": [80, "kg N"], "partition": ["ref", "fert-params", "AN"] },
        { "type": "MineralFertilization", "date": "0001-05-10",
          "amount": [60, "kg N"], "partition": ["ref", "fert-params", "AN"] },
        { "type": "AutomaticHarvest", "latest-date": "0001-08-31" }
      ]
    }
  ],
  "CropParameters": ["include-from-file", "general/crop.json"]
}
```

Note: Dates `0000-MM-DD` and `0001-MM-DD` are relative dates within the crop
rotation cycle. MONICA maps them to actual calendar dates based on simulation
start.
