"""Explicit archive preserves bytes and never changes scientific authority."""
import hashlib
import io
import json
import os
from pathlib import Path

import pytest

from kiss_cli import artifact_archive as aa, gui, sessions
from .test_declared_output_validation import case, invoke

SID = 'a' * 12
REL = 'outputs/DSSAT/gainesville_replay_20261013_verified/hwam_replay_timeseries.csv'
DATA = b'day,yield\r\n1,0\r\n2,2293\r\n'


def extra(c, rel=REL):
    p = c.project / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(DATA)
    return p


def row(c, rel=REL):
    return next(r for r in aa.preview(c.project, ['M'])['items'] if r['path'] == rel)


def request(r):
    return {'path': r['path'], 'expected_sha256': r['sha256'], 'expected_size': r['size'],
            'expected_context_sha256': r['context_sha256']}


def archive(c, r=None, **kwargs):
    return aa.archive(c.project, ['M'], **request(r or row(c)), session_id=SID,
                      check_idle=kwargs.pop('check_idle', lambda: None), **kwargs)


def signed_reference(c, rel=REL, *, field='outputs', status='failed', current=False):
    flow = c.fs.flow
    doc = {'run_id': 'historical-reference', 'ki': 'M', 'plan_step_id': 'M:run',
        'approval_sha256': c.fs.approval_id if current else 'old-approval',
        'command': [str(c.tool)], 'executable': str(c.tool), 'finished_at': 1,
        'validation': {'status': status}, field: [{'path': rel, 'sha256': hashlib.sha256(DATA).hexdigest()}]}
    path = c.project / flow.receipts.RECEIPT_DIR / (
        flow.receipts.DATA_SUB if field in {'raw_files', 'processed_files'} else flow.receipts.RUNS_SUB) / 'history.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(flow.receipts.sign(c.project, doc)), encoding='utf-8')
    return path


def test_real_windows_move_preserves_bytes_receipts_and_flow_state(case):
    c = case
    invoke(c)
    p = extra(c)
    before = {f.relative_to(c.project).as_posix(): f.read_bytes() for f in c.project.rglob('*') if f.is_file()}
    assert not c.fs.evidence()['receipts_verified']
    r = row(c)
    assert r['eligible'] and r['size'] == len(DATA)
    saved = archive(c, r)
    target, audit = aa.archived_file(c.project, saved['id'])
    assert target.read_bytes() == DATA and not p.exists()
    assert audit['state'] == 'archived' and audit['provenance'] == 'explicit-local-gui-action'
    assert audit['context_sha256'] == r['context_sha256']
    assert c.fs.flow.receipts.verify(c.project, audit)
    assert c.fs.evidence()['receipts_verified']
    assert c.fs.flow.states.FlowContext.load(c.project).state.value == 'EXECUTING'
    for rel, contents in before.items():
        if rel != REL:
            assert (c.project / rel).read_bytes() == contents
    assert aa.preview(c.project, ['M'])['archives'] == [saved]


def test_reviewed_run_dir_does_not_protect_unknown_child(case):
    c = case; p = extra(c)
    c.fs.plan['steps'][0]['command'] = ['--run-dir', str(p.parent)]
    c.fs.flow.plan.write_artifacts(c.project, c.fs.plan, c.fs.inventory)
    assert row(c)['eligible']
    assert archive(c)['path'] == REL


@pytest.mark.parametrize('field', ['outputs', 'inputs', 'raw_files', 'processed_files'])
@pytest.mark.parametrize('status', ['passed', 'failed'])
def test_every_authentic_historical_reference_protected(case, field, status):
    c = case; p = extra(c); r = row(c)
    signed_reference(c, field=field, status=status)
    with pytest.raises(ValueError):
        archive(c, r)
    assert p.read_bytes() == DATA


@pytest.mark.parametrize('kind', ['inventory-output', 'inventory-input-directory', 'tool', 'command', 'casefold-reference'])
def test_current_required_paths_and_casefold_receipt_protected(case, kind):
    c = case; p = extra(c); r = row(c)
    if kind.startswith('inventory'):
        c.fs.inventory['items'].append({'id': 'protected', 'local_paths': [str(p.parent) if kind.endswith('directory') else REL]})
    elif kind == 'tool':
        c.fs.plan['steps'][0]['tool'] = str(p)
    elif kind == 'command':
        c.fs.plan['steps'][0]['command'] = ['--report=' + str(p)]
    else:
        signed_reference(c, REL.upper())
    c.fs.flow.plan.write_artifacts(c.project, c.fs.plan, c.fs.inventory)
    with pytest.raises(ValueError): archive(c, r)
    assert p.read_bytes() == DATA


