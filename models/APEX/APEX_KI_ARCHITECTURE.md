# APEX KI Architecture Design

**Goal**: A fully parameterized APEX KI where any input can be changed
programmatically — crop type, soil, weather, management, site, control
settings — using the XLSM editor as the authoritative format reference.

## Design Principle

APEX has ~20 input files with hundreds of parameters across fixed-width
Fortran formats. The KI must:

1. **Never generate .DAT files from scratch** — always copy from template
2. **Expose every configurable parameter** as a Python function argument
3. **Use the XLSM editor** (`reference/apex_formats.json`) as the format spec
4. **Follow RZWQM2's proven pattern** — 10 stage tools, each owns one domain

## Architecture: Copy-Modify-Run

```
Template Workspace (shipped example, read-only)
    │
    ├── COPY entire workspace to /tmp/apex_{run_id}/
    │
    ├── MODIFY specific files via stage tools:
    │   ├── s1: workspace setup (copytree + validate)
    │   ├── s2: weather (swap .DLY/.WP1/.WND)
    │   ├── s3: soil (modify .SOL layers)
    │   ├── s4: site (modify .SIT — lat, lon, elevation, slope)
    │   ├── s5: control (modify APEXCONT.DAT — years, options)
    │   ├── s6: crop & management (generate .OPC from crop templates)
    │   ├── s7: subarea (modify .SUB — area, CN, Manning)
    │   ├── s8: list files (register new files in *LIST.DAT)
    │   ├── s9: run binary + collect output
    │   └── s10: parse output (.ACY, .AWP, .DWS, .RCH)
    │
    └── Each modify step uses string replacement on the TEMPLATE,
        never writes the full file from a Python dict.
```

## Stage Tools (10 stages, mirrors RZWQM2)

### s1: Setup Workspace
```python
def setup_workspace(output_dir, template_dir=EXAMPLE_DIR):
    """Copy entire template workspace. Returns workspace path."""
    shutil.copytree(template_dir, output_dir, dirs_exist_ok=True)
```

### s2: Weather — Convert Forcing to APEX Format
```python
def convert_forcing(workspace, lat, lon, start_year, end_year, source='cmfd'):
    """Load forcing via ki_tools_common, write .DLY/.WP1/.WND, update lists."""
    data = load_daily_forcing(source, lat, lon, start_year, end_year)
    write_dly(data, workspace)   # Daily weather
    write_wp1(data, workspace)   # Monthly summary
    write_wnd(data, workspace)   # Monthly wind
    update_list(workspace, 'WDLYLIST.DAT', new_dly)
    update_list(workspace, 'WPM1LIST.DAT', new_wp1)
    update_list(workspace, 'WINDLIST.DAT', new_wnd)
```

### s3: Soil — Convert HWSD to APEX .SOL
```python
def convert_soil(workspace, lat, lon):
    """HWSD lookup → APEX .SOL format, update SOILLIST.DAT."""
    soil = lookup_hwsd(lat, lon)
    # Read template .SOL, replace layer values
    template = read_template_sol(workspace)
    modify_sol_layers(template, soil)
    write_sol(workspace, template)
    update_list(workspace, 'SOILLIST.DAT', new_sol)
```

### s4: Site — Update .SIT for Location
```python
def update_site(workspace, lat, lon, elevation, slope=2.0):
    """Modify .SIT file with site coordinates. Format from XLSM SITE.SIT sheet."""
    # Read template, replace lat/lon/elev lines
    content = read_file(workspace, 'SITE01.SIT')
    content = replace_field(content, 'YLAT', lat, line=1, col=3)
    content = replace_field(content, 'XLOG', lon, line=1, col=4)
    content = replace_field(content, 'ELEV', elevation, line=1, col=5)
    write_file(workspace, 'SITE01.SIT', content)
```

### s5: Control — Update APEXCONT.DAT
```python
def update_control(workspace, n_years, start_year, start_month=1, start_day=1,
                   pet_method=1, cn_method=0, runoff_method=0):
    """Modify APEXCONT.DAT control parameters. 86 params from XLSM."""
    # Read template, replace Line 1 values
    content = read_file(workspace, 'APEXCONT.DAT')
    content = replace_line1(content, NBYR=n_years, IYR=start_year,
                           IMO=start_month, IDA=start_day, IET=pet_method)
    write_file(workspace, 'APEXCONT.DAT', content)
```

### s6: Crop & Management — Generate .OPC
```python
def set_crop(workspace, crop_name, lat, n_rate_kgha=None):
    """Generate crop-specific OPC from templates. Uses CROP_DB."""
    schedule = get_schedule(crop_name, lat)
    if n_rate_kgha:
        schedule['n_rate_kgha'] = n_rate_kgha
    write_opc(schedule, n_years, workspace + '/OPSC01.mgt')
    update_list(workspace, 'MNGTLIST.DAT', 'OPSC01.mgt')

# Supported crops (from PLANTABLE.DAT):
# corn(2), soybean(1), wheat(3), spring_wheat(7), rice(18),
# cotton(86), sorghum(4), pasture(187), alfalfa(31)
```

### s7: Subarea — Modify .SUB
```python
def update_subarea(workspace, area_ha, cn2=75, manning_n=0.15):
    """Modify subarea parameters. Format from XLSM SUBS.SUB sheet."""
    content = read_file(workspace, 'SUBA01.SUB')
    content = replace_field(content, 'WSA', area_ha)
    content = replace_field(content, 'CN2', cn2)
    content = replace_field(content, 'SPLM', manning_n)
    write_file(workspace, 'SUBA01.SUB', content)
```

