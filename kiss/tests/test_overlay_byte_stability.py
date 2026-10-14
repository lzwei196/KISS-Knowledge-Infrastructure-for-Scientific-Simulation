"""Stable composed bytes without semantic identities or acceptance exceptions."""
import hashlib
from pathlib import Path
import subprocess

import pytest
import yaml

from kiss_cli import ki_platform_overlay as overlay
from .test_ki_platform_overlay import write, generic, windows as _windows, compose
from .test_ki_guidance_composition import signed_component, run as authenticated_compose

FIXTURES = Path(__file__).parent / 'fixtures/stable_windows_guidance'


def windows(**fields):
    return {**_windows(), **fields}


def test_actual_dssat_recipe_reproduces_previous_exact_package_bytes(tmp_path):
    before, incoming = tmp_path / 'raw', tmp_path / 'main'
    raw = (FIXTURES / 'dssat_raw_windows.yaml').read_bytes()
    main = (FIXTURES / 'dssat_main_generic.yaml').read_bytes()
    expected = (FIXTURES / 'dssat_expected_windows.yaml').read_bytes()
    write(before, 'models/DSSAT/kiss.windows.yaml', raw)
    write(incoming, 'models/DSSAT/SKILL.md', 'DSSAT fixture')
    write(incoming, 'kiss/manifests/DSSAT.yaml', main)
    result = overlay.apply_windows_overlay(before, incoming, architecture='amd64',
        source_models=['DSSAT'], source_identity='fixture raw component')
    target = incoming / 'models/DSSAT/kiss.windows.yaml'
    assert target.read_bytes() == expected
    assert hashlib.sha256(expected).hexdigest() == '6be27e50a739d18753595b3e6dd4ee1b44b852c53739f0e06ffe87824b016ada'
    assert yaml.safe_load(raw)['verified'] == 'observed'
    assert yaml.safe_load(target.read_bytes())['verified'] == 'unverified'
    assert (before / 'models/DSSAT/kiss.windows.yaml').read_bytes() == raw
    assert (incoming / 'kiss/manifests/DSSAT.yaml').read_bytes() == main
    row = result['files'][0]
    assert row['mode'] == 'platform_contract_overlay'
    assert row['output']['sha256'] == hashlib.sha256(expected).hexdigest()
    assert row['source']['sha256'] == hashlib.sha256(raw).hexdigest()
    assert result['setup_reverification_required'] is True


@pytest.mark.parametrize('autocrlf', ['true', 'false', 'input'])
def test_exact_guidance_fixtures_survive_git_checkout(tmp_path, autocrlf):
    repo, checkout = tmp_path / 'repo', tmp_path / 'checkout'
    repo.mkdir()
    root = Path(__file__).resolve().parents[2]
    (repo / '.gitattributes').write_bytes((root / '.gitattributes').read_bytes())
    relative = Path('kiss/tests/fixtures/stable_windows_guidance')
    payloads = {relative / path.name: path.read_bytes() for path in FIXTURES.iterdir()
                if path.is_file()}
    # The checkout rule preserves literal bytes; it must not normalize a future
    # authenticated CRLF fixture just to make the current LF fixture pass.
    payloads[relative / 'literal_crlf.yaml'] = b'# Exact CRLF fixture\r\nmodel: Demo\r\n'
    for path, body in payloads.items():
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)

    def git(*args):
        return subprocess.run(['git', '-C', str(repo), *args], check=True,
                              capture_output=True).stdout

    git('init', '--quiet')
    git('-c', 'core.autocrlf=false', 'add', '--', '.gitattributes', relative.as_posix())
    git('-c', f'core.autocrlf={autocrlf}', 'checkout-index', '--all',
        '--prefix=' + checkout.as_posix() + '/')
    for path, body in payloads.items():
        assert git('show', ':' + path.as_posix()) == body
        assert (checkout / path).read_bytes() == body


@pytest.mark.parametrize('mode', ['three-way', 'platform'])
def test_reordered_top_level_generic_fields_produce_identical_overlay_bytes(tmp_path, mode):
    outputs = []
    for index, reverse in enumerate([False, True]):
        before, incoming = tmp_path / f'raw{index}', tmp_path / f'main{index}'
        write(before, 'models/Demo/SKILL.md', 'Demo')
        write(incoming, 'models/Demo/SKILL.md', 'Demo')
        win = windows(acquire={'strategy': 'build', 'repo': 'official', 'ref': 'pinned',
                               'commands': ['second-name-first', 'first-name-second'],
                               'produces': 'model.exe'})
        write(before, 'models/Demo/kiss.windows.yaml', win)
        if mode == 'three-way': write(before, 'models/Demo/kiss.yaml', generic())
        gen = generic(python_deps=['z-package', 'a-package'], new_metadata={'z': 1, 'a': 2})
        if reverse: gen = dict(reversed(list(gen.items())))
        upstream = write(incoming, 'models/Demo/kiss.yaml', gen)
        saved = upstream.read_bytes()
        result = compose(before, incoming)
        body = (incoming / 'models/Demo/kiss.windows.yaml').read_bytes()
        doc = yaml.safe_load(body)
        assert list(doc) == sorted(doc)
        assert doc['acquire']['commands'] == win['acquire']['commands']
        assert list(doc['acquire']) == list(win['acquire'])
        assert doc['python_deps'] == ['z-package', 'a-package']
        assert list(doc['new_metadata']) == ['z', 'a']
        assert upstream.read_bytes() == saved and result['setup_reverification_required']
        outputs.append(body)
    assert outputs[0] == outputs[1]


