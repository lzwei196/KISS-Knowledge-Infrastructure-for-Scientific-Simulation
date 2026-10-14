"""Real guarded-worker recovery; isolated fixture projects, never native models."""
import hashlib
import json
from pathlib import Path

import pytest

from kiss_cli import api, project_data_tools
from .test_project_data_tools import CSV_READER, case, approve, run


@pytest.fixture(autouse=True)
def isolated_host_state(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "host-keys"))
    monkeypatch.setenv("GEOFORGE_FLOW_REGISTRY", str(tmp_path / "host-registry"))


def recovery_case(tmp_path, source=CSV_READER):
    c = case(tmp_path, source)
    c[4]["items"].append({"id": "inspection", "status": "missing", "local_paths": ["outputs/inspection.json"]})
    target = c[1] / "outputs/inspection.json"
    target.parent.mkdir()
    target.write_text("unreceipted original", encoding="utf-8")
    return c, target


def receipt(result):
    summary = json.loads(result.splitlines()[1].split("[RECEIPT] ", 1)[1])
    path = Path(summary["receipt"])
    return path, json.loads(path.read_text(encoding="utf-8"))


def assert_preimage(c, doc, expected):
    history = doc["validation"]["output_preimages"]
    manifest_path = c[1] / history["manifest"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == history["sha256"]
    assert c[2].flow.receipts.verify(c[1], manifest)
    assert manifest["approval_sha256"] == doc["approval_sha256"]
    assert manifest["plan_step_id"] == "M:read"
    assert manifest["outputs"] == history["outputs"]
    row, = history["outputs"]
    assert row["path"] == "outputs/inspection.json"
    assert (c[1] / row["preimage_path"]).read_bytes() == expected
    assert row["sha256"] == hashlib.sha256(expected).hexdigest()


def test_exact_approved_existing_output_is_replaced_with_signed_original_history(tmp_path):
    c, target = recovery_case(tmp_path)
    old = target.read_bytes()
    raw = (c[1] / "inputs/raw.csv").read_bytes()
    approve(c)
    result = run(c)
    assert result.startswith("exit_code=0"), result
    path, doc = receipt(result)
    assert c[2].flow.receipts.verify(c[1], doc)
    assert doc["validation"]["status"] == "passed"
    assert json.loads(target.read_text(encoding="utf-8"))["count"] == 2
    assert (c[1] / "inputs/raw.csv").read_bytes() == raw
    assert_preimage(c, doc, old)
    assert c[2].evidence()["receipts_verified"]


def test_failed_partial_write_keeps_original_then_same_approval_retry_passes(tmp_path):
    source = """from pathlib import Path
p=Path('outputs/inspection.json')
if p.read_text(encoding='utf-8') == 'unreceipted original':
    p.write_text('{partial', encoding='utf-8')
    raise RuntimeError('fixture fails after a partial write')
""" + CSV_READER
    c, target = recovery_case(tmp_path, source)
    old = target.read_bytes()
    approve(c)
    result = run(c)
    assert result.startswith("exit_code=1"), result
    failed_path, failed = receipt(result)
    failed_bytes = failed_path.read_bytes()
    assert failed["validation"]["status"] == "failed"
    assert_preimage(c, failed, old)
    assert target.read_text(encoding="utf-8") == '{partial'
    result = run(c)
    assert result.startswith("exit_code=0"), result
    _, passed = receipt(result)
    assert passed["approval_sha256"] == failed["approval_sha256"]
    assert_preimage(c, passed, b'{partial')
    assert failed_path.read_bytes() == failed_bytes
    assert c[2].evidence()["receipts_verified"]
    assert c[2].evidence()["superseded_failures"]


@pytest.mark.parametrize("scope", ["exact", "parent"])
def test_declared_output_cannot_overwrite_consumed_input_or_directory(tmp_path, scope):
    c, target = recovery_case(tmp_path)
    c[4]["items"][0]["local_paths"].append(str(target if scope == 'exact' else target.parent))
    old = target.read_bytes()
    approve(c)
    with pytest.raises(api.ToolError, match="consumed input"):
        run(c)
    assert target.read_bytes() == old
    assert not (c[1] / '.geoforge/output-preimages').exists()


def test_existing_undeclared_sibling_stays_immutable(tmp_path):
    source = "from pathlib import Path\nPath('outputs/sibling.txt').write_text('changed')\n" + CSV_READER
    c, target = recovery_case(tmp_path, source)
    sibling = target.with_name('sibling.txt')
    sibling.write_text('original', encoding='utf-8')
    approve(c)
    result = run(c)
    assert result.startswith('exit_code=1'), result
    assert sibling.read_text(encoding='utf-8') == 'original'
    assert target.read_text(encoding='utf-8') == 'unreceipted original'


@pytest.mark.parametrize("damage", ["changed", "missing"])
def test_worker_rejects_existing_output_changed_after_host_preimage(tmp_path, monkeypatch, damage):
    c, target = recovery_case(tmp_path)
    original = project_data_tools.preserve_output_preimages
    def changed(*args, **kwargs):
        history = original(*args, **kwargs)
        if damage == 'missing':
            target.unlink()
        else:
            target.write_text('concurrent edit', encoding='utf-8')
        return history
    monkeypatch.setattr(project_data_tools, 'preserve_output_preimages', changed)
    approve(c)
    result = run(c)
    assert result.startswith('exit_code=1'), result
    if damage == 'missing':
        assert not target.exists()
    else:
        assert target.read_text(encoding='utf-8') == 'concurrent edit'
    _, doc = receipt(result)
    assert doc['validation']['status'] == 'failed'
    assert_preimage(c, doc, b'unreceipted original')


@pytest.mark.parametrize('linked', ['symlink', 'hardlink'])
def test_existing_output_alias_is_denied_before_recovery(tmp_path, linked):
    c, target = recovery_case(tmp_path)
    original = target.read_bytes()
    other = target.with_name('other.txt')
    target.replace(other)
    try:
        if linked == 'symlink':
            target.symlink_to(other)
        else:
            target.hardlink_to(other)
    except OSError:
        pytest.skip('host cannot create this link')
    approve(c)
    with pytest.raises(api.ToolError, match='aliases|ordinary unshared'):
        run(c)
    assert other.read_bytes() == original
    assert not (c[1] / '.geoforge/output-preimages').exists()


def test_v2_contract_only_existing_output_argument_is_not_mistaken_for_input(tmp_path):
    from .test_project_data_output_contracts import typed_case
    c = typed_case(tmp_path)
    # The reviewed format contract supplies exact paths; this legacy inventory
    # does not repeat them. Existing literal destination arguments are preimages.
    target = c[1] / 'outputs/weather.csv'
    target.parent.mkdir()
    target.write_text('unreceipted prior weather', encoding='utf-8')
    c[3]['steps'][0]['project_data_tool']['arguments'] = ['outputs/weather.csv']
    approve(c)
    result = run(c)
    assert result.startswith('exit_code=0'), result
    _, doc = receipt(result)
    assert doc['validation']['status'] == 'passed', doc['validation']
    assert 'outputs/weather.csv' not in {row['path'] for row in doc['inputs']}
    assert c[2].evidence()['receipts_verified'], c[2].evidence()
    history = doc['validation']['output_preimages']
    assert (c[1] / history['outputs'][0]['preimage_path']).read_text(encoding='utf-8') == 'unreceipted prior weather'


def test_conflicting_v2_inventory_and_format_paths_do_not_expand_replacement_grants(tmp_path):
    from .test_project_data_output_contracts import typed_case
    c = typed_case(tmp_path)
    c[4]['items'].append({'id': 'weather', 'status': 'missing', 'local_paths': ['outputs/other.csv']})
    target = c[1] / 'outputs/other.csv'
    target.parent.mkdir()
    target.write_text('preserve this different file', encoding='utf-8')
    approve(c)
    with pytest.raises(api.ToolError, match='differs from.*format'):
        run(c)
    assert target.read_text(encoding='utf-8') == 'preserve this different file'
    assert not (c[1] / '.geoforge/output-preimages').exists()
    assert not (c[1] / 'outputs/weather.csv').exists()
