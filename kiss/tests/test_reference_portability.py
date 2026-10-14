"""Reference provenance is preserved; mandatory runtime paths still block."""
import hashlib
import json
import textwrap

import pytest

from kiss_cli import doctor, reference_portability
from kiss_cli.catalog import KI

SERVER = '/mnt/disk1/Hydrocraft_server/model/demo/bin/demo'


def package(tmp_path, filename, text):
    root = tmp_path / 'Demo'
    root.mkdir(exist_ok=True)
    (root / 'SKILL.md').write_text('Demo')
    (root / 'preflight_check.py').write_text('print("check")\n')
    file = root / filename
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(textwrap.dedent(text).encode())
    return KI('Demo', root), file


def blocked(ki):
    return [f for f in doctor.check_ki(ki) if f.check == 'hardcoded-paths']


BASE = '''\
import argparse, os, shutil, subprocess
from pathlib import Path
DEFAULT = "PATH_VALUE"
def find_binary(arg):
    for candidate in (arg, os.environ.get('DEMO_BIN'), shutil.which('demo'), DEFAULT):
        if candidate and Path(candidate).exists():
            return candidate
    return None
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--demo-bin')
    args = parser.parse_args()
    binary = find_binary(args.demo_bin)
'''.replace('PATH_VALUE', SERVER)


def test_actual_style_function_fallback_is_proven_without_rewriting(tmp_path):
    ki, file = package(tmp_path, 'test_cases/demo/run_reference.py', BASE)
    before = hashlib.sha256(file.read_bytes()).hexdigest()
    assert not blocked(ki)
    rows = reference_portability.classify_reference_paths(ki)['test_cases/demo/run_reference.py']
    assert rows[0]['classification'] == 'configurable_default'
    assert hashlib.sha256(file.read_bytes()).hexdigest() == before
    warnings = doctor.check_ki(ki)
    assert any(f.check == 'reference-case-binding' and 'not performed' in f.detail for f in warnings)


@pytest.mark.parametrize('field', ['recorded_with', 'engine_version', 'run_tweak'])
def test_known_expected_provenance_field_is_retained(tmp_path, field):
    body = json.dumps({field: 'Recorded using ' + SERVER, 'numeric_checks': [{'expected': 1, 'tol': 0.1}]})
    ki, file = package(tmp_path, 'test_cases/demo/expected.json', body)
    assert not blocked(ki) and file.read_text() == body


@pytest.mark.parametrize('field', ['binary', 'default_binary', 'binary_default', 'python', 'source'])
def test_known_manifest_engine_metadata_requires_binding(tmp_path, field):
    ki, file = package(tmp_path, 'test_cases/demo/manifest.json', json.dumps({'engine': {field: SERVER}, 'files': {}}))
    assert not blocked(ki)
    assert reference_portability.classify_reference_paths(ki)['test_cases/demo/manifest.json'][0]['classification'] == 'runtime_binding_metadata'


@pytest.mark.parametrize('file,body', [
    ('tools/run.py', BASE),
    ('test_cases/demo/inputs/README.md', SERVER),
    ('test_cases/demo/inputs/data.json', json.dumps({'recorded_with': SERVER})),
    ('test_cases/demo/expected.json', json.dumps({'numeric_checks': [{'file': SERVER}]})),
    ('test_cases/demo/manifest.json', json.dumps({'files': {SERVER: {'sha256': 'x'}}})),
])
def test_core_inputs_and_scientific_fields_stay_strict(tmp_path, file, body):
    ki, _ = package(tmp_path, file, body)
    assert blocked(ki)


@pytest.mark.parametrize('source', [
    BASE + '\nsubprocess.run([DEFAULT])\n',
    BASE + '\nprint(subprocess.run([DEFAULT]))\n',
    BASE + '\nprint = subprocess.run\nprint(DEFAULT)\n',
    BASE.replace('if candidate and Path(candidate).exists():', 'subprocess.run([candidate])\n        if candidate and Path(candidate).exists():'),
    BASE.replace('if candidate and Path(candidate).exists():', 'if False:'),
    BASE.replace('binary = find_binary(args.demo_bin)', 'args.demo_bin = None\n    binary = find_binary(args.demo_bin)'),
    BASE.replace('binary = find_binary(args.demo_bin)', 'args = object()\n    binary = find_binary(args.demo_bin)'),
    BASE.replace('binary = find_binary(args.demo_bin)', 'alias = find_binary\n    binary = alias(args.demo_bin)'),
    BASE.replace('parser.parse_args()', 'parser.parse_args([])'),
    'import subprocess\nclass Fake: pass\nfake=Fake()\nfake.add_argument("--x",default="'+SERVER+'")',
    'import argparse\nargparse=other\np=argparse.ArgumentParser()\np.add_argument("--x",default="'+SERVER+'")',
])
def test_unproven_or_mandatory_execution_paths_remain_blocked(tmp_path, source):
    ki, _ = package(tmp_path, 'test_cases/demo/run_reference.py', source)
    assert blocked(ki)


