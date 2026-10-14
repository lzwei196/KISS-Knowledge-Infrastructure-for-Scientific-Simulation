"""Portable identities for complete source or frozen Python implementations.

Receipts bind executable code, including nested functions and constants. Source
is compiled afresh so edits after import invalidate evidence. Frozen importers
provide the same code through get_code; build paths and source line positions
are debugging metadata and deliberately do not affect the identity. This is
host provenance, not a sandbox against same-user modification of the process.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import types

POLICY = "portable-python-implementation-v1"


class IdentityError(ValueError):
    """The complete implementation cannot be identified safely."""


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _constant(value):
    # Type tags preserve distinctions such as True/1 and bytes/text. Code
    # constants cover defaults, annotations, nested helpers and module values.
    if value is None:
        return ["none"]
    if value is Ellipsis:
        return ["ellipsis"]
    if isinstance(value, types.CodeType):
        return ["code", _code(value)]
    if type(value) is bool:
        return ["bool", value]
    if type(value) is int:
        return ["int", str(value)]
    if type(value) is float:
        return ["float", value.hex()]
    if type(value) is complex:
        return ["complex", value.real.hex(), value.imag.hex()]
    if type(value) is str:
        return ["str", value]
    if type(value) is bytes:
        return ["bytes", value.hex()]
    if type(value) is tuple:
        return ["tuple", [_constant(item) for item in value]]
    if type(value) is frozenset:
        return ["frozenset", sorted((_constant(item) for item in value), key=_json)]
    raise IdentityError(f"Unsupported implementation constant: {type(value).__name__}")


def _code(code):
    # Keep execution metadata; exclude co_filename, co_firstlineno and line
    # tables, which change when an identical module is relocated or packaged.
    names = ("co_argcount", "co_posonlyargcount", "co_kwonlyargcount", "co_nlocals",
             "co_stacksize", "co_flags", "co_name", "co_qualname", "co_names",
             "co_varnames", "co_freevars", "co_cellvars")
    result = {name: getattr(code, name, None) for name in names}
    result.update(co_code=code.co_code.hex(),
                  co_exceptiontable=getattr(code, "co_exceptiontable", b"").hex(),
                  co_consts=[_constant(value) for value in code.co_consts])
    return result


def _module_code(module):
    name = getattr(module, "__name__", None)
    if not isinstance(name, str) or not name:
        raise IdentityError("Implementation module has no identity")
    filename = getattr(module, "__file__", None)
    # A frozen importer's __file__ commonly names a nonexistent .py. Do not
    # fall back for an unreadable or invalid existing source: cached bytecode
    # must never hide an edit that needs verification.
    if filename is not None:
        try:
            path = Path(filename)
            source = path.read_bytes() if path.suffix.casefold() in (".py", ".pyw") else None
        except FileNotFoundError:
            source = None
        except (OSError, TypeError, ValueError) as error:
            raise IdentityError(f"Cannot read implementation source for {name}") from error
        if source is not None:
            try:
                return compile(source, str(path), "exec", dont_inherit=True, optimize=0)
            except (SyntaxError, ValueError, TypeError) as error:
                raise IdentityError(f"Cannot compile implementation source for {name}") from error
    loader = getattr(module, "__loader__", None)
    get_code = getattr(loader, "get_code", None)
    if not callable(get_code):
        raise IdentityError(f"Cannot identify implementation code for {name}")
    try:
        code = get_code(name)
    except Exception as error:
        raise IdentityError(f"Cannot load implementation code for {name}") from error
    if not isinstance(code, types.CodeType):
        raise IdentityError(f"Cannot identify implementation code for {name}")
    return code


def module_digest(module):
    """Bind code and this identity algorithm, independent of source availability.

    The bytecode ABI is explicit: evidence is not carried across incompatible
    Python bytecode versions. No file paths or line numbers enter the payload.
    """
    value = {"policy": POLICY,
             "bytecode_abi": [sys.implementation.name, sys.implementation.cache_tag],
             "identity_implementation": _code(_module_code(sys.modules[__name__])),
             "module_name": getattr(module, "__name__", None),
             "module_code": _code(_module_code(module))}
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()
