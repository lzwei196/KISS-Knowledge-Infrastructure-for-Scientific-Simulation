#!/usr/bin/env python3
"""Copy a legacy CRHM project with an explicit observation-clock correction.

Only global Time_Offset and the observation path change. Existing parameters,
dates and display variables remain intact. Clock offset and HRU longitudes must
be provided explicitly; unknown station time is never assumed to be UTC.
"""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re


def _tool(relative, name):
    path = Path(__file__).resolve().parents[1] / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _section_indices(lines, name, known):
    current = None
    indices = []
    for i, raw in enumerate(lines):
        line = raw.strip()
        title = line.rstrip(':')
        if title in known:
            current = title
        elif current == name and line and not line.startswith('######'):
            indices.append(i)
    return indices


def process(project, output, obs_path, clock_utc_offset, longitudes):
    project, output, obs_path = map(lambda p: Path(p).resolve(), (project, output, obs_path))
    if output == project or output.exists() or Path(str(output)+'.migration.json').exists():
        raise ValueError('Choose a new output path; existing projects are never overwritten')
    if not math.isfinite(clock_utc_offset) or not -12 <= clock_utc_offset <= 14:
        raise ValueError('Observation clock UTC offset must be finite and in [-12,14]')
    validator = _tool('s4_parameter_config/validate_prj.py', 'legacy_prj_validator')
    obs_validator = _tool('s2_observation_data/validate_obs_file.py', 'legacy_obs_validator')
    selector = _tool('s3_module_selection/select_modules.py', 'legacy_module_validator')
    original = project.read_text()
    sections = validator.parse_prj_sections(original)
    dims = [l.split() for l in sections.get('Dimensions', []) if l.startswith('nhru ')]
    if len(dims) != 1 or int(dims[0][1]) < 1:
        raise ValueError('Project must specify one positive nhru')
    nhru = int(dims[0][1])
    if len(longitudes) == 1:
        longitudes = list(longitudes) * nhru
    if len(longitudes) != nhru or any(not math.isfinite(x) or not -180 <= x <= 360 for x in longitudes):
        raise ValueError('Supply one longitude or one finite longitude per HRU, in [-180,360]')
    if any(l.strip() for l in sections.get('Macros', [])):
        raise ValueError('Macro projects require an explicit module-aware migration')
    modules = [l.split()[0].lstrip('+') for l in sections.get('Modules', []) if l.strip()]
    errors = [s for s in selector.validate_chain(modules, allow_later=True) if s.startswith('ERROR')]
    if errors:
        raise ValueError('; '.join(errors))
    if 'global' not in modules:
        raise ValueError('Project has no global solar-geometry module')
    if any(l.strip() for k in ('Initial_State', 'Final_State') for l in sections.get(k, [])):
        raise ValueError('State-file projects require explicit state-path handling')
    obs_report = obs_validator.process(obs_path)
    if obs_report['errors']:
        raise ValueError('Invalid observations: ' + '; '.join(obs_report['errors']))

    lines = original.splitlines(keepends=True)
    obs_indices = _section_indices(lines, 'Observations', validator.KNOWN_SECTIONS)
    if len(obs_indices) != 1:
        raise ValueError('Migration supports exactly one observation file')
    lines[obs_indices[0]] = str(obs_path) + '\n'
    indices = _section_indices(lines, 'Parameters', validator.KNOWN_SECTIONS)
    if not indices:
        raise ValueError('Missing Parameters section')
    # String parameters have no <range>; they still terminate the prior block.
    starts = [i for i in indices if re.fullmatch(
        r'[A-Za-z_]\w*\s+[A-Za-z_]\w*(?:\s+<[^>]+>)?', lines[i].strip())]
    targets = [i for i in starts if re.match(r'(?:global|Shared)\s+Time_Offset\s+<', lines[i].strip())]
    if len(targets) > 1:
        raise ValueError('Conflicting Time_Offset declarations must be resolved explicitly')
    offsets = [round((clock_utc_offset - lon/15 + 12) % 24 - 12, 8) for lon in longitudes]
    block = ['global Time_Offset <-12 to 12>\n', ' '.join(map(str, offsets)) + '\n']
    previous = None
    if targets:
        start = targets[0]
        following = next((i for i in starts if i > start), indices[-1] + 1)
        previous = ''.join(lines[start:following])
        lines[start:following] = block
    else:
        lines[indices[0]:indices[0]] = block
    corrected = ''.join(lines)
    # Verify that only the two declared fields have changed semantically.
    old_sections = validator.parse_prj_sections(original)
    new_sections = validator.parse_prj_sections(corrected)
    for section in old_sections:
        if section not in ('Observations', 'Parameters'):
            if old_sections[section] != new_sections[section]:
                raise AssertionError('Unexpected change to '+section)
    if previous is None:
        old_params = old_sections['Parameters']
    else:
        old_params = validator.parse_prj_sections(original.replace(previous, '', 1))['Parameters']
    new_params = validator.parse_prj_sections(corrected.replace(''.join(block), '', 1))['Parameters']
    if [l for l in old_params if l] != [l for l in new_params if l]:
        raise AssertionError('Unexpected change to a non-clock parameter')

    receipt = {
        'source_project': str(project), 'source_sha256': hashlib.sha256(project.read_bytes()).hexdigest(),
        'output_project': str(output), 'output_sha256': hashlib.sha256(corrected.encode()).hexdigest(),
        'observation_file': str(obs_path), 'observation_sha256': hashlib.sha256(obs_path.read_bytes()).hexdigest(),
        'clock_utc_offset_hours': clock_utc_offset, 'longitudes': longitudes,
        'global_Time_Offset_hours': offsets, 'previous_Time_Offset': previous,
        'preserved': 'All non-clock parameters, weather bytes, dates, modules, and display variables',
        'requires_fresh_simulation': True,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as f:
        f.write(corrected)
    Path(str(output)+'.migration.json').write_text(json.dumps(receipt, indent=2)+'\n')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prj_path', required=True)
    parser.add_argument('--output_path', required=True)
    parser.add_argument('--obs_path', required=True, help='The original weather file, verified against its provenance')
    parser.add_argument('--obs_utc_offset', type=float, required=True, help='Known observation clock offset from UTC; 0 for UTC')
    parser.add_argument('--longitudes', type=float, nargs='+', required=True, help='One basin longitude or one longitude per HRU')
    args = parser.parse_args()
    try:
        receipt = process(args.prj_path, args.output_path, args.obs_path, args.obs_utc_offset, args.longitudes)
    except (ValueError, OSError) as exc:
        parser.exit(2, f'ERROR: {exc}\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
