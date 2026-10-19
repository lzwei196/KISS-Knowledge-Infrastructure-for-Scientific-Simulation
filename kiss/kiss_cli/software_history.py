"""Authenticated historical setup observations; never current readiness.

Only real host verification publication calls the writer. Reading does not
migrate old status, create signing keys, execute probes or renew any authority.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import time
import uuid

from . import flowgate, runtime_provenance

KIND = "software-verification-result"
MAX_BYTES = 64 * 1024
MAX_FILES = 512
SCOPES = {"full_software_verification", "installation_only"}
_ERROR = "Authenticated verification history was not saved; no historical runtime version is established by this status."
_FIELDS = {"schema_version", "kind", "scope", "event_id", "installation", "model",
           "operation_id", "checked_at", "outcome", "check_scope", "verification_context",
           "runtime_identity", "verification_identity", "ki_content_digest", "checks", "signature"}


def capture():
    """Capture before checks; absence remains unknown, never replaced afterward."""
    try:
        return runtime_provenance.validate(runtime_provenance.capture())
    except (OSError, ValueError, TypeError, RuntimeError):
        return None


def _text(value, limit=160, *, optional=False):
    if optional and value is None:
        return None
    if (not isinstance(value, str) or not value or len(value) > limit
            or any(ord(c) < 32 for c in value)):
        raise ValueError("Invalid verification-history text field")
    return value


def _hash(value):
    if value is not None and (not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value)):
        raise ValueError("Invalid verification-history identity")
    return value


def _ordinary(path, *, directory=False):
    if path.resolve() != path.absolute():
        raise ValueError("Verification history cannot use aliased paths")
    for parent in (path, *path.parents):
        info=parent.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:
            raise ValueError("Verification history cannot use linked paths")
    info=path.stat()
    if directory:
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("Verification history requires an ordinary directory")
    elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("Verification history requires an ordinary unshared file")
    return info


def _location(installation, model):
    root=Path(installation).expanduser().resolve()
    _text(model)
    receipts=flowgate.load().receipts
    authority=receipts.registry_dir().absolute()
    if authority.resolve() != authority or authority.is_relative_to(root):
        raise ValueError("Verification history must remain outside the installation")
    key=hashlib.sha256(json.dumps([str(root),model],ensure_ascii=False).encode()).hexdigest()[:32]
    return root, receipts, authority/'software-verification-history'/key


def _validate(doc, root, model):
    if (not isinstance(doc,dict) or set(doc)!=_FIELDS
            or type(doc.get('schema_version')) is not int or doc['schema_version']!=1
            or doc.get('kind')!=KIND or doc.get('scope')!='historical_only'
            or doc.get('installation')!=str(root) or doc.get('model')!=model
            or not re.fullmatch('[0-9a-f]{32}',str(doc.get('event_id','')))
            or doc.get('check_scope') not in SCOPES
            or doc.get('outcome') not in {'passed','failed','cancelled'}):
        raise ValueError('Invalid verification-history scope')
    _text(doc['operation_id'],128,optional=True)
    at=doc['checked_at']
    if type(at) not in (float,int) or not math.isfinite(at) or at<=0:
        raise ValueError('Invalid verification-history time')
    runtime_provenance.validate(doc['verification_context'])
    for key in ('runtime_identity','verification_identity','ki_content_digest'):
        _hash(doc[key])
    checks=doc['checks']
    if not isinstance(checks,list) or len(checks)>64:
        raise ValueError('Invalid verification-history checks')
    for row in checks:
        if (not isinstance(row,dict) or set(row)!={'name','ok','skipped'}
                or type(row['ok']) is not bool or type(row['skipped']) is not bool):
            raise ValueError('Invalid verification-history check')
        _text(row['name'])
    if doc['outcome']=='passed' and (not checks or any(not row['ok'] for row in checks)):
        raise ValueError('Passing verification history requires actual passing checks')
    return doc


def record(installation, model, *, verification_context, operation_id, checked_at,
           outcome, check_scope, runtime_identity=None, verification_identity=None,
           ki_content_digest=None, checks=()):
    """Persist one completed host observation, without granting readiness."""
    root,receipts,directory=_location(installation,model)
    doc={'schema_version':1,'kind':KIND,'scope':'historical_only',
         'event_id':uuid.uuid4().hex,'installation':str(root),'model':model,
         'operation_id':operation_id,'checked_at':checked_at,'outcome':outcome,
         'check_scope':check_scope,
         'verification_context':runtime_provenance.validate(verification_context),
         'runtime_identity':runtime_identity,'verification_identity':verification_identity,
         'ki_content_digest':ki_content_digest,'checks':[dict(row) for row in checks],
         'signature':None}
    _validate(doc,root,model)
    sealed=receipts.sign(root,dict(doc))
    data=(json.dumps(sealed,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')
    if len(data)>MAX_BYTES:
        raise ValueError('Verification history exceeds the record limit')
    # The registry is host-owned, outside installation/project trees. Reject
    # aliases before creating missing children; never overwrite an event.
    missing=[];parent=directory
    while not parent.exists() and not parent.is_symlink():
        missing.append(parent);parent=parent.parent
    _ordinary(parent,directory=True)
    for path in reversed(missing):
        try:path.mkdir()
        except FileExistsError:pass
        _ordinary(path,directory=True)
    _ordinary(directory,directory=True)
    path=directory/(doc['event_id']+'.json')
    with path.open('xb') as stream:
        stream.write(data);stream.flush();os.fsync(stream.fileno())
    _ordinary(path)
    return {'event_id':doc['event_id'],'sha256':hashlib.sha256(data).hexdigest(),
            'scope':'historical_only'}


def record_status(installation, model, status, *, verification_context, check_scope, outcome=None, checks=None):
    """Optional history reference; preserve the actual verification verdict."""
    status.pop('verification_history',None)
    status.pop('verification_history_error',None)
    try:
        rows=[{'name':row['name'],'ok':row['ok'],'skipped':row.get('skipped',False)}
              for row in (status.get('steps',[]) if checks is None else checks) if isinstance(row,dict)]
        result_outcome = outcome or ('passed' if status.get('ok') is True else 'failed')
        status['verification_history']=record(installation,model,
            verification_context=verification_context,
            operation_id=(status.get('current_operation') or {}).get('id'),
            checked_at=status.get('checked_at'),check_scope=check_scope,
            outcome=result_outcome,
            runtime_identity=status.get('runtime_identity'),
            verification_identity=status.get('verification_identity'),
            ki_content_digest=status.get('ki_content_digest') if result_outcome != 'cancelled' else None,checks=rows)
    except (OSError,ValueError,TypeError,RuntimeError,KeyError):
        status['verification_history_error']=_ERROR


def history(installation, model, limit=8):
    """Return a bounded authenticated subset, never completeness/readiness."""
    if type(limit) is not int or not 1<=limit<=32:
        raise ValueError('History limit must be an integer from 1 to 32')
    result={'scope':'historical_only','records':[],'invalid_count':0,'truncated':False,
            'note':'Bounded authenticated observations only; not a complete timeline or current readiness.'}
    try:
        root,receipts,directory=_location(installation,model)
        if not directory.exists() and not directory.is_symlink():
            return result
        _ordinary(directory,directory=True)
        paths=[]
        with os.scandir(directory) as entries:
            for entry in entries:
                if len(paths)>=MAX_FILES:
                    result['truncated']=True;break
                paths.append(Path(entry.path))
        records=[]
        for path in paths:
            try:
                if not re.fullmatch(r'[0-9a-f]{32}\.json',path.name):
                    raise ValueError('Invalid event filename')
                before=_ordinary(path)
                if before.st_size>MAX_BYTES:
                    raise ValueError('Oversized event')
                with path.open('rb') as stream:
                    raw=stream.read(MAX_BYTES+1)
                after=_ordinary(path)
                if (len(raw)>MAX_BYTES or (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)
                        !=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns)):
                    raise ValueError('Event changed during reading')
                doc=_validate(json.loads(raw),root,model)
                if path.stem!=doc['event_id'] or not receipts.verify(root,doc):
                    raise ValueError('Unauthenticated event')
                row={k:v for k,v in doc.items() if k!='signature'}
                row.update(authenticated=True, authentication='verified', provenance='recorded')
                records.append(row)
            except (OSError,ValueError,TypeError,RuntimeError,KeyError):
                result['invalid_count']+=1
        records.sort(key=lambda row:(row['checked_at'],row['event_id']),reverse=True)
        result['records']=records[:limit]
        result['truncated']=result['truncated'] or len(records)>limit
    except (OSError,ValueError,TypeError,RuntimeError):
        result['unavailable']=True
    return result