def test_direct_tracked_argparse_default_is_configurable(tmp_path):
    source = 'import argparse\np=argparse.ArgumentParser()\np.add_argument("--bin",default="'+SERVER+'")\na=p.parse_args()\n'
    ki, _ = package(tmp_path, 'test_cases/demo/run_reference.py', source)
    assert not blocked(ki)


def test_string_diagnostic_is_provenance(tmp_path):
    ki, _ = package(tmp_path, 'test_cases/demo/run_reference.py', 'print("Missing original '+SERVER+'")\n')
    assert not blocked(ki)


PATH_FALLBACK = '''\
import os, shutil
DEFAULT = '/home/server/.local/bin'
def main():
    env = dict(os.environ)
    if not shutil.which('mpirun'):
        env['PATH'] = DEFAULT + os.pathsep + env.get('PATH', '')
    if not shutil.which('mpirun', path=env['PATH']):
        print('missing mpirun; not run')
        return 3
'''


def test_guarded_preserved_path_fallback_is_configurable(tmp_path):
    ki, _ = package(tmp_path, 'test_cases/demo/run_reference.py', PATH_FALLBACK)
    assert not blocked(ki)


@pytest.mark.parametrize('source', [
    PATH_FALLBACK.replace("if not shutil.which('mpirun'):", 'if True:'),
    PATH_FALLBACK.replace("DEFAULT + os.pathsep + env.get('PATH', '')", 'DEFAULT'),
    PATH_FALLBACK.replace("path=env['PATH']", "path='other'"),
    PATH_FALLBACK.replace("if not shutil.which('mpirun'):", "if shutil.which('mpirun'):"),
    PATH_FALLBACK + '\nimport subprocess\nsubprocess.run([DEFAULT])\n',
])
def test_unguarded_or_unverified_path_writes_stay_blocked(tmp_path, source):
    ki, _ = package(tmp_path, 'test_cases/demo/run_reference.py', source)
    assert blocked(ki)


PROBE = BASE.replace('if candidate and Path(candidate).exists():\n            return candidate',
    "if not candidate or not Path(candidate).exists():\n            continue\n        cp = subprocess.run([candidate, '-c', CODE], capture_output=True)\n        if cp.returncode == 0:\n            return candidate")


@pytest.mark.parametrize('code', ['import numpy', "import importlib.metadata as m; print(m.version('numpy'))"])
def test_candidate_import_metadata_probe_is_only_a_binding_check(tmp_path, code):
    source = PROBE.replace('def find_binary(arg):', 'CODE = '+repr(code)+'\ndef find_binary(arg):')
    ki, _ = package(tmp_path, 'test_cases/demo/run_reference.py', source)
    assert not blocked(ki)


@pytest.mark.parametrize('code', ['import os; os.system("model")', 'import numpy as np; print(np.ones(10))'])
def test_arbitrary_probe_commands_are_not_import_checks(tmp_path, code):
    source = PROBE.replace('def find_binary(arg):', 'CODE = '+repr(code)+'\ndef find_binary(arg):')
    ki, _ = package(tmp_path, 'test_cases/demo/run_reference.py', source)
    assert blocked(ki)


def test_probe_does_not_accept_continued_execution_after_success(tmp_path):
    source = PROBE.replace('def find_binary(arg):', 'CODE = "import numpy"\ndef find_binary(arg):')
    source = source.replace('return candidate', 'break')
    ki, _ = package(tmp_path, 'test_cases/demo/run_reference.py', source)
    assert blocked(ki)


@pytest.mark.parametrize('predicate,expected_block', [('os.path.isfile', False),
    ('lambda p: os.path.isfile(p) and os.access(p, os.X_OK)', False),
    ('lambda p: subprocess.run([p]).returncode == 0', True)])
