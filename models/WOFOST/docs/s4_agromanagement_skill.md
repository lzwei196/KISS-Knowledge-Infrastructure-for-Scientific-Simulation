# Agromanagement Definition — Skill Document

> **Stage ID**: s4_agromanagement
> **Pipeline order**: 4 of 8
> **Depends on**: s1_crop_params (crop_name and variety_name must match)

## Purpose

Define the agricultural management schedule that controls when and how the crop is sown, irrigated, fertilized, and harvested. PCSE uses YAML-formatted agromanagement definitions that are parsed by the AgroManager. The agromanagement is the only input that directly controls the simulation timeline. Errors here either prevent the simulation from starting or cause it to terminate prematurely.

## Prerequisites

- [ ] Crop name and variety name determined (from Stage 1)
- [ ] Sowing date appropriate for the crop and climate zone
- [ ] Simulation period falls within weather data availability (Stage 3)
- [ ] Understanding of crop_start_type: `sowing` (crop starts from seed) vs `emergence` (crop starts already emerged)

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| crop_name | string | Stage 1 | Exact crop name from YAMLCropDataProvider (case sensitive) |
| variety_name | string | Stage 1 | Exact variety name (case sensitive) |
| campaign_start_date | date | user | Start of the agricultural campaign (YYYY-MM-DD) |
| crop_start_date | date | user | Sowing or emergence date |
| crop_start_type | string | user | `sowing` or `emergence` |
| crop_end_type | string | user | `maturity`, `harvest`, or `earliest` |
| max_duration | integer | user | Maximum simulation days (safety limit) |
| irrigation_events | list | optional | List of {date, amount_cm, efficiency} |
| fertilization_events | list | optional | List of {date, N_amount, P_amount} |

## Procedure

### Step 1: Determine sowing date

Choose the sowing date based on crop type and latitude:

| Crop | Northern Hemisphere | Southern Hemisphere |
|------|-------------------|-------------------|
| Winter wheat | Sep 15 – Nov 15 | Mar 15 – May 15 |
| Spring wheat | Mar 1 – May 1 | Sep 1 – Nov 1 |
| Maize | Apr 1 – Jun 15 | Oct 1 – Dec 15 |
| Rice (paddy) | Apr 15 – Jun 30 | Oct 15 – Dec 30 |
| Soybean | May 1 – Jun 30 | Nov 1 – Dec 30 |

For winter crops, the campaign start date must precede the sowing date. Typically set campaign start 2 weeks before sowing.

### Step 2: Construct the YAML agromanagement

```python
import yaml
import datetime

# Basic agromanagement for winter wheat
agro_dict = [{
    datetime.date(2000, 10, 1): {  # campaign start
        'CropCalendar': {
            'crop_name': 'wheat',                    # CASE SENSITIVE
            'variety_name': 'Winter_wheat_101',      # CASE SENSITIVE
            'crop_start_date': datetime.date(2000, 10, 15),
            'crop_start_type': 'sowing',
            'crop_end_date': None,                   # None = use crop_end_type
            'crop_end_type': 'maturity',
            'max_duration': 365,
        },
        'TimedEvents': None,
        'StateEvents': None,
    }
}]
```

**CRITICAL**: `crop_name` and `variety_name` must EXACTLY match what the YAMLCropDataProvider has. Case matters.

### Step 3: Add irrigation events (optional)

For water-limited simulations (WLP), irrigation can be added as TimedEvents:

```python
timed_events = [
    {
        'event_signal': 'irrigate',
        'name': 'irrigation schedule',
        'comment': 'fixed supplemental irrigation',
        'events_table': [
            {datetime.date(2001, 3, 15): {'amount': 3.0, 'efficiency': 0.7}},  # 3 cm = 30 mm
            {datetime.date(2001, 4, 15): {'amount': 3.0, 'efficiency': 0.7}},
        ]
    }
]
# Note: irrigation amount is in cm (not mm)
```

### Step 4: Add fertilization events (optional, for nutrient-limited models)

PCSE WOFOST 7.2 standard does not include nitrogen limitation. However, the LINTUL3 model within PCSE does. For WOFOST, fertilization events are ignored.

### Step 5: Write to YAML file

```python
agro_yaml_path = f'outputs/{run_name}/wofost/agromanagement.yaml'
with open(agro_yaml_path, 'w') as f:
    yaml.dump(agro_dict, f, default_flow_style=False, allow_unicode=True)
```

### Step 6: Validate the YAML

```python
# Re-read and verify structure
with open(agro_yaml_path) as f:
    agro_loaded = yaml.safe_load(f)

assert isinstance(agro_loaded, list), "AgroManagement must be a list"
assert len(agro_loaded) > 0, "AgroManagement list is empty"

campaign = agro_loaded[0]
assert isinstance(campaign, dict), "Campaign must be a dict with date key"
campaign_date = list(campaign.keys())[0]
assert isinstance(campaign_date, datetime.date), \
    f"Campaign key must be a datetime.date, got {type(campaign_date)}"

cc = campaign[campaign_date].get('CropCalendar', {})
assert cc.get('crop_name'), "crop_name is missing or empty"
assert cc.get('variety_name'), "variety_name is missing or empty"
assert cc.get('max_duration', 0) > 0, "max_duration must be > 0"
```

**If this fails**: See diagnostic triplets dt_001 (YAML parse), dt_002 (indent error), dt_010 (case sensitivity).

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| agro YAML file | `outputs/{run}/wofost/agromanagement.yaml` | yaml.safe_load() succeeds; has CropCalendar |
| agro Python object | in-memory list of dicts | Directly usable by PCSE engine |

## Validation Checks

1. **YAML parses**: `yaml.safe_load()` does not raise exceptions
   - If unexpected: See diagnostic triplet dt_001

2. **crop_name exists**: Check against `cropdata.get_crop_types()`
   - If unexpected: See diagnostic triplet dt_010

3. **variety_name exists**: Check against `cropdata.get_variety_names(crop_name)`
   - If unexpected: See diagnostic triplet dt_010

4. **Date ordering**: campaign_start_date <= crop_start_date
   - For winter crops: campaign in autumn, crop sowing in autumn

5. **max_duration sufficient**: For winter wheat, 300-365 days. For maize, 120-200 days.
   - If unexpected: See diagnostic triplet dt_014

## Common Pitfalls

> **PITFALL**: YAML indentation errors
> YAML is whitespace-sensitive. A CropCalendar at the wrong indent level becomes a sibling instead of a child, causing `KeyError` or silent misconfiguration.
> **Do this instead**: Use Python dicts and `yaml.dump()` to generate YAML, not manual string formatting.
> See diagnostic triplet dt_002.

> **PITFALL**: max_duration too short
> Setting max_duration=150 for winter wheat (which needs 250-300 days) causes the simulation to terminate before maturity. DVS never reaches 2.0. Yield is incomplete but no error is raised.
> **Do this instead**: Set max_duration generously (365 for winter crops, 200-250 for spring crops). The simulation will terminate at maturity anyway.
> See diagnostic triplet dt_014.

> **PITFALL**: Using `crop_end_date` instead of `crop_end_type: maturity`
> If you set a fixed crop_end_date, the simulation may terminate before the crop matures (if development is slow due to cold weather) or long after maturity (wasting computation). Prefer `crop_end_type: maturity` with `crop_end_date: null`.

---

*This skill document is part of the wofost-pcse-knowledge infrastructure.*
*Stage 4 of 8 | Tools: generate_agromanagement_yaml, validate_agromanagement | Related triplets: dt_001, dt_002, dt_010, dt_014*
