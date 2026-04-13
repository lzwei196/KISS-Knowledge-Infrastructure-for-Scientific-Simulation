# Project Structure Setup — Skill Document

> **Stage ID**: s1_project_setup
> **Pipeline order**: 1 of 10
> **Depends on**: none

## Purpose

Create the LDNDC project directory structure and generate the master `project.xml` configuration file that defines simulation schedule, geographic coordinates, input file sources, and output destinations. All subsequent stages depend on this structure existing.

## Prerequisites

Before starting this stage, verify:

- [ ] LDNDC binary is installed and accessible at the expected path
- [ ] Target output directory parent exists and is writable
- [ ] Basin coordinates (lat/lon) and simulation period (start/end dates) are known
- [ ] Python environment activated: `source /mnt/disk1/Hydrocraft_server/python_env/bin/activate`

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| project_dir | directory | User-specified | Root directory for this LDNDC simulation |
| basin_name | string | User-specified | Identifier used for file naming |
| lat | number | Basin delineation or user | Latitude in decimal degrees |
| lon | number | Basin delineation or user | Longitude in decimal degrees |
| start_date | string | User-specified | Simulation start (YYYY-MM-DD) |
| end_date | string | User-specified | Simulation end (YYYY-MM-DD) |

## Procedure

### Step 1: Create project directory structure

```bash
python tools/s1_project_setup/create_project_structure.py
```

Set `project_dir` and `basin_name` before running. This creates:
```
{project_dir}/
  input/
  output/
```

**Expected result**: Directory exists with `input/` and `output/` subdirectories.

**If this fails**: Check parent directory exists and is writable.

### Step 2: Generate project.xml

```bash
python tools/s1_project_setup/generate_project_xml.py
```

Set `project_dir`, `lat`, `lon`, `start_date`, `end_date` before running.

**Expected result**: `project.xml` exists at `{project_dir}/project.xml` with content like:

```xml
<ldndcproject id="0" lat="33.5" lon="117.2">
  <schedule time="2000-01-01/24 -> 2010-12-31"/>
  <input>
    <sources sourceprefix="input/">
      <site source="site.xml"/>
      <event source="mana.xml"/>
      <setup source="setup.xml"/>
      <climate source="climate.txt"/>
      <airchemistry source="airchem.txt"/>
      <speciesparameters source="parameters_species.xml"/>
      <siteparameters source="parameters_site.xml"/>
    </sources>
    <attributes use="0">
      <airchemistry endless="yes"/>
    </attributes>
  </input>
  <output>
    <sinks sinkprefix="output/"/>
  </output>
</ldndcproject>
```

**If this fails**: See diagnostic triplet dt_001.

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| Project directory | `{project_dir}/` | Directory exists with input/ and output/ subdirs |
| project.xml | `{project_dir}/project.xml` | Well-formed XML; `xmllint --noout project.xml` returns 0 |

## Validation Checks

1. **Directory structure**: Verify `input/` and `output/` exist inside project_dir
2. **XML validity**: Parse project.xml; check it has `ldndcproject`, `schedule`, `input`, `output` elements
3. **Schedule dates**: Verify start_date < end_date and both are valid ISO 8601 dates
4. **Source prefix**: Verify `sourceprefix` ends with `/`

## Common Pitfalls

> **PITFALL**: sourceprefix missing trailing slash
> The `sourceprefix` attribute in project.xml must end with `/`. Without it, LDNDC concatenates prefix+filename without a separator (e.g., `inputsite.xml` instead of `input/site.xml`).
> **Do this instead**: Always ensure sourceprefix = "input/"
> See diagnostic triplet dt_001 for full details.

> **PITFALL**: Using absolute paths in project.xml
> If project.xml uses absolute paths and the project is moved to a different location, all paths break. Use relative paths from the project.xml directory.
> **Do this instead**: Use relative sourceprefix (e.g., "input/") and run LDNDC from the project directory.

---

*This skill document is part of the ldndc-knowledge-infrastructure package.*
*Stage 1 of 10 | Tools used: create_project_structure, generate_project_xml | Related triplets: dt_001*