def test_candidate_callback_requires_pure_file_predicate(tmp_path, predicate, expected_block):
    source = BASE[:BASE.index('def find_binary')] + '''
def first(candidates, ok):
    return next((c for c in candidates if c and ok(c)), None)
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--demo-bin')
    args = parser.parse_args()
    binary = first((args.demo_bin, DEFAULT), PREDICATE)
'''.replace('PREDICATE', predicate)
    ki, _ = package(tmp_path, 'test_cases/demo/run_reference.py', source)
    assert bool(blocked(ki)) is expected_block


@pytest.mark.parametrize('code,expected_block', [('import pyswmm, swmm.toolkit', False),
    ('import os; os.system("model")', True)])
def test_named_import_predicate_is_bounded(tmp_path, code, expected_block):
    source = BASE[:BASE.index('def find_binary')] + '''
def can_import(py):
    try:
        return subprocess.run([py, '-c', CODE], capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--demo-bin')
    args = parser.parse_args()
    candidates = (args.demo_bin, DEFAULT)
    binary = next((c for c in candidates if c and can_import(c)), None)
'''.replace('CODE', repr(code))
    ki, _ = package(tmp_path, 'test_cases/demo/run_reference.py', source)
    assert bool(blocked(ki)) is expected_block


OPTION_FALLBACK = '''\
import argparse, os
from pathlib import Path
DEFAULT = '/home/server/engine/install/wrapper'
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--wrapper')
    ap.add_argument('--binary')
    a = ap.parse_args()
    if not (a.wrapper or a.binary) and Path(DEFAULT).is_file():
        a.wrapper = DEFAULT
'''


@pytest.mark.parametrize('source', [OPTION_FALLBACK,
    OPTION_FALLBACK.replace('a.wrapper or a.binary', 'a.wrapper or os.environ.get("WASP_PREFIX")').replace('.is_file()', '.is_dir()')])
def test_parsed_option_fallback_preserves_explicit_binding(tmp_path, source):
    ki, _ = package(tmp_path, 'test_cases/demo/run_reference.py', source)
    assert not blocked(ki)


@pytest.mark.parametrize('source', [
    OPTION_FALLBACK.replace('not (a.wrapper or a.binary)', '(a.wrapper or a.binary)'),
    OPTION_FALLBACK.replace('not (a.wrapper or a.binary)', 'not a.binary'),
    OPTION_FALLBACK.replace('Path(DEFAULT).is_file()', 'True'),
    OPTION_FALLBACK.replace("ap.add_argument('--binary')", "ap.add_argument('--binary')\n    ap.add_argument('--other')").replace('a.wrapper = DEFAULT', 'a.other = DEFAULT'),
    OPTION_FALLBACK.replace('a = ap.parse_args()', 'a = ap.parse_args()\n    a.wrapper = None'),
    OPTION_FALLBACK + '\nimport subprocess\nsubprocess.run([DEFAULT])\n',
])
def test_option_fallback_cannot_overwrite_or_bypass_explicit_binding(tmp_path, source):
    ki, _ = package(tmp_path, 'test_cases/demo/run_reference.py', source)
    assert blocked(ki)


BRANCH_FALLBACK = '''\
import argparse, os, shutil
DEFAULT = "PATH_VALUE"
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--binary')
    a = ap.parse_args()
    if a.binary:
        binary, source = a.binary, '--binary'
    elif os.environ.get('DEMO_BIN'):
        binary, source = os.environ['DEMO_BIN'], 'environment'
    else:
        binary, source = DEFAULT, 'server default'
    return binary
'''.replace('PATH_VALUE', SERVER)


def test_cli_if_elif_tuple_selection_is_overridable(tmp_path):
    ki, _ = package(tmp_path, 'test_cases/demo/run_reference.py', BRANCH_FALLBACK)
    assert not blocked(ki)


