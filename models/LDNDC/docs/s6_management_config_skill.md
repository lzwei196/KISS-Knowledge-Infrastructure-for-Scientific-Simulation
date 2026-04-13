# Management Events Configuration (mana.xml) — Skill Document

> **Stage ID**: s6_management_config
> **Pipeline order**: 6 of 10
> **Depends on**: s1_project_setup

## Purpose

Define agricultural management operations in `mana.xml` that drive LDNDC's biogeochemistry: when crops are sown, how much fertilizer is applied, when and how tillage occurs, and when harvest happens. Management is the primary human control on soil C/N cycling and GHG emissions.

## Prerequisites

- [ ] Project directory created (S1 complete)
- [ ] Crop type and management schedule known
- [ ] LDNDC species parameter database available (parameters_species.xml)

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| project_dir | directory | S1 | LDNDC project root |
| management_config | config | User/DSSAT/literature | JSON with event definitions |
| simulation_years | list | S1 | Years to generate events for |

## Procedure

### Step 1: Define management events

Create a JSON config with events. Each event has: type, date, and type-specific parameters.

**Event types and parameters:**

| Event | Key Parameters | Example |
|-------|---------------|---------|
| sowing | species (must match parameters_species.xml), seed_amount (kgC/ha) | `{"type": "sowing", "date": "2005-04-15", "species": "maize", "seed_amount": 10}` |
| fertilization | n_amount (kgN/ha), fert_type (urea, ammonium_nitrate, organic), depth_cm | `{"type": "fertilization", "date": "2005-05-01", "n_amount": 120, "fert_type": "urea", "depth_cm": 5}` |
| tillage | depth_cm, intensity (0-1, fraction of residue incorporated) | `{"type": "tillage", "date": "2005-03-20", "depth_cm": 25, "intensity": 0.9}` |
| harvest | residue_fraction (0-1, fraction of aboveground left on field) | `{"type": "harvest", "date": "2005-10-01", "residue_fraction": 0.3}` |
| irrigation | amount_mm | `{"type": "irrigation", "date": "2005-07-15", "amount_mm": 50}` |

### Step 2: Generate mana.xml

```bash
python tools/s6_management_config/generate_management_xml.py
```

**Expected result**: `{project_dir}/input/mana.xml` with structure:

```xml
<ldndcmanagement>
  <event type="tillage" date="2005-03-20" depth="0.25" intensity="0.9"/>
  <event type="sowing" date="2005-04-15" species="maize" seedamount="10"/>
  <event type="fertilization" date="2005-05-01" amount="120" type="urea" depth="0.05"/>
  <event type="harvest" date="2005-10-01" residuefraction="0.3"/>
</ldndcmanagement>
```

**If this fails**: See diagnostic triplet dt_008.

### Step 3: Verify species names

Cross-check every species name in sowing events against `parameters_species.xml`. An exact string match is required. See dt_009 for the consequences of mismatched names.

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| mana.xml | `{project_dir}/input/mana.xml` | Well-formed XML; events cover all simulation years |

## Validation Checks

1. **Date range**: All event dates within [start_date, end_date] from project.xml
2. **Species match**: Every sowing species name exists in parameters_species.xml
3. **Annual coverage**: At least one sowing event per simulation year (for cropland)
4. **Fertilizer range**: N amounts 0-400 kgN/ha per application (>400 is suspicious)
5. **Event ordering**: Per-year events in chronological order (tillage before sowing before harvest)

## Common Pitfalls

> **PITFALL**: Species name mismatch
> If mana.xml says "wheat" but parameters_species.xml has "winter_wheat", LDNDC silently skips the sowing. No crop grows, yield is zero. No error is raised.
> **Do this instead**: Run validate_species_params (S7) after generating mana.xml.
> See diagnostic triplet dt_009.

> **PITFALL**: Event dates outside simulation period
> LDNDC rejects events with dates outside the project.xml schedule. This is a fatal error, not a silent one.
> See diagnostic triplet dt_008.

> **PITFALL**: Tillage depth in meters instead of centimeters
> LDNDC expects tillage depth in meters in the XML (e.g., 0.25 for 25 cm). If provided in cm (25), tillage reaches 25 meters deep, which is nonsensical but does not cause an error.

---

*This skill document is part of the ldndc-knowledge-infrastructure package.*
*Stage 6 of 10 | Tools used: generate_management_xml | Related triplets: dt_008, dt_009*
