"""Document/code consistency check for dt_v007 (soil hydraulics fix of 2026-09-12).

Installed 2026-10-05 from KISSPATH_HOME/ki_defects_fixes_20261003/WOFOST/check_status.py
(H13). The first test is that check with paths adapted to this KI folder and wrapped
in a pytest function. The second test is new: it checks that the dt_v007 entries in
diagnostics/triplets.yaml and docs/format_spec.yaml describe the bug as fixed.
No model code is changed or run.
"""
import ast
from pathlib import Path

import yaml

KI = Path(__file__).resolve().parents[1]


def test_skill_status_and_production_call():
    text = (KI / 'SKILL.md').read_text()
    section = text.split('### 7. `convert_hwsd_to_pcse_soil.py`', 1)[1]
    current = section.split('#### Historical diagnosis', 1)[0]
    assert '**Status: FIXED on 2026-09-12.**' in current
    assert 'Status: OPEN' not in current
    assert 'Previously generated soil files' in current
    assert 'Historical diagnosis recorded 2026-09-09' in section
    code = ast.parse((KI / 'tools/s2_soil_params/convert_hwsd_to_pcse_soil.py').read_text())
    process = next(n for n in code.body if isinstance(n, ast.FunctionDef) and n.name == 'process')
    calls = {n.func.id for n in ast.walk(process) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert '_shared_ptf' in calls and 'pedotransfer_wosten' not in calls


def _entry(rel):
    doc = yaml.safe_load((KI / rel).read_text())
    items = doc if isinstance(doc, list) else [x for v in doc.values() if isinstance(v, list) for x in v]
    found = [x for x in items if isinstance(x, dict) and x.get('id') == 'dt_v007']
    assert len(found) == 1, rel
    return found[0]


def test_yaml_entries_say_fixed():
    for rel in ['diagnostics/triplets.yaml', 'docs/format_spec.yaml']:
        e = _entry(rel)
        diagnosis = e['diagnosis']['root_cause'] if isinstance(e['diagnosis'], dict) else e['diagnosis']
        assert diagnosis.startswith('FIXED 2026-09-12'), rel
        assert 'saxton_rawls' in diagnosis and 'x 24' in diagnosis, rel
        symptom = e['symptom']['description'] if isinstance(e['symptom'], dict) else e['symptom']
        assert symptom.startswith('HISTORICAL'), rel
        # sync2 r1 (codex): the file date must not decide whether a soil file is affected.
        assert 'can only come from' not in symptom, rel
        assert 'not decide' in symptom.lower(), rel
        remedy = e['remedy']['action'] if isinstance(e['remedy'], dict) else e['remedy']
        assert 'provenance' in remedy and 'match' in remedy.lower(), rel
        assert 'made before 2026-09-12' not in remedy, rel
        # sync2 r2 (codex): replace only on positive evidence of the old formula; keep other files.
        assert 'matches_legacy_formula' in remedy and '_legacy_doc_ptf' in remedy, rel
        assert 'keep the file' in remedy.lower() or 'do not overwrite' in remedy.lower(), rel


def _converter_manual(tmp_path, monkeypatch):
    """Run the converter's manual-texture path in-process (no HWSD raster needed)."""
    import importlib.util, json
    spec = importlib.util.spec_from_file_location(
        'conv', KI / 'tools/s2_soil_params/convert_hwsd_to_pcse_soil.py')
    conv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(conv)
    conv.SAND_PCT, conv.CLAY_PCT, conv.SILT_PCT, conv.OC_PCT = 40.0, 20.0, 40.0, 1.0
    out = tmp_path / 'soil_params.json'
    monkeypatch.setenv('SOIL_PARAMS_JSON', str(out))
    sp = conv.process()
    conv.validate_outputs(sp)
    out.write_text(json.dumps(sp))
    return out, sp


def _run_validator(path):
    import subprocess, sys, json
    r = subprocess.run([sys.executable, str(KI / 'tools/s2_soil_params/validate_soil_params.py'), str(path)],
                       capture_output=True, text=True, timeout=60)
    return r.returncode, (json.loads(r.stdout) if r.stdout.strip() else None)


def test_validator_accepts_converter_output(tmp_path, monkeypatch):
    out, sp = _converter_manual(tmp_path, monkeypatch)
    assert len(sp) == 8
    rc, rep = _run_validator(out)
    assert rc == 0 and rep['status'] == 'PASS', rep


def test_validator_flags_site_keys_and_missing_keys(tmp_path, monkeypatch):
    import json
    out, sp = _converter_manual(tmp_path, monkeypatch)
    bad = dict(sp, WAV=20.0)                       # site key in soildata -> PCSE duplicate (dt_v003)
    out.write_text(json.dumps(bad))
    rc, rep = _run_validator(out)
    assert rc == 2 and any(c['check'] == 'no_site_keys_in_soil' and c['status'] == 'FAIL' for c in rep['checks'])
    missing = {k: v for k, v in sp.items() if k != 'SMW'}  # missing key: FAIL, never read as 0
    out.write_text(json.dumps(missing))
    rc, rep = _run_validator(out)
    assert rc == 2
    smw_check = next(c for c in rep['checks'] if c['check'] == 'SMW_lt_SMFCF')
    assert smw_check['status'] == 'FAIL' and 'not checked' in smw_check['message']


def test_skill_doc_steps_2_to_5_run(tmp_path, monkeypatch):
    """sync2 r1 (codex): the manual workflow must define every name it uses."""
    import re
    out, _ = _converter_manual(tmp_path, monkeypatch)   # writes soil_params.json + .provenance.json
    doc = (KI / 'docs/s2_soil_params_skill.md').read_text()
    body = doc.split('### Step 2:', 1)[1].split('## Expected Outputs', 1)[0]
    blocks = re.findall(r'```python\n(.*?)```', body, re.S)
    # Block 2 is the hand-built alternative (needs a live HWSD lookup); run the tool route.
    tool_route = [b for b in blocks if 'lookup_hwsd' not in b]
    assert len(tool_route) == 4, len(tool_route)
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'outputs/r1/wofost').mkdir(parents=True)
    ns = {'run_name': 'r1'}
    for b in tool_route:
        exec(compile(b, 'doc', 'exec'), ns)
    assert set(ns['soil_params']) == {'SMW', 'SMFCF', 'SM0', 'CRAIRC', 'K0', 'SOPE', 'KSUB', 'RDMSOL'}
    assert (tmp_path / 'outputs/r1/wofost/soil_params.json').exists()