@pytest.mark.parametrize('source', [
    BRANCH_FALLBACK.replace('if a.binary:', 'if a.unrelated:'),
    BRANCH_FALLBACK.replace("a.binary, '--binary'", "None, '--binary'"),
    BRANCH_FALLBACK.replace("binary, source = a.binary", "ignored, source = a.binary"),
    BRANCH_FALLBACK.replace('a = ap.parse_args()', 'a = ap.parse_args()\n    a.binary = None'),
    BRANCH_FALLBACK.replace('a = ap.parse_args()', 'a = ap.parse_args()\n    a: object = other'),
    BRANCH_FALLBACK.replace('return binary', 'binary = DEFAULT\n    return binary'),
    BRANCH_FALLBACK + '\nrun(DEFAULT)\n',
])
def test_branch_override_must_control_the_actual_default(tmp_path, source):
    ki, _ = package(tmp_path, 'test_cases/demo/run_reference.py', source)
    assert blocked(ki)


EARLY_SELECTOR = '''\
import argparse, os, shutil
DEFAULT = "PATH_VALUE"
class Missing(Exception):
    pass
def select_binary(arg):
    explicit = [('--binary', arg), ('environment', os.environ.get('DEMO_BIN'))]
    for label, candidate in explicit:
        if candidate:
            if not os.path.isfile(candidate):
                raise Missing('missing')
            version = binary_version(candidate)
            if version != '1.0':
                raise Missing('version')
            return candidate
    for candidate in (shutil.which('demo'), DEFAULT):
        if candidate and os.path.isfile(candidate) and binary_version(candidate) == '1.0':
            return candidate
    raise Missing(f'no binary; server default {DEFAULT}')
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--binary')
    a = ap.parse_args()
    return select_binary(a.binary)
'''.replace('PATH_VALUE', SERVER)


def test_explicit_selector_returns_before_fallback_and_version_probe(tmp_path):
    ki, _ = package(tmp_path, 'test_cases/demo/run_reference.py', EARLY_SELECTOR)
    assert not blocked(ki)


@pytest.mark.parametrize('source', [
    EARLY_SELECTOR.replace('return candidate', 'break', 1),
    EARLY_SELECTOR.replace("raise Missing('version')", 'continue'),
    EARLY_SELECTOR.replace("('--binary', arg)", "('--binary', None)"),
    EARLY_SELECTOR.replace('select_binary(a.binary)', 'select_binary(None)'),
    EARLY_SELECTOR.replace('if candidate:', 'if False:', 1),
    EARLY_SELECTOR.replace('for label, candidate in explicit:', 'explicit[0] = ("ignored", None)\n    for label, candidate in explicit:'),
    EARLY_SELECTOR.replace('def select_binary(arg):', 'def select_binary(arg):\n    arg: str = None'),
    EARLY_SELECTOR.replace('def select_binary(arg):', 'def select_binary(arg):\n    arg += "ignored"'),
    EARLY_SELECTOR.replace('def select_binary(arg):', 'def select_binary(arg):\n    (arg := None)'),
    EARLY_SELECTOR.replace('def select_binary(arg):', 'def select_binary(arg):\n    del arg'),
])
def test_fallback_selector_requires_unmodified_early_exit(tmp_path, source):
    ki, _ = package(tmp_path, 'test_cases/demo/run_reference.py', source)
    assert blocked(ki)


ENV_SELECTOR = '''\
import os as _os
def downloader():
    import shutil as _sh
    for candidate in (_os.environ.get('BAIDUPCS_BIN'), _sh.which('BaiduPCS-Py'), 'PATH_VALUE'):
        if candidate and _os.path.isfile(candidate) and _os.access(candidate, _os.X_OK):
            return candidate
    return None
'''.replace('PATH_VALUE', SERVER)


def test_env_path_last_default_selector_supports_verified_import_aliases(tmp_path):
    ki, _ = package(tmp_path, 'test_cases/demo/run_reference.py', ENV_SELECTOR)
    assert not blocked(ki)


@pytest.mark.parametrize('source', [
    ENV_SELECTOR.replace("_os.environ.get('BAIDUPCS_BIN')", 'None'),
    ENV_SELECTOR.replace('import os as _os', 'import fake_os as _os'),
    ENV_SELECTOR.replace('import shutil as _sh', 'import shutil as _sh\n    _os = fake'),
    ENV_SELECTOR.replace('import shutil as _sh', "import shutil as _sh\n    _os.environ['BAIDUPCS_BIN'] = ''"),
    ENV_SELECTOR.replace('import shutil as _sh', 'import shutil as _sh\n    _os.environ.clear()'),
    ENV_SELECTOR.replace('import shutil as _sh', 'import shutil as _sh\n    env = _os.environ\n    env.clear()'),
    ENV_SELECTOR.replace('import os as _os', 'import os as _os\nfrom fake_os import os as _os'),
    ENV_SELECTOR.replace('return candidate', 'break'),
    ENV_SELECTOR.replace('if candidate and', 'run(candidate)\n        if candidate and'),
])
def test_env_selector_does_not_hide_mutation_or_execution(tmp_path, source):
    ki, _ = package(tmp_path, 'test_cases/demo/run_reference.py', source)
    assert blocked(ki)