@pytest.mark.parametrize('raw', ['../outside.csv', '/outputs/a.csv', 'outputs/../inputs/a.csv',
    'outputs//a.csv', 'outputs/./a.csv', 'outputs\\a.csv', 'outputs/a.csv:stream',
    'inputs/a.csv', 'models/M/ki/a.csv', '.geoforge/receipts/a.json', 'artifacts/a.csv ',
    'outputs/a\n.csv', 'outputs', 'calibration/cases/a.csv'])
def test_hostile_or_protected_names_rejected(case, raw):
    c = case; p = extra(c); r = row(c); req = request(r); req['path'] = raw
    with pytest.raises(ValueError):
        aa.archive(c.project, ['M'], **req, session_id=SID, check_idle=lambda: None)
    assert p.read_bytes() == DATA


@pytest.mark.parametrize('change', ['file', 'size', 'plan', 'inventory', 'approval', 'state', 'new-signed-receipt'])
def test_stale_preview_keeps_source(case, change):
    c = case; p = extra(c); r = row(c)
    if change == 'file': p.write_bytes(DATA.replace(b'2293', b'2000'))
    elif change == 'size': p.write_bytes(DATA + b'3,4\n')
    elif change in {'plan', 'inventory'}:
        target = c.project / 'runs' / ('plan.json' if change == 'plan' else 'data-inventory.json')
        target.write_bytes(target.read_bytes() + b'\n')
    elif change == 'approval':
        c.fs.flow.approval.revoke(c.project, 'fixture stale preview')
    elif change == 'state':
        target = c.project / 'runs/flow-state.json'
        target.write_bytes(target.read_bytes() + b'\n')
    else: signed_reference(c)
    expected = p.read_bytes()
    with pytest.raises(ValueError): archive(c, r)
    assert p.read_bytes() == expected


def test_race_before_move_keeps_file_and_prepared_audit(case):
    c = case; p = extra(c); calls = []
    def check():
        calls.append(1)
        if len(calls) == 2:
            signed_reference(c)
    with pytest.raises(ValueError): archive(c, check_idle=check)
    assert p.read_bytes() == DATA
    audits = list((c.project / aa.ARCHIVE_ROOT).rglob('audit.json'))
    assert len(audits) == 1 and json.loads(audits[0].read_text())['state'] == 'prepared'
    assert aa.archives(c.project) == []


def test_atomic_move_never_overwrites_even_unexpected_collision(case, monkeypatch):
    c = case; p = extra(c); original = aa._move_no_replace; destinations = []
    def collision(source, destination, stream):
        destination.write_bytes(b'PREEXISTING')
        destinations.append(destination)
        return original(source, destination, stream)
    monkeypatch.setattr(aa, '_move_no_replace', collision)
    with pytest.raises(FileExistsError): archive(c)
    assert p.read_bytes() == DATA and destinations[0].read_bytes() == b'PREEXISTING'
    assert not aa.archives(c.project)


def test_hardlink_source_rejected(case):
    c = case; p = extra(c); (c.project / 'inputs').mkdir(); os.link(p, c.project / 'inputs/linked.csv')
    assert not row(c)['eligible']
    assert p.read_bytes() == DATA


@pytest.mark.parametrize('location', ['source', 'parent', 'archive'])
def test_symlink_aliases_do_not_move_outside_bytes(case, tmp_path, location):
    c = case; p = extra(c); r = row(c); outside = tmp_path / 'outside'; outside.mkdir()
    (outside / 'extra.csv').write_bytes(b'OUTSIDE')
    if location == 'source':
        p.unlink(); p.symlink_to(outside / 'extra.csv')
    elif location == 'parent':
        p.unlink(); p.parent.rmdir(); p.parent.symlink_to(outside, target_is_directory=True)
    else:
        (c.project / '.geoforge').mkdir(exist_ok=True)
        (c.project / aa.ARCHIVE_ROOT).symlink_to(outside, target_is_directory=True)
    with pytest.raises((ValueError, OSError)): archive(c, r)
    assert (outside / 'extra.csv').read_bytes() == b'OUTSIDE'


def test_bounded_hash_rejects_before_read(case, monkeypatch):
    c = case; extra(c)
    monkeypatch.setattr(aa, 'MAX_BYTES', 4)
    # Function defaults are fixed; use an explicit limit to test the bounded reader.
    with pytest.raises(ValueError, match='limit'): aa._hash(c.project / REL, 4)


def handler(c, monkeypatch):
    h = gui.Handler.__new__(gui.Handler); h.workroot = c.project.parent / 'workroot'
    h.responses = []; h._json = lambda doc, code=200: h.responses.append((code, doc))
    (c.project / 'session.json').write_text(json.dumps({'id': SID, 'models': ['M']}))
    monkeypatch.setattr(sessions, '_find_project', lambda root, sid: c.project if sid == SID else None)
    with gui._LIVE_AGENT_RUNS_LOCK: gui._LIVE_AGENT_RUNS.pop(SID, None)
    with gui._PROJECT_OPERATIONS_LOCK: gui._PROJECT_OPERATIONS.pop(SID, None)
    return h


