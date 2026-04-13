# Species Parameters Configuration — Skill Document

> **Stage ID**: s7_species_params
> **Pipeline order**: 7 of 10
> **Depends on**: s6_management_config

## Purpose

Ensure that the species parameters file (`parameters_species.xml`) contains entries for every crop/vegetation species referenced in management events (`mana.xml`). This cross-validation prevents the most common cause of zero-yield LDNDC simulations: species name mismatch.

## Prerequisites

- [ ] Management events defined (S6 complete)
- [ ] parameters_species.xml available (from LDNDC distribution or custom)

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| species_xml | file | LDNDC distribution | parameters_species.xml with crop parameter definitions |
| mana_xml | file | S6 | Management events with species references |

## Procedure

### Step 1: Validate species cross-reference

```bash
python tools/s7_species_params/validate_species_params.py
```

Set `species_xml` and `mana_xml` paths.

**Expected result**: JSON output confirming all species in mana.xml exist in parameters_species.xml.

**If validation fails**: Add missing species to parameters_species.xml or correct the species name in mana.xml to match an existing entry.

### Step 2: Review key parameters (if calibrating)

For each crop species, the critical parameters in parameters_species.xml are:

| Parameter | Description | Typical Range | Impact |
|-----------|-------------|---------------|--------|
| tbase | Base temperature for growth (C) | 5-10 | Below this, no growth occurs |
| topt | Optimal temperature (C) | 20-30 | Peak growth rate |
| gdd_maturity | Growing degree days to maturity | 1000-2500 | Controls phenology length |
| maxlai | Maximum LAI | 3-8 | Constrains canopy development |
| cn_leaf | Leaf C:N ratio | 15-35 | Affects N demand |
| rootdepth | Maximum root depth (m) | 0.5-2.0 | Controls water/nutrient uptake zone |
| harvest_index | Grain fraction of aboveground | 0.3-0.5 | Determines yield |

### Step 3: Copy parameters_species.xml to project

Copy the validated file to `{project_dir}/input/parameters_species.xml`.

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| Validation result | stdout JSON | All species matched |
| parameters_species.xml | `{project_dir}/input/parameters_species.xml` | Contains all referenced species |

## Validation Checks

1. **Species coverage**: Every species name in mana.xml sowing events has a corresponding entry in parameters_species.xml
2. **Parameter ranges**: Key parameters (tbase, maxlai, rootdepth) are within physical ranges
3. **Case sensitivity**: Species names match exactly (case-sensitive comparison)

## Common Pitfalls

> **PITFALL**: Common name vs. LDNDC name
> LDNDC uses specific names like "winter_wheat" or "spring_barley", not generic "wheat" or "barley". The exact name must match.
> **Do this instead**: Check parameters_species.xml for the exact species name string.
> See diagnostic triplet dt_009.

> **PITFALL**: Using outdated parameters_species.xml
> Different LDNDC versions ship with different species lists. Using an older version's file with a newer binary may have incompatible parameter structure.
> **Do this instead**: Always use the parameters_species.xml from the same LDNDC distribution as the binary.

---

*This skill document is part of the ldndc-knowledge-infrastructure package.*
*Stage 7 of 10 | Tools used: validate_species_params | Related triplets: dt_009*
