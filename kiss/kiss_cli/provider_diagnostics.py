"""Bounded host diagnostics; never completion, approval, or scientific evidence.

Only small allowlisted metadata is retained. Prompts, credentials, tool arguments
and full tool results are deliberately not accepted by this logger.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import threading
import time

LOG = Path('.geoforge/provider-diagnostics.jsonl')
MAX_BYTES = 256 * 1024
_LOCK = threading.Lock()
_FIELDS = frozenset({'phase', 'reason', 'tool', 'provider', 'finish_reason',
    'state', 'turn_id', 'approval_id', 'call_count', 'text_chars', 'error',
    'blocked', 'malformed_arguments', 'step'})


def record(project, event, **metadata):
    """Best effort, with one bounded predecessor and no linked destinations."""
    if project is None:
        return
    try:
        from .flowgate import _redact_plan_error
        row = {'schema_version': 'geoforge.provider-diagnostics.v1',
               'at_epoch': time.time(), 'event': _redact_plan_error(event)[:80]}
        for key in _FIELDS & metadata.keys():
            value = metadata[key]
            if value is None or isinstance(value, (bool, int)):
                row[key] = value
            elif isinstance(value, str):
                row[key] = _redact_plan_error(value)[:(1000 if key == 'error' else 200)]
        payload = (json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')
        if len(payload) > 8192:
            return
        with _LOCK:
            root = Path(project).resolve()
            if not root.is_dir():
                return
            directory = root / LOG.parent
            path = root / LOG
            backup = path.with_suffix('.previous.jsonl')
            for candidate in (directory, path, backup):
                try:
                    info = candidate.lstat()
                except FileNotFoundError:
                    continue
                if (stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0)
                        & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024)):
                    return
                if candidate != directory and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
                    return
            if directory.resolve() != directory or not directory.resolve().is_relative_to(root):
                return
            directory.mkdir(exist_ok=True)
            if path.exists() and path.stat().st_size + len(payload) > MAX_BYTES:
                if path.stat().st_size <= MAX_BYTES:
                    os.replace(path, backup)
                else:
                    path.unlink()
            with path.open('ab') as stream:
                stream.write(payload)
    except Exception:
        # Observability failure must not change execution or approval authority.
        return
