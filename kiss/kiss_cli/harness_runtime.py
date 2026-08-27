"""Load and prove GeoForge's exact bundled KI harness.

``ki_tools_common`` has a project-root/package-root layout::

    ki_tools_common/                 # distribution/source root
        ki_tools_common/             # import package
            harness/

The outer directory is also shipped as loose source because model tools run in
separate Python interpreters.  Merely copying that directory beside a frozen
application does not make ``ki_tools_common.harness`` importable: the outer
directory becomes a namespace package unless its parent is on ``sys.path``.

This adapter establishes that path deliberately, rejects an unrelated copy
from another model workspace, and exposes one status probe shared by the CLI,
the desktop self-check and release tests.
"""

from __future__ import annotations

import hashlib
import importlib
import sys
from pathlib import Path


class HarnessUnavailable(RuntimeError):
    """The mandatory KI execution contract cannot be loaded or proved."""


class KiContractUnavailable(RuntimeError):
    """The harness loaded correctly, but this particular KI is incomplete."""


def bundled_source_root() -> Path:
    """Return the distribution root containing the import package."""
    candidates: list[Path] = []
    frozen = getattr(sys, "_MEIPASS", None)
    if frozen:
        candidates.append(Path(frozen) / "ki_tools_common")
    candidates.append(Path(__file__).resolve().parents[2] / "ki_tools_common")
    for outer in candidates:
        if (outer / "ki_tools_common" / "harness" / "__init__.py").is_file():
            return outer.resolve()
    expected = ", ".join(str(path) for path in candidates)
    raise HarnessUnavailable(
        f"GeoForge's bundled ki_tools_common source is missing; checked {expected}")


def _inside(path: str | Path | None, root: Path) -> bool:
    if not path:
        return False
    try:
        target = Path(path).resolve(strict=False)
        return target == root or root in target.parents
    except OSError:
        return False


def load():
    """Return ``(harness package, ki_harness implementation)``.

    The source root is prepended even in a frozen build.  PyInstaller's frozen
    importer still wins for modules collected into the PYZ, while the loose
    source remains a deterministic recovery path and the payload used by
    external model interpreters.
    """
    outer = bundled_source_root()
    outer_text = str(outer)
    if outer_text in sys.path:
        sys.path.remove(outer_text)
    sys.path.insert(0, outer_text)
    importlib.invalidate_caches()
    try:
        package = importlib.import_module("ki_tools_common.harness")
        implementation = importlib.import_module(
            "ki_tools_common.harness.ki_harness")
    except Exception as error:
        raise HarnessUnavailable(
            "ki_tools_common.harness could not be imported from GeoForge's "
            f"bundled source ({type(error).__name__}: {error})") from error

    # A developer machine may have an editable copy below ~/kiss/<model>.
    # Accept only this checkout/bundle, otherwise tests can pass using stale
    # code that will not exist on a researcher's machine.
    origins = [getattr(package, "__file__", None),
               getattr(implementation, "__file__", None)]
    if not all(_inside(origin, outer) for origin in origins):
        raise HarnessUnavailable(
            "ki_tools_common.harness resolved outside this GeoForge build: "
            + ", ".join(str(origin) for origin in origins))
    marker = getattr(implementation, "MARKER", None)
    contract = getattr(package, "contract", None)
    if marker != "[KI HARNESS v1]" or not callable(contract):
        raise HarnessUnavailable(
            "the bundled harness does not expose the required v1 contract")
    return package, implementation


def _sha256(path: str | Path | None) -> str:
    if not path:
        return ""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError as error:
        raise HarnessUnavailable(
            f"could not hash the bundled harness implementation: {error}") from error


def verified_contract(ki_root: str | Path, *, execute: bool = True,
                      python: str | None = None) -> tuple[str, dict]:
    """Render and prove one KI contract, returning an auditable receipt.

    The imported module must be GeoForge's bundled copy, and the text returned
    by that module must still contain its conformance marker. A broken harness
    is a hard failure; only an incomplete individual KI may be reported as
    unavailable.
    """
    package, implementation = load()
    previous_python = getattr(implementation, "PROJECT_PY", None)
    if python:
        implementation.PROJECT_PY = str(python)
    try:
        try:
            text = package.contract(Path(ki_root), execute=execute)
        except getattr(package, "KiHarnessError", Exception) as error:
            raise KiContractUnavailable(str(error)) from error
    finally:
        if python and previous_python is not None:
            implementation.PROJECT_PY = previous_python

    try:
        implementation.assert_injected(text)
    except Exception as error:
        raise HarnessUnavailable(
            f"the bundled harness returned an unverified contract: {error}") from error

    origin = getattr(implementation, "__file__", "")
    receipt = {
        "ready": True,
        "marker": implementation.MARKER,
        "implementation_origin": str(origin),
        "implementation_sha256": _sha256(origin),
        "contract_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "contract_chars": len(text),
    }
    return text, receipt


def receipt_line(receipt: dict) -> str:
    """Return the compact proof embedded in every KI-guided prompt."""
    return (
        "[GEOFORGE HARNESS RECEIPT] "
        f"marker={receipt.get('marker')} "
        f"implementation_sha256={receipt.get('implementation_sha256')} "
        f"contract_sha256={receipt.get('contract_sha256')}"
    )


def status(ki_root: str | Path | None = None) -> dict:
    """Return machine-readable import and injection evidence."""
    try:
        package, implementation = load()
        result = {
            "ready": True,
            "marker": implementation.MARKER,
            "package_origin": str(getattr(package, "__file__", "")),
            "implementation_origin": str(
                getattr(implementation, "__file__", "")),
            "contract_chars": None,
            "implementation_sha256": _sha256(
                getattr(implementation, "__file__", "")),
            "contract_sha256": None,
        }
        if ki_root is not None:
            _text, proof = verified_contract(ki_root, execute=True)
            result.update(proof)
        return result
    except Exception as error:
        return {
            "ready": False,
            "error": f"{type(error).__name__}: {error}",
        }