def test_validator_rejects_unusable_values(tmp_path, monkeypatch):
    """sync2 r2 (codex): null / negative / infinite values must not PASS."""
    import json
    out, sp = _converter_manual(tmp_path, monkeypatch)
    for key, bad in [('SOPE', None), ('KSUB', -1.0), ('SOPE', -0.5), ('SMW', -0.05), ('K0', 'inf'),
                     ('CRAIRC', 0.0)]:
        d = dict(sp)
        d[key] = float('inf') if bad == 'inf' else bad
        out.write_text(json.dumps(d))          # json writes inf as Infinity; json.load reads it back
        rc, rep = _run_validator(out)
        assert rc == 2 and rep['status'] == 'FAIL', (key, rep)


def test_legacy_ptf_check_is_usable():
    """The dt_v007 remedy relies on _legacy_linear_ptf() to spot old-formula files."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'conv2', KI / 'tools/s2_soil_params/convert_hwsd_to_pcse_soil.py')
    conv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(conv)
    smw, smfcf, sm0, k0 = conv._legacy_linear_ptf(40.0, 20.0, 40.0, 1.0, 1.4)
    assert 0 < smw < smfcf < sm0
    from ki_tools_common.soil_utils import saxton_rawls
    hyd = saxton_rawls(40.0, 20.0, om=1.724)
    assert round(smfcf, 4) != round(float(hyd['field_capacity']), 4)


def test_validator_allows_zero_percolation(tmp_path, monkeypatch):
    """sync2 r3 (codex): PCSE uses limit(0, SOPE/KSUB, ...); KSUB=0 (no subsoil drainage) is valid."""
    import json
    out, sp = _converter_manual(tmp_path, monkeypatch)
    out.write_text(json.dumps(dict(sp, SOPE=0.0, KSUB=0.0)))
    rc, rep = _run_validator(out)
    assert rc == 0 and rep['status'] == 'PASS', rep


def test_matches_legacy_formula_both_old_versions():
    """sync2 r3 (codex): recognise files from the old tool AND the old doc formula; keep others."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'conv3', KI / 'tools/s2_soil_params/convert_hwsd_to_pcse_soil.py')
    conv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(conv)
    tex = dict(sand=40.0, clay=20.0, silt=40.0, oc=1.0, bd=1.4)
    # File written by the old Step-2 doc (codex r3 reproduced these values from the old doc text).
    old_doc = {'SMW': 0.054, 'SMFCF': 0.137, 'SM0': 0.472, 'K0': 13.6}
    assert conv.matches_legacy_formula(old_doc, **tex) in ('legacy_tool', 'legacy_doc')
    # Where the two old formulas differ (here a clamp: SM0 below the old tool's 0.30 floor), the doc one is found.
    tex2 = dict(sand=40.0, clay=20.0, silt=40.0, oc=1.0, bd=1.95)
    s, f, z, k = conv._legacy_doc_ptf(40.0, 20.0, 1.0, 1.95)
    assert conv.matches_legacy_formula({'SMW': round(s, 3), 'SMFCF': round(f, 3), 'SM0': round(z, 3),
                                        'K0': round(k, 1)}, **tex2) == 'legacy_doc'
    # File written by the old tool (its rounding: 4 decimals, K0 2 decimals).
    a, b, c, d = conv._legacy_linear_ptf(**tex)
    old_tool = {'SMW': round(a, 4), 'SMFCF': round(b, 4), 'SM0': round(c, 4), 'K0': round(d, 2)}
    assert conv.matches_legacy_formula(old_tool, **tex) in ('legacy_tool', 'legacy_doc')
    # Current shared hydraulics and a measured-looking soil: not old-formula, must be kept.
    from ki_tools_common.soil_utils import saxton_rawls
    hyd = saxton_rawls(40.0, 20.0, om=1.724)
    cur = {'SMW': hyd['wilting_point'], 'SMFCF': hyd['field_capacity'], 'SM0': hyd['saturation'],
           'K0': hyd['ksat_cm_hr'] * 24}
    assert conv.matches_legacy_formula(cur, **tex) is None
    assert conv.matches_legacy_formula({'SMW': 0.11, 'SMFCF': 0.29, 'SM0': 0.45, 'K0': 30.0}, **tex) is None