def test_actual_controller_preview_archive_and_download_without_resume(case, monkeypatch):
    c = case; extra(c); h = handler(c, monkeypatch)
    h._project_artifact_archive(SID)
    assert h.responses[-1][0] == 200
    r = next(x for x in h.responses[-1][1]['items'] if x['path'] == REL)
    h._project_artifact_archive(SID, req=request(r), action=True)
    code, result = h.responses[-1]
    assert code == 200 and result['ok']
    assert not gui._PROJECT_OPERATIONS.get(SID)
    assert 'Continue' in result['note']
    h.wfile = io.BytesIO(); headers = []
    h.send_response = lambda code: headers.append(('status', code))
    h.send_header = lambda *args: headers.append(args)
    h._set_browser_security_headers = lambda: None; h.end_headers = lambda: None
    h._download_archived_artifact(SID, result['archive']['id'])
    assert h.wfile.getvalue() == DATA and ('status', 200) in headers
    h.wfile = io.BytesIO()
    h._download_archived_artifact(SID, result['archive']['id'], audit=True)
    assert json.loads(h.wfile.getvalue())['provenance'] == 'explicit-local-gui-action'


@pytest.mark.parametrize('busy', ['turn', 'operation', 'acquisition', 'setup', 'selection'])
def test_controller_busy_or_changed_binding_never_moves(case, monkeypatch, busy):
    c = case; p = extra(c); h = handler(c, monkeypatch); r = row(c)
    token = None
    if busy == 'turn': monkeypatch.setattr(gui, '_agent_run_snapshot', lambda sid: {'state': 'running'})
    elif busy == 'operation': token = gui._claim_project_operation(SID, 'other mutation')
    elif busy == 'acquisition': monkeypatch.setattr(gui.project_status, 'snapshot', lambda *a, **k: {'progress': {'acquisition': {'active': True}}})
    elif busy == 'selection':
        (c.project / 'session.json').write_text(json.dumps({'id': SID, 'models': ['Other']}))
    else:
        def reject(*args, **kwargs): raise ValueError('Setup is running')
        monkeypatch.setattr(gui.setup_jobs, 'idle_guard', reject)
    try:
        h._project_artifact_archive(SID, req=request(r), action=True)
        assert h.responses[-1][0] == 409 and p.read_bytes() == DATA
    finally:
        if token: gui._release_project_operation(SID, token)


@pytest.mark.parametrize('damage', ['bytes', 'audit', 'hardlink'])
def test_archive_download_rechecks_signed_audit_and_bytes(case, damage):
    c = case; extra(c); record = archive(c)
    p, doc = aa.archived_file(c.project, record['id'])
    if damage == 'bytes': p.write_bytes(b'TAMPERED')
    elif damage == 'hardlink':
        (c.project / 'inputs').mkdir(); os.link(p, c.project / 'inputs/alias.csv')
    else:
        audit = c.project / aa.ARCHIVE_ROOT / record['id'] / 'audit.json'
        data = json.loads(audit.read_text()); data['path'] = 'outputs/other.csv'; audit.write_text(json.dumps(data))
    with pytest.raises(ValueError): aa.archived_file(c.project, record['id'])


@pytest.mark.parametrize('scope', ['plan', 'receipt'])
@pytest.mark.parametrize('option', ['separate', 'equals'])
def test_required_file_argument_resolves_from_approved_cwd(case, scope, option):
    c = case; p = extra(c)
    args = ['--input', p.name] if option == 'separate' else ['--input=' + p.name]
    if scope == 'plan':
        c.fs.plan['steps'][0].update(command=args, cwd=str(p.parent))
        c.fs.flow.plan.write_artifacts(c.project, c.fs.plan, c.fs.inventory)
    else:
        receipt = signed_reference(c, rel='outputs/other.csv')
        doc = json.loads(receipt.read_text())
        doc.update(command=args, cwd=str(p.parent))
        receipt.write_text(json.dumps(c.fs.flow.receipts.sign(c.project, doc)))
    assert not row(c)['eligible']


@pytest.mark.parametrize('body', [None, {}, {'path': REL}, {'path': REL, 'untrusted_reason': 'approve'}])
def test_controller_rejects_missing_preview_or_unexpected_fields(case, monkeypatch, body):
    c = case; p = extra(c); h = handler(c, monkeypatch)
    h._project_artifact_archive(SID, req=body, action=True)
    assert h.responses[-1][0] == 409 and p.read_bytes() == DATA


def test_wrong_models_and_missing_project_do_not_create_project(case, monkeypatch):
    c = case; p = extra(c); h = handler(c, monkeypatch); r = row(c)
    with pytest.raises(ValueError): aa.preview(c.project, ['Other'])
    monkeypatch.setattr(sessions, '_find_project', lambda *a: None)
    h._project_artifact_archive(SID, req=request(r), action=True)
    assert h.responses[-1][0] == 409 and p.read_bytes() == DATA