@pytest.mark.parametrize('mode', ['three-way', 'platform'])
def test_truly_unchanged_unverified_raw_recipe_preserves_comments_and_crlf(tmp_path, mode):
    before, incoming = tmp_path / 'raw', tmp_path / 'main'
    for root in (before, incoming): write(root, 'models/Demo/SKILL.md', 'Demo')
    old = windows(verified='unverified')
    body = b'# Exact authenticated raw bytes\r\n' + yaml.safe_dump(old, sort_keys=False).replace('\n', '\r\n').encode()
    write(before, 'models/Demo/kiss.windows.yaml', body)
    if mode == 'three-way': write(before, 'models/Demo/kiss.yaml', generic())
    write(incoming, 'models/Demo/kiss.yaml', generic())
    result = compose(before, incoming)
    assert (incoming / 'models/Demo/kiss.windows.yaml').read_bytes() == body
    assert result['setup_reverification_required'] is True


@pytest.mark.parametrize('field,value', [
    ('python_deps', ['numpy>=2']), ('depends_on', ['Routing']),
    ('data', [{'role': 'forcing', 'name': 'changed forcing'}]),
    ('runtime_data', {'source': 'new required runtime support'}),
])
def test_genuine_generic_requirements_cannot_reuse_prior_bytes(tmp_path, field, value):
    before, incoming = tmp_path / 'raw', tmp_path / 'main'
    for root in (before, incoming): write(root, 'models/Demo/SKILL.md', 'Demo')
    old = write(before, 'models/Demo/kiss.windows.yaml', windows(verified='unverified'))
    write(incoming, 'models/Demo/kiss.yaml', generic(**{field: value}))
    compose(before, incoming)
    actual = (incoming / 'models/Demo/kiss.windows.yaml').read_bytes()
    assert actual != old.read_bytes() and yaml.safe_load(actual)[field] == value


@pytest.mark.parametrize('field,value', [
    ('acquire', {'strategy': 'build', 'repo': 'new-engine', 'ref': 'new-pinned', 'produces': 'changed.exe'}),
    ('system_deps', ['new-compiler']), ('install_dir', 'different-home'),
])
def test_genuine_platform_changes_produce_different_exact_bytes(tmp_path, field, value):
    bodies = []
    for index, extra in enumerate([{}, {field: value}]):
        before, incoming = tmp_path / f'raw{index}', tmp_path / f'main{index}'
        for root in (before, incoming): write(root, 'models/Demo/SKILL.md', 'Demo')
        write(before, 'models/Demo/kiss.windows.yaml', windows(**extra))
        write(incoming, 'models/Demo/kiss.yaml', generic())
        compose(before, incoming)
        bodies.append((incoming / 'models/Demo/kiss.windows.yaml').read_bytes())
    assert bodies[0] != bodies[1] and yaml.safe_load(bodies[1])[field] == value


def test_raw_preservation_does_not_conflate_boolean_and_number(tmp_path):
    before, incoming = tmp_path / 'raw', tmp_path / 'main'
    for root in (before, incoming): write(root, 'models/Demo/SKILL.md', 'Demo')
    old = write(before, 'models/Demo/kiss.windows.yaml', windows(verified='unverified', future_value=1))
    write(incoming, 'models/Demo/kiss.yaml', generic(future_value=True))
    compose(before, incoming)
    actual = (incoming / 'models/Demo/kiss.windows.yaml').read_bytes()
    assert actual != old.read_bytes() and yaml.safe_load(actual)['future_value'] is True


@pytest.mark.parametrize('verified', ['observed', 'unverified'])
def test_authenticated_composition_records_new_exact_bytes_without_acceptance(tmp_path, monkeypatch, verified):
    monkeypatch.setenv('GEOFORGE_KI_VERIFICATION_HOME', str(tmp_path / 'receipts'))
    monkeypatch.setenv('GEOFORGE_FLOW_KEYS', str(tmp_path / 'keys'))
    raw = signed_component(tmp_path / 'raw', {'models/Demo/kiss.windows.yaml': windows(verified=verified)})
    incoming = tmp_path / 'main'
    write(incoming, 'models/Demo/SKILL.md', 'Current main science')
    write(incoming, 'models/Demo/kiss.yaml', generic())
    result = authenticated_compose(raw, incoming)
    body = (incoming / 'models/Demo/kiss.windows.yaml').read_bytes()
    assert result['files'][0]['output']['sha256'] == hashlib.sha256(body).hexdigest()
    if verified == 'unverified':
        assert body == (raw['root'] / 'models/Demo/kiss.windows.yaml').read_bytes()
    else:
        assert list(yaml.safe_load(body)) == sorted(yaml.safe_load(body))
    assert result['composition']['whole_ki_trusted'] is False
    assert result['composition']['authoring_verification'] is False
    assert result['composition']['native_regression'] == 'not_run'
