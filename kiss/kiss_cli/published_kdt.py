"""Reviewed publication profile for one exact KDT structural verifier.

KDT's default gate accepts authored packages with gathered-paper evidence.
Published packages distribute a metadata bibliography instead. This explicit
profile changes only those literature semantics in a private function copy;
it does not rewrite candidate files, patch the installed engine, or discard
failures from the authoring verifier. All other KDT checks remain in place.

This small source patch is intended to become an upstream KDT profile. An
engine update requires reviewing these three sites again, not fuzzy matching.
"""
from __future__ import annotations

import ast
import hashlib
import json
import marshal
import sys
import types
from pathlib import Path


PROFILE_POLICY = "kdt-published-package-v1"
BASE_COMMIT = "631e5c50cb0cd812447f67358dd9c162658155ea"
# SHA-256 of verify_ki_structure.py after universal-newline reading. Identical
# reviewed Git source may be checked out as LF or CRLF on different platforms.
BASE_SOURCE_SHA256 = "4db1b2a9353ce72226ec7cd3e5d192221d4c006b1ceb9831ff72a56d05dc7746"


class PublishedProfileError(ValueError):
    """The reviewed publication contract cannot be applied safely."""


_LITERATURE_BEFORE = '''    # literature, reported as its own dimension
    gp = docs_dir / "gathered_papers.json"
    n_papers = 0
    if gp.is_file():
        try:
            n_papers = len(json.loads(gp.read_text()))
        except Exception:
            warns.append("docs/gathered_papers.json does not parse")
    info["n_papers"] = n_papers
    info["has_papers_json"] = gp.is_file()
'''

_LITERATURE_AFTER = '''    # Published literature is metadata, not gathered/read authoring evidence.
    _publication = _published_literature_check(ki, kind=kind)
    fails.extend(_publication["failures"])
    warns.extend(_publication["warnings"])
    n_papers = _publication["count"] if _publication["ok"] else 0
    info["n_papers"] = n_papers
    info["has_papers_json"] = _publication["present"]
    info["literature_profile"] = "published_metadata"
    info["published_literature"] = _publication["info"]
'''

_REQUIREMENT_BEFORE = '''    # literature is required too — the validation bands are read out of these papers
    if not gp.is_file():
        # data_ki: OWNER DECISION 2026-08-18 — "documentation is enough: one to two papers on
        # the spec and how it was generated." So papers are REQUIRED for datasets too, but the
        # bar is provenance (1-2 reference papers), not a validation-band corpus. Resolves the
        # codex-vs-kimi split (codex: structural; kimi: wrong question) with the owner's verdict:
        # required, but scoped to documentation.
        _papers_required = _model_reqs or kind == "data_ki"
        (fails if _papers_required else warns).append(
            (("[kind=data_ki: 1-2 papers documenting the dataset's spec and generation] ")
             if (kind == "data_ki") else
             ("" if _model_reqs else f"[kind={kind}: advisory] ")) +
            "docs/gathered_papers.json missing — REQUIRED. Provenance/validation literature: "
                     "this model's own literature; without it a run is graded on a generic "
                     "default. Gather with openalex_search.py + paper_fetch.py")
'''

_REQUIREMENT_AFTER = '''    # Published metadata requirements are checked above by the explicit
    # publication contract. No gathered/read authoring evidence is asserted.
'''

_CONVENTION_BEFORE = '''    if not _vc.is_file():
        if gp.is_file() and _model_reqs:
            fails.append("docs/validation_convention.yaml missing — REQUIRED (FILE 11). This KI "
                         "has gathered papers, so the cited pass-bands can be built. Run "
                         "`python3 stepb_dispatch_prep.py <MODEL>` then work "
                         "stepb_agent_prompt.md")
        elif _model_reqs:
            warns.append("docs/validation_convention.yaml missing, and there are no gathered "
                         "papers to build it from — fix FILE 9 first")
        else:
            # codex round 1: this branch used to claim "there are no gathered papers" even for a
            # non-model KI that HAS them. Say what is true: the convention is a model contract.
            warns.append(f"docs/validation_convention.yaml missing [kind={kind}: not required — "
                         f"it records how a MODEL is judged against observations]")
'''

_CONVENTION_AFTER = '''    if not _vc.is_file():
        if _model_reqs:
            fails.append("docs/validation_convention.yaml missing — REQUIRED (FILE 11). "
                         "A published process-model package must retain its cited validation "
                         "convention; a metadata bibliography does not replace it.")
        else:
            warns.append(f"docs/validation_convention.yaml missing [kind={kind}: not required — "
                         f"it records how a MODEL is judged against observations]")
'''