### s8: List Files — Register New Files
```python
def update_list(workspace, list_file, new_entry):
    """Add or replace an entry in a *LIST.DAT file."""
    # Each list file has a simple format: index + filename per line
    # Format from XLSM list sheets (SITE.LIST, MNGT.LIST, etc.)
```

### s9: Run APEX
```python
def run_apex(workspace, binary_path=APEX_BINARY, timeout=300):
    """Execute APEX from workspace directory."""
    result = subprocess.run([binary_path], cwd=workspace, timeout=timeout)
    return parse_run_summary(workspace)
```

### s10: Parse Output
```python
def parse_output(workspace, variables=['yield', 'runoff', 'erosion', 'n_loss']):
    """Parse .ACY, .AWP, .DWS, .RCH output files."""
    # ACY columns from XLSM OUT.ACY sheet:
    # SA#, ID, YR, YR#, CPNM, YLDG, YLDF, BIOM, WS, NS, PS, KS, TS,
    # AS, SS, ZNO3, ZQP, AP15, ZOC, OCPD, RSDP, ARSD, IRGA, FN, FP...
```

## Parameter Reference (from XLSM)

### APEXCONT.DAT — 86 Control Parameters (13 lines)
| Line | Params | Key parameters |
|------|--------|---------------|
| 1 | NBYR, IYR, IMO, IDA, IPD, NGN0, IGN, IGS0, LPYR, IET... | Simulation period + options |
| 2 | MNUL, LPD, MSCP, IPRP, IOX, IDNT, IATL... | Management + transport options |
| 3-13 | Calibration coefficients | PARM(1)-PARM(86) |

### OPC Management — 9 Columns
| Col | Name | Source |
|-----|------|--------|
| 1 | YEAR | Rotation year |
| 2 | MONTH | Month |
| 3 | DAY | Day |
| 4 | TILLAGE_ID | TILLTABLE.DAT row |
| 5 | MACHINE_ID | Equipment |
| **6** | **PLANT_ID** | **CROPCOM.DAT / PLANTABLE.DAT row** |
| 7 | OPV | Operation variable |
| 8 | OPV1 | Operation parameter 1 |
| 9 | OPV2 | Operation parameter 2 |

### Key Operation Codes (TILLTABLE.DAT)
| Code | Operation | Use |
|------|-----------|-----|
| 132 | Drill plant | Standard planting |
| 261 | Fertilizer application | Manual N/P/K |
| 316 | Harvest grain | Crop harvest |
| 397 | Kill crop | Terminate standing crop |
| 426/427 | Begin/end grazing | Livestock |
| 579/580 | Auto/manual fertilize | N application |
| 623 | Hay harvest | Forage |
| 682 | Mow/harvest | General |

### Key Crop IDs (PLANTABLE.DAT)
| ID | Name | Type |
|----|------|------|
| 1 | SOYB | Legume |
| 2 | CORN | C4 grain |
| 3 | WWHT | Winter wheat |
| 4 | GRSG | Grain sorghum |
| 7 | SWHT | Spring wheat |
| 18 | RICE | Paddy rice |
| 31 | ALFA | Alfalfa |
| 86 | COTT | Cotton |
| 187 | PAST | Pasture/grass |

## Integration with HydroCraft

### One-Command Run
```python
from apex_ki import setup_workspace, convert_forcing, convert_soil, \
                     update_site, update_control, set_crop, run_apex, parse_output

workspace = setup_workspace("/tmp/apex_bengbu")
convert_forcing(workspace, lat=32.9, lon=117.4, start_year=2010, end_year=2015)
convert_soil(workspace, lat=32.9, lon=117.4)
update_site(workspace, lat=32.9, lon=117.4, elevation=23)
update_control(workspace, n_years=6, start_year=2010)
set_crop(workspace, crop="corn", lat=32.9, n_rate_kgha=150)
run_apex(workspace)
results = parse_output(workspace)
print(f"Corn yield: {results['yield_kgha']} kg/ha")
```

### Coupling with Other Models
- **VIC → APEX**: VIC gridded runoff → APEX subarea inflow
- **APEX → CaMa-Flood**: APEX outlet discharge → CaMa routing
- **APEX → LDNDC**: APEX residue C/N → LDNDC soil biogeochem
- **DSSAT ↔ APEX**: Compare field-scale crop yields (DSSAT daily vs APEX daily)

## File Modification Strategy

Every tool follows the same pattern:

```python
def modify_file(workspace, filename, modifications):
    """Read template file, apply targeted modifications, write back."""
    path = os.path.join(workspace, filename)
    with open(path) as f:
        lines = f.readlines()

    for mod in modifications:
        line_num = mod['line']
        col_start = mod['col_start']
        col_end = mod['col_end']
        value = mod['value']
        fmt = mod.get('format', f'{value}')  # Fortran format

        line = lines[line_num]
        lines[line_num] = line[:col_start] + fmt + line[col_end:]

    with open(path, 'w') as f:
        f.writelines(lines)
```

Column positions come from `reference/apex_formats.json` (extracted from XLSM).
This ensures we never break the fixed-width format.
