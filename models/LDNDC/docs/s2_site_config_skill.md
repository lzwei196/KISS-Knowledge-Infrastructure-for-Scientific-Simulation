# Site Configuration (site.xml) — Skill Document

> **Stage ID**: s2_site_config
> **Pipeline order**: 2 of 10
> **Depends on**: s1_project_setup

## Purpose

Define the physical and chemical properties of the simulation site in `site.xml`. This includes the soil profile (layer depths, texture, bulk density, pH, organic carbon, total nitrogen, stone fraction), canopy structure, and optional groundwater settings. The soil profile is the foundation for all biogeochemical calculations -- incorrect soil data silently corrupts all LDNDC outputs.

## Prerequisites

- [ ] Project directory created (S1 complete)
- [ ] Soil data available: either from HWSD global database, VIC soil params, or user measurements
- [ ] Python environment activated

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| project_dir | directory | S1 | LDNDC project root |
| soil_data | config | HWSD, VIC, or user | JSON with per-horizon properties |
| lat | number | User | Latitude for HWSD lookup |
| lon | number | User | Longitude for HWSD lookup |
| hwsd_raster | file | HydroCraft data | `data/soil/HWSD_RASTER/hwsd.bil` |
| hwsd_mdb | file | HydroCraft data | `data/forcing/huaihe_raw/soil/HWSD.mdb` |

## Procedure

### Step 1: Obtain soil data from HWSD (if no user data)

```bash
python tools/s2_site_config/hwsd_to_ldndc_soil.py
```

Set `lat`, `lon`, `hwsd_raster`, `hwsd_mdb`. This queries HWSD and returns JSON with LDNDC-format soil horizons.

**Expected result**: JSON with 2+ horizons, each containing: depth_cm, clay_pct, sand_pct, silt_pct, bd_gcm3, pH, corg_fraction, norg_fraction, stone_fraction.

**Critical check**: Verify `corg` values are mass fractions (0.001-0.05 for mineral soils), NOT percentages. See dt_003.

### Step 2: Generate site.xml

```bash
python tools/s2_site_config/generate_site_xml.py
```

Set `project_dir` and `soil_data` (output from Step 1 or user-provided).

**Expected result**: `{project_dir}/input/site.xml` with structure:

```xml
<ldndcsite>
  <soilprofile>
    <layer depth="0.30" clay="0.18" sand="0.42" silt="0.40"
           bd="1.35" pH="6.8" corg="0.015" norg="0.0015"
           stone="0.0" fe="0.0"/>
    <layer depth="1.00" clay="0.22" sand="0.38" silt="0.40"
           bd="1.45" pH="7.0" corg="0.008" norg="0.0008"
           stone="0.05" fe="0.0"/>
    <layer depth="2.00" clay="0.25" sand="0.35" silt="0.40"
           bd="1.50" pH="7.2" corg="0.003" norg="0.0003"
           stone="0.10" fe="0.0"/>
  </soilprofile>
</ldndcsite>
```

**If this fails**: See diagnostic triplet dt_002.

### Step 3: Validate soil properties

Check each layer:
- `bd` (bulk density): 0.5 - 2.0 g/cm3 (organic soils can be lower)
- `clay + sand + silt` should approximately equal 1.0 (as fractions) or sum checked
- `corg` (organic carbon): mass fraction, typically 0.001-0.05 for mineral soils
- `pH`: 3.0 - 10.0
- Layer depths increase monotonically

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| site.xml | `{project_dir}/input/site.xml` | Well-formed XML; has soilprofile with 2+ layers |
| soil_data JSON | in-memory | Used by Step 2; all horizons have required fields |

## Validation Checks

1. **Layer count**: At least 2 soil layers defined
   - Expected: 2-10 layers for typical simulations
2. **Layer depth monotonicity**: Each layer deeper than the previous
3. **Bulk density range**: 0.5 <= bd <= 2.0 g/cm3 for each layer
4. **Organic carbon**: corg < 0.10 for mineral soils (if > 0.10, likely unit error -- see dt_003)
5. **Texture sum**: clay + sand + silt = 1.0 (as fractions) within 0.01 tolerance

## Common Pitfalls

> **PITFALL**: Organic carbon as percentage instead of fraction
> HWSD reports organic carbon as percentage (e.g., 1.5%). LDNDC expects mass fraction (0.015). If the /100 conversion is skipped, CO2 emissions will be 100x too high. The model gives no warning.
> **Do this instead**: Always use hwsd_to_ldndc_soil which applies the conversion automatically.
> See diagnostic triplet dt_003 for full details.

> **PITFALL**: Missing subsoil horizons
> Using only one horizon (topsoil) causes unrealistic drainage behavior and incorrect deep soil C/N cycling. Always define at least 2 horizons (topsoil 0-30cm, subsoil 30-100cm minimum).
> **Do this instead**: Use hwsd_to_ldndc_soil which creates topsoil + subsoil + optional deep layer.

> **PITFALL**: Zero bulk density causes segfault
> A layer with bd=0 causes division by zero during soil initialization (porosity = 1 - bd/2.65). LDNDC segfaults without a helpful error message.
> See diagnostic triplet dt_010.

---

*This skill document is part of the ldndc-knowledge-infrastructure package.*
*Stage 2 of 10 | Tools used: generate_site_xml, hwsd_to_ldndc_soil | Related triplets: dt_002, dt_003, dt_010*
