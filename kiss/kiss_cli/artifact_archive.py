"""Reversible, explicit host archive of an unbound project artifact.

This is housekeeping, never scientific validation or a receipt rewrite. The
caller must hold the project-operation lease and supply a current idle check.
The file, context, and all historical authentic receipt references are checked
again immediately before the no-replace move. Archive records are signed host
audits outside the run-receipt namespace.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import stat
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from . import flowgate

ARCHIVE_ROOT = '.geoforge/archived-unreceipted'
MAX_BYTES = 64 * 1024 * 1024
MAX_JSON = 16 * 1024 * 1024
MAX_RECEIPTS = 4096
POLICY = 'unreceipted-artifact-archive-v1'


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _ordinary(path: Path, *, directory=False, missing=False):
    """Reject lexical aliases, reparse points, and multiply linked files."""
    if not path.is_absolute() or path.absolute() != path.resolve():
        raise ValueError('Paths must be absolute and must not use aliases.')
    for parent in (path, *path.parents):
        try:
            st = parent.lstat()
        except FileNotFoundError:
            if parent == path and missing:
                continue
            raise ValueError('A required path does not exist.')
        if stat.S_ISLNK(st.st_mode) or getattr(st, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Linked or reparse-point paths cannot be archived.')
    if missing and not path.exists():
        return None
    st = path.stat()
    if directory:
        if not stat.S_ISDIR(st.st_mode):
            raise ValueError('Expected an ordinary directory.')
    elif not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        raise ValueError('Expected an ordinary file with no hardlinks.')
    return st


def _relative(raw):
    if (not isinstance(raw, str) or not raw or len(raw) > 1600 or '\\' in raw
            or ':' in raw or any(ord(c) < 32 for c in raw)):
        raise ValueError('Use a literal project-relative artifact path.')
    p = PurePosixPath(raw)
    if (p.is_absolute() or p.as_posix() != raw or any(x in {'', '.', '..'} for x in p.parts)
            or p.parts[0] not in {'outputs', 'artifacts'} or len(p.parts) < 2
            or any(x.endswith((' ', '.')) for x in p.parts)):
        raise ValueError('Only ordinary files under outputs/ or artifacts/ can be archived.')
    return raw


def _fingerprint(st):
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_nlink)


def _hash(path, limit=MAX_BYTES):
    before = _ordinary(path)
    if before.st_size > limit:
        raise ValueError('File exceeds the bounded archive inspection limit.')
    h = hashlib.sha256()
    size = 0
    with _open_read(path) as stream:
        if _fingerprint(os.fstat(stream.fileno())) != _fingerprint(before):
            raise ValueError('File changed during inspection.')
        while block := stream.read(min(1024 * 1024, limit + 1 - size)):
            size += len(block)
            if size > limit:
                raise ValueError('File grew beyond the inspection limit.')
            h.update(block)
        if _fingerprint(os.fstat(stream.fileno())) != _fingerprint(before):
            raise ValueError('File changed during inspection.')
    if size != before.st_size or _fingerprint(_ordinary(path)) != _fingerprint(before):
        raise ValueError('File changed during inspection.')
    return h.hexdigest(), size, _fingerprint(before)


def _read_json(path):
    digest, _, _ = _hash(path, MAX_JSON)
    with _open_read(path) as stream:
        doc = json.loads(stream.read(MAX_JSON + 1).decode('utf-8'))
    if _hash(path, MAX_JSON)[0] != digest:
        raise ValueError('Project evidence changed during inspection.')
    return doc, digest


def _reference_path(project, raw, cwd=None):
    if not isinstance(raw, str) or not raw or '\x00' in raw:
        return None
    raw = raw.replace('${PROJECT}', str(project)).replace('{PROJECT}', str(project))
    if raw.startswith('--') and '=' in raw:
        raw = raw.split('=', 1)[1]
    p = Path(raw)
    if not p.is_absolute():
        p = (cwd or project) / p
    try:
        resolved = p.resolve()
        resolved.relative_to(project)
        return resolved
    except (OSError, ValueError, RuntimeError):
        return None


def _key(project, raw, cwd=None):
    resolved = _reference_path(project, raw, cwd)
    return resolved.relative_to(project).as_posix().casefold() if resolved is not None else None


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)


def _cwd(project, raw):
    if not isinstance(raw, str) or not raw:
        return project
    p = Path(raw.replace('${PROJECT}', str(project)).replace('{PROJECT}', str(project)))
    return p if p.is_absolute() else project / p


def _state(project, selected):
    project = Path(project).absolute()
    _ordinary(project, directory=True)
    flow = flowgate.load()
    ctx = flow.states.FlowContext.load(project)
    if ctx.state.value in {'ACQUIRING', 'SETUP_RUNNING'}:
        raise ValueError('Project setup or acquisition is active.')
    plan, inv = flow.plan.read_artifacts(project)
    if not isinstance(plan, dict) or not isinstance(inv, dict):
        raise ValueError('The current project plan and inventory are required.')
    chosen = set(selected)
    if not chosen or set(plan.get('selected_kis') or []) != chosen or set(ctx.selected_kis) != chosen:
        raise ValueError('The selected project models changed; refresh the project.')
    approval = flow.approval.read(project)
    hashes = {}
    # These raw-file identities also catch nonsemantic or same-size rewrites.
    for rel in ('runs/plan.json', 'runs/data-inventory.json', 'runs/approval.json',
                'runs/flow-state.json', '.geoforge/turn-generation'):
        path = project / rel
        hashes[rel] = _hash(path, MAX_JSON)[0] if path.exists() else None
    protected, protected_dirs = set(), set()
    for item in inv.get('items') or []:
        if not isinstance(item, dict):
            raise ValueError('Malformed current inventory.')
        for raw in item.get('local_paths') or []:
            key = _key(project, raw)
            if key:
                protected.add(key)
                # A declared input/output directory owns its subtree. A CLI
                # --run-dir alone does not own every future sibling artifact.
                if _reference_path(project, raw).is_dir():
                    protected_dirs.add(key)
    for step in plan.get('steps') or []:
        if not isinstance(step, dict):
            raise ValueError('Malformed current plan.')
        for raw in _strings(step):
            for cwd in (project, _cwd(project, step.get('cwd'))):
                key = _key(project, raw, cwd)
                if key:
                    protected.add(key)
    for sub in (flow.receipts.RUNS_SUB, flow.receipts.DATA_SUB):
        directory = project / flow.receipts.RECEIPT_DIR / sub
        if not directory.exists():
            continue
        _ordinary(directory, directory=True)
        paths = sorted(directory.glob('*.json'))
        if len(paths) > MAX_RECEIPTS:
            raise ValueError('Too many historical receipts to inspect safely.')
        for path in paths:
            doc, digest = _read_json(path)
            hashes[path.relative_to(project).as_posix()] = digest
            if flow.receipts.verify(project, doc):
                for raw in _strings(doc):
                    for cwd in (project, _cwd(project, doc.get('cwd'))):
                        key = _key(project, raw, cwd)
                        if key:
                            protected.add(key)
                for row in doc.get('inputs') or []:
                    key = _key(project, row.get('path')) if isinstance(row, dict) else None
                    if key and _reference_path(project, row['path']).is_dir():
                        protected_dirs.add(key)
    proof = flow.receipts.evidence(project, plan, approval, inventory=inv)
    context = _digest({'project': str(project), 'selected': sorted(chosen), 'files': hashes,
        'plan': plan, 'inventory': inv, 'approval': approval, 'state': ctx.state.value,
        'unreceipted': proof.get('unreceipted_artifacts', [])})
    return {'context': context, 'protected': protected, 'protected_dirs': protected_dirs,
            'unreceipted': proof.get('unreceipted_artifacts', []), 'flow': flow}


def _eligible(project, raw, state):
    rel = _relative(raw)
    key = rel.casefold()
    if key not in {p.casefold() for p in state['unreceipted']}:
        raise ValueError('This path is not a current unreceipted artifact.')
    if (key in state['protected'] or any(key.startswith(p + '/') for p in state['protected_dirs'])
            or key in {p.casefold() for p in state['flow'].receipts.HOST_BOOKKEEPING}):
        raise ValueError('This file is required by a plan or referenced by a signed receipt.')
    return _hash(project / rel)


def preview(project, selected):
    project = Path(project).absolute()
    state = _state(project, selected)
    rows = []
    for raw in state['unreceipted']:
        row = {'path': raw, 'eligible': False, 'context_sha256': state['context']}
        try:
            digest, size, _ = _eligible(project, raw, state)
            row.update(sha256=digest, size=size, eligible=True, reason='')
        except (OSError, ValueError) as error:
            row['reason'] = str(error)
        rows.append(row)
    return {'items': rows, 'archives': archives(project), 'busy': False, 'reason': ''}


def _write_audit(project, path, doc, *, first=False):
    signed = flowgate.load().receipts.sign(project, dict(doc))
    content = (json.dumps(signed, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()
    temp = path if first else path.with_name('audit-' + uuid.uuid4().hex + '.tmp')
    with temp.open('xb') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    if not first:
        os.replace(temp, path)
    return signed


@contextmanager
def _open_read(path, *, moving=False):
    """Reads share DELETE; a moving handle excludes every other writer/deleter."""
    if os.name == 'nt':
        from ctypes import wintypes
        import msvcrt
        lib = ctypes.WinDLL('kernel32', use_last_error=True)
        create = lib.CreateFileW
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
            wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        handle = create(str(path), 0x80000000 | (0x00010000 if moving else 0),
                        1 if moving else 7, None, 3, 0x00200000, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    else:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        yield stream


def _move_no_replace(source, destination, stream):
    if destination.exists() or destination.is_symlink():
        raise FileExistsError('Archive destination already exists.')
    if os.name == 'nt':
        from ctypes import wintypes
        import msvcrt
        name = str(destination)
        class RenameInfo(ctypes.Structure):
            _fields_ = [('replace', wintypes.BOOLEAN), ('root', wintypes.HANDLE),
                        ('length', wintypes.DWORD), ('name', wintypes.WCHAR * (len(name) + 1))]
        info = RenameInfo(False, None, len(name.encode('utf-16-le')), name)
        lib = ctypes.WinDLL('kernel32', use_last_error=True)
        rename = lib.SetFileInformationByHandle
        rename.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
        rename.restype = wintypes.BOOL
        if not rename(msvcrt.get_osfhandle(stream.fileno()), 3, ctypes.byref(info), ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        lib = ctypes.CDLL(None, use_errno=True)
        if sys.platform == 'darwin':
            rename = lib.renamex_np
            rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
            result = rename(os.fsencode(source), os.fsencode(destination), 4)  # RENAME_EXCL
        elif hasattr(lib, 'renameat2'):
            rename = lib.renameat2
            rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            result = rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1)
        else:
            raise ValueError('This platform has no supported atomic no-overwrite rename.')
        if result != 0:
            raise OSError(ctypes.get_errno(), 'Archive rename failed.')


def archive(project, selected, *, path, expected_sha256, expected_size,
            expected_context_sha256, session_id, check_idle):
    """Call only for an explicit GUI action while holding the project lease."""
    project = Path(project).absolute()
    if (not isinstance(expected_sha256, str) or not re.fullmatch('[0-9a-f]{64}', expected_sha256)
            or type(expected_size) is not int or not 0 <= expected_size <= MAX_BYTES
            or not isinstance(expected_context_sha256, str)
            or not re.fullmatch('[0-9a-f]{64}', expected_context_sha256)
            or not re.fullmatch('[0-9a-f]{12}', str(session_id))):
        raise ValueError('A fresh archive preview with exact hash, size and context is required.')
    check_idle()
    state = _state(project, selected)
    digest, size, fingerprint = _eligible(project, path, state)
    if (digest, size, state['context']) != (expected_sha256, expected_size, expected_context_sha256):
        raise ValueError('The artifact or project context changed; refresh before archiving.')
    source = project / path
    with _open_read(source, moving=True) as stream:
        if _fingerprint(os.fstat(stream.fileno())) != fingerprint:
            raise ValueError('Artifact changed before it could be locked.')
        base = project / ARCHIVE_ROOT
        for directory in (project / '.geoforge', base):
            if not directory.exists():
                directory.mkdir()
            _ordinary(directory, directory=True)
        ident = uuid.uuid4().hex
        home = base / ident
        home.mkdir()  # exclusive: an existing directory is never reused
        _ordinary(home, directory=True)
        destination = home / path
        parent = home
        for component in PurePosixPath(path).parts[:-1]:
            parent = parent / component
            parent.mkdir()
            _ordinary(parent, directory=True)
        doc = {'version': 1, 'policy': POLICY, 'id': ident, 'state': 'prepared',
            'project': str(project), 'session_id': session_id, 'path': path,
            'archive_path': destination.relative_to(project).as_posix(), 'sha256': digest,
            'size': size, 'context_sha256': state['context'], 'created_at': time.time(),
            'provenance': 'explicit-local-gui-action', 'reason': 'User archived an unreceipted artifact for review; no scientific validation granted.'}
        audit_path = home / 'audit.json'
        _write_audit(project, audit_path, doc, first=True)
        check_idle()
        fresh = _state(project, selected)
        if fresh['context'] != state['context'] or _eligible(project, path, fresh) != (digest, size, fingerprint):
            raise ValueError('Project evidence or artifact changed before the move; source retained.')
        _ordinary(destination.parent, directory=True)
        _move_no_replace(source, destination, stream)
        # Windows keeps our delete-capable handle open; other opens may inspect
        # bytes but cannot modify either source identity or archived content.
        if source.exists() or _hash(destination)[:2] != (digest, size):
            raise ValueError('Archive needs manual inspection; its prepared audit preserves the original identity.')
        doc.update(state='archived', archived_at=time.time())
        _write_audit(project, audit_path, doc)
    return {'id': ident, 'path': path, 'sha256': digest, 'size': size}


def archived_file(project, ident, *, audit=False):
    project = Path(project).absolute()
    _ordinary(project, directory=True)
    if not isinstance(ident, str) or not re.fullmatch('[0-9a-f]{32}', ident):
        raise ValueError('Invalid archive identifier.')
    home = project / ARCHIVE_ROOT / ident
    _ordinary(home, directory=True)
    doc, _ = _read_json(home / 'audit.json')
    if (not flowgate.load().receipts.verify(project, doc) or doc.get('policy') != POLICY
            or doc.get('state') != 'archived' or doc.get('id') != ident or doc.get('project') != str(project)):
        raise ValueError('The archive has no authentic completed host audit.')
    relative = _relative(doc.get('path'))
    target = home / relative
    if doc.get('archive_path') != target.relative_to(project).as_posix() or _hash(target)[:2] != (doc.get('sha256'), doc.get('size')):
        raise ValueError('Archived bytes no longer match the signed audit.')
    return (home / 'audit.json' if audit else target), doc


def archives(project):
    base = Path(project) / ARCHIVE_ROOT
    if not base.exists():
        return []
    _ordinary(base, directory=True)
    rows = []
    for home in sorted(base.iterdir())[-200:]:
        try:
            _, doc = archived_file(project, home.name)
            rows.append({k: doc[k] for k in ('id', 'path', 'sha256', 'size')})
        except (OSError, ValueError, KeyError):
            continue
    return rows