_PROFILE_EDITS = (
    (_LITERATURE_BEFORE, _LITERATURE_AFTER),
    (_REQUIREMENT_BEFORE, _REQUIREMENT_AFTER),
    (_CONVENTION_BEFORE, _CONVENTION_AFTER),
)


def _profile_source(source: str) -> str:
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    if digest != BASE_SOURCE_SHA256:
        raise PublishedProfileError(
            "This KDT verifier has no reviewed published-package profile; "
            "install the supported reviewed engine before updating the library")
    for before, after in _PROFILE_EDITS:
        if source.count(before) != 1:
            raise PublishedProfileError("The reviewed KDT publication patch no longer matches its source")
        source = source.replace(before, after, 1)
    return source


def _checked_literature(root: Path, model_name: str, kind: str = "process_model") -> dict:
    from . import published_literature
    if kind not in ("process_model", "task_workflow"):
        raise PublishedProfileError("Unsupported publication KI kind")
    result = published_literature.check(root, model_name=model_name, kind=kind)
    if (not isinstance(result, dict)
            or type(result.get("ok")) is not bool
            or type(result.get("present")) is not bool
            or type(result.get("count")) is not int or result["count"] < 0
            or not isinstance(result.get("info"), dict)
            or any(not isinstance(result.get(key), list)
                   or any(not isinstance(item, str) for item in result[key])
                   for key in ("failures", "warnings"))
            or result["ok"] != (not result["failures"])
            or (result["ok"] and kind == "process_model"
                and (not result["present"] or result["count"] == 0))):
        raise PublishedProfileError("Published literature checker returned an invalid result")
    return result


def gate_view(gate, *, model_name: str):
    """Return a private published-profile verifier; the authoring gate is intact.

    GeoForge applies its normal private UTF-8/tool-path adapter to this view.
    Only the patched verify function is compiled; existing module imports and
    the host's frozen-runtime sys proxy are preserved without rerunning them.
    """
    if not isinstance(model_name, str) or not model_name.strip():
        raise PublishedProfileError("Published verification requires the catalogue's model identity")
    try:
        path = Path(gate.__file__)
        source = path.read_text(encoding="utf-8")
    except (AttributeError, OSError, UnicodeError, TypeError) as error:
        raise PublishedProfileError("Cannot read the reviewed KDT verifier source") from error
    patched = _profile_source(source)
    tree = ast.parse(patched, filename=str(path))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "verify"]
    if len(functions) != 1:
        raise PublishedProfileError("Reviewed KDT verifier must have exactly one verify function")
    # Preserve the base module's future-annotations contract when compiling a
    # function in isolation, including on Python versions before PEP 604.
    imports = [node for node in tree.body if isinstance(node, ast.ImportFrom)
               and node.module == "__future__"]
    code = compile(ast.Module(body=imports + functions, type_ignores=[]),
                   str(path) + " [published profile]", "exec", dont_inherit=True)
    view = types.ModuleType(gate.__name__ + "_published")
    view.__dict__.update(gate.__dict__)
    view.__dict__["_published_literature_check"] = lambda root, *, kind: _checked_literature(root, model_name, kind)
    exec(code, view.__dict__)
    view.PUBLICATION_PROFILE = PROFILE_POLICY
    return view


def _module_identity(module) -> str:
    # Source installs retain the readable implementation. Frozen builds may
    # have only their importer's code object; both forms include the complete
    # module, including the patch and all helper functions, in the identity.
    try:
        source = Path(module.__file__).read_text(encoding="utf-8")
        payload = b"source\0" + source.encode("utf-8")
    except (OSError, UnicodeError, TypeError, AttributeError):
        loader = getattr(module, "__loader__", None)
        code = loader.get_code(module.__name__) if hasattr(loader, "get_code") else None
        if not isinstance(code, types.CodeType):
            raise PublishedProfileError("Cannot identify the published verifier implementation")
        payload = b"code\0" + marshal.dumps(code)
    return hashlib.sha256(payload).hexdigest()


def profile_source_digest() -> str:
    """Bind publication receipts to the exact app-owned profile implementation."""
    from . import published_literature
    identities = {"policy": PROFILE_POLICY, "base_commit": BASE_COMMIT,
                  "base_source_sha256": BASE_SOURCE_SHA256,
                  "profile": _module_identity(sys.modules[__name__]),
                  "literature": _module_identity(published_literature)}
    return hashlib.sha256(json.dumps(identities, sort_keys=True).encode("utf-8")).hexdigest()
