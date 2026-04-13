# Module Configuration (setup.xml) — Skill Document

> **Stage ID**: s3_setup_modules
> **Pipeline order**: 3 of 10
> **Depends on**: s1_project_setup

## Purpose

Configure which LDNDC process modules to use for microclimate, water cycle, soil chemistry, and plant physiology. Also configure which output variables to write and at what temporal resolution. The module selection must match the ecosystem type -- using forest modules for cropland produces nonsensical results.

## Prerequisites

- [ ] Project directory created (S1 complete)
- [ ] Ecosystem type determined (cropland, grassland, forest, or wetland)
- [ ] Desired output variables and temporal resolution decided

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| project_dir | directory | S1 | LDNDC project root |
| ecosystem_type | string | User | cropland, grassland, forest, or wetland |
| output_detail | string | User | minimal, standard, or detailed |

## Procedure

### Step 1: Select module combination

Use the following ecosystem-module mapping:

| Ecosystem | Microclimate | Watercycle | Soilchemistry | Physiology |
|-----------|-------------|------------|---------------|------------|
| Cropland | microclimate:canopyecm | watercycle:dndc | soilchemistry:metrx | physiology:plamox |
| Grassland | microclimate:canopyecm | watercycle:dndc | soilchemistry:metrx | physiology:grasslanddndc |
| Forest | microclimate:canopyecm | watercycle:dndc | soilchemistry:dndc | physiology:psim |
| Wetland | microclimate:canopyecm | watercycle:dndc | soilchemistry:metrx | physiology:plamox |

### Step 2: Generate setup.xml

```bash
python tools/s3_setup_modules/generate_setup_xml.py
```

Set `project_dir`, `ecosystem_type`, and optionally `output_detail`.

**Expected result**: `{project_dir}/input/setup.xml` with content like:

```xml
<ldndcsetup>
  <modulelist>
    <module use="microclimate:canopyecm"/>
    <module use="watercycle:dndc"/>
    <module use="soilchemistry:metrx"/>
    <module use="physiology:plamox"/>
    <module use="output:soilchemistry:daily"/>
    <module use="output:watercycle:daily"/>
    <module use="output:physiology:daily"/>
    <module use="output:soilchemistry-layer:daily"/>
    <module use="output:ecosystem:yearly"/>
  </modulelist>
</ldndcsetup>
```

### Step 3: Configure output modules

Output module naming pattern: `output:{category}:{resolution}`

| Category | Resolution Options | Key Variables |
|----------|-------------------|---------------|
| soilchemistry | daily, yearly, subdaily | N2O, CO2, CH4 emissions; NO3, NH4 leaching |
| soilchemistry-layer | daily | Per-layer C/N pools, moisture, temperature |
| soilchemistry-horizons | daily | Per-horizon aggregated values |
| watercycle | daily, yearly | ET, drainage, runoff, soil water content |
| physiology | daily, yearly | GPP, NPP, LAI, biomass, yield |
| microclimate | daily | Soil temperature profile, air temperature |
| ecosystem | yearly | Integrated ecosystem fluxes |
| management | yearly | Applied management events summary |

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| setup.xml | `{project_dir}/input/setup.xml` | Well-formed XML; modulelist has 4+ process modules + output modules |

## Validation Checks

1. **Module names valid**: Each module name is a recognized LDNDC module
2. **Module compatibility**: Microclimate, watercycle, soilchemistry, and physiology modules are compatible
3. **At least one output**: At least one `output:` module is defined
4. **No duplicate modules**: No category has two process modules

## Common Pitfalls

> **PITFALL**: Incompatible module combination
> Using forest physiology (psim) with cropland management events produces no error but generates meaningless output -- the physiology module ignores crop management because it expects forest stand parameters.
> **Do this instead**: Always match ecosystem_type to the module table above.
> See diagnostic triplet dt_004.

> **PITFALL**: No output modules configured
> LDNDC runs successfully but produces no output files if no `output:` modules are in setup.xml. There is no warning about missing output configuration.
> **Do this instead**: Always include at least `output:soilchemistry:daily` and `output:physiology:daily`.

---

*This skill document is part of the ldndc-knowledge-infrastructure package.*
*Stage 3 of 10 | Tools used: generate_setup_xml | Related triplets: dt_004*