PACK_SELECTOR = '''\
import argparse, json, os
from pathlib import Path
HERE = Path(__file__).resolve().parent
MAN = json.loads((HERE / 'manifest.json').read_text())
def resolve_pack(pack, explicit_arg):
    explicit = explicit_arg or os.environ.get('DEMO_PACK_DIR')
    if explicit:
        if not Path(explicit).is_dir():
            raise ValueError('missing pack')
        check_pack(explicit, pack['files'])
        return explicit
    if Path(pack['server_default']).is_dir():
        check_pack(pack['server_default'], pack['files'])
        return pack['server_default']
    return download_pack(pack)
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pack-dir')
    a = ap.parse_args()
    return resolve_pack(MAN['pack'], a.pack_dir)
'''


def _pack_case(tmp_path, runner):
    ki, _ = package(tmp_path, 'test_cases/demo/manifest.json',
                    json.dumps({'pack': {'server_default': SERVER, 'files': {}}}))
    (ki.root / 'test_cases/demo/run_reference.py').write_text(runner)
    return ki


def test_manifest_pack_default_needs_companion_explicit_override_proof(tmp_path):
    ki = _pack_case(tmp_path, PACK_SELECTOR)
    assert not blocked(ki)
    rows = reference_portability.classify_reference_paths(ki)['test_cases/demo/manifest.json']
    assert rows[0]['classification'] == 'runtime_binding_metadata'


@pytest.mark.parametrize('runner', [
    '', PACK_SELECTOR.replace('return explicit', 'pass'),
    PACK_SELECTOR.replace('resolve_pack(MAN[\'pack\'], a.pack_dir)', 'resolve_pack(MAN[\'pack\'], None)'),
    PACK_SELECTOR.replace("'manifest.json'", "'other.json'"),
    PACK_SELECTOR + "\nrun(MAN['pack']['server_default'])\n",
    PACK_SELECTOR + "\nrun(MAN['pack'])\n",
    PACK_SELECTOR + "\nrun(MAN['pack']['server_' + 'default'])\n",
    PACK_SELECTOR.replace('    if explicit:', '    explicit: str = None\n    if explicit:'),
    PACK_SELECTOR.replace('    if explicit:', '    execute(pack)\n    if explicit:'),
    PACK_SELECTOR.replace('    if explicit:', '    def hidden():\n        return pack["server_" + "default"]\n    execute(hidden())\n    if explicit:'),
    PACK_SELECTOR.replace('if explicit:', 'if False:'),
    PACK_SELECTOR.replace('a = ap.parse_args()', 'a = ap.parse_args()\n    a.pack_dir = None'),
])
def test_pack_metadata_is_not_blanket_exempted(tmp_path, runner):
    assert blocked(_pack_case(tmp_path, runner))


@pytest.mark.parametrize('filename,body', [
    ('expected.json', json.dumps({'notes': ['Historical build ' + SERVER], 'numeric_checks': []})),
    ('manifest.json', json.dumps({'engine': {'build': 'Build notes: ' + SERVER}})),
    ('run_reference.py', '# Historical build ' + SERVER + '\nprint("ready")\n'),
])
def test_narrow_reference_comments_and_build_notes_are_provenance(tmp_path, filename, body):
    ki, file = package(tmp_path, 'test_cases/demo/' + filename, body)
    before = file.read_bytes()
    assert not blocked(ki)
    assert file.read_bytes() == before


@pytest.mark.parametrize('body', [
    json.dumps({'notes': {'execute': SERVER}}),
    json.dumps({'notes': [SERVER], 'numeric_checks': [{'file': SERVER}]}),
])
def test_notes_cannot_exempt_paths_used_by_scientific_fields(tmp_path, body):
    ki, _ = package(tmp_path, 'test_cases/demo/expected.json', body)
    assert blocked(ki)
