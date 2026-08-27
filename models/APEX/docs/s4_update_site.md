# S4 Update Site

## Purpose

Retarget the copied APEX site file to a new latitude, longitude, and elevation without disturbing the rest of the validated `*.SIT` fields.

## Inputs

- A workspace from S1
- `tools/s4_update_site.py`
- Latitude, longitude, and elevation in metres
- `SITECOM.DAT` for auto-detecting the APEX0806 `*.SIT` file, usually `SIT0002.SIT`

## Outputs

- Updated line 4 of the selected `*.SIT` file. The first three F8.2 fields become latitude, longitude, and elevation; the trailing fields, including CO2, remain from the template.

## Procedure

```bash
cd KISSPATH_KI_ROOT/APEX/knowledge_infrastructure
python tools/s1_setup_workspace.py /tmp/apex_ws
python tools/s4_update_site.py --workspace /tmp/apex_ws --lat 32.94 --lon 117.36 --elev 23
```

To override auto-detection:

```bash
python tools/s4_update_site.py --workspace /tmp/apex_ws --lat 32.94 --lon 117.36 --elev 23 --sit-name SIT0002.SIT
```

## Verification

```bash
sed -n '4p' /tmp/apex_ws/SIT0002.SIT
python - <<'PY'
from tools.s4_update_site import _fixed_fields
line = open("/tmp/apex_ws/SIT0002.SIT").read().splitlines()[3]
print(_fixed_fields(line)[:5])
PY
```

The fixed-width parse should show the requested latitude, longitude, elevation, and a plausible CO2 value in field 5.

## Traps

- `diagnostics/triplets.yaml:apex0806_sit_column_shift_co2_starvation` - adding a leading pad to the F8.2 row shifts CO2 to an impossible value and silently starves crop growth.
- `diagnostics/triplets.yaml:file_missing_uppercase` - `SITECOM.DAT` references real filenames by exact case.
- `dag.yaml` hazard `site_units_elevation_slope` - elevation is metres, and southern hemisphere latitude must be negative.

## Example

```bash
python tools/s4_update_site.py --workspace /tmp/apex_bengbu --lat 32.94 --lon 117.36 --elev 23
cut -c1-8,9-16,17-24,33-40 /tmp/apex_bengbu/SIT0002.SIT | sed -n '4p'
```
