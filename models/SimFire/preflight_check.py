#!/usr/bin/env python3
"""Preflight check for the SimFire knowledge infrastructure."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener, getproxies, proxy_bypass


MODEL_ID = "SimFire"
KI_DIR = Path(__file__).resolve().parent
MODEL_PYTHON = Path(
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/"
    "SimFire/venv/bin/python"
)
MODEL_SITE_PACKAGES = Path(
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/"
    "SimFire/venv/lib/python3.12/site-packages"
)
SHARED_SITE_PACKAGES = Path(
    "KISSPATH_PYTHON_ENV/lib/python3.12/site-packages"
)
MTBS_SHAPEFILE = Path(
    "KISSPATH_OBS/fire_perimeters/mtbs/"
    "mtbs_perims/mtbs_perims_DD.shp"
)
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"
LFPS_URL = "https://lfps.usgs.gov/api/products"
LFPS_TIMEOUT = 30
# Extra proxy routes tried after "environment" and "direct". Override with a
# comma list in SIMFIRE_LFPS_PROXIES (an empty value disables extra proxies).
DEFAULT_LFPS_PROXIES = "http://127.0.0.1:7877,http://127.0.0.1:7897"
TOOLS = [
    KI_DIR / "tools" / "convert_landfire_to_simfire.py",
    KI_DIR / "tools" / "convert_wind_to_simfire.py",
    KI_DIR / "tools" / "run_simfire.py",
    KI_DIR / "tools" / "parse_simfire_output.py",
]


checks: list[dict[str, object]] = []


def record(kind: str, subject: str, critical: bool, ok: bool, fix: str = "") -> bool:
    """Record and print one check in the KDT preflight report format."""
    if not ok and fix and "diagnostics/triplets.yaml" not in fix:
        fix = f"{fix}; check diagnostics/triplets.yaml for recovery"
    check = {
        "kind": kind,
        "subject": subject,
        "critical": critical,
        "status": "pass" if ok else "fail",
        "fix": "" if ok else fix,
    }
    checks.append(check)
    label = "OK" if ok else ("FAIL" if critical else "WARN")
    print(f"  {label:<5} {kind}: {subject}")
    if not ok and fix:
        print(f"        Fix: {fix}")
    return ok


def run_model_python(code: str, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    """Run a short check inside the SimFire interpreter."""
    env = os.environ.copy()
    env.setdefault("SDL_VIDEODRIVER", "dummy")
    env.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    return subprocess.run(
        [str(MODEL_PYTHON), "-c", code],
        cwd=str(KI_DIR),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def check_file(path: Path, label: str, *, critical: bool = True, executable: bool = False) -> bool:
    subject = str(path)
    if executable:
        subject = os.path.realpath(path)
    if not path.is_file():
        return record("binary" if executable else "data", subject, critical, False, f"restore missing file: {path}")
    if executable and not os.access(path, os.X_OK):
        return record("binary", subject, critical, False, f"chmod +x {path}")
    return record("binary" if executable else "data", subject, critical, True)


def check_dir(path: Path, label: str, *, critical: bool = True) -> bool:
    del label
    if not path.is_dir():
        return record("data", str(path), critical, False, f"restore missing directory: {path}")
    try:
        next(path.iterdir())
    except StopIteration:
        return record("data", str(path), critical, False, f"reinstall SimFire dependencies into {path}")
    return record("data", str(path), critical, True)


def check_python_starts() -> bool:
    realpath = os.path.realpath(MODEL_PYTHON)
    if not check_file(MODEL_PYTHON, "SimFire Python interpreter", critical=True, executable=True):
        return False
    try:
        proc = run_model_python(
            "import os, sys; "
            "print(sys.version.split()[0]); "
            "print(os.path.realpath(sys.executable))",
            timeout=10,
        )
    except Exception as exc:
        return record("run", realpath, True, False, f"make {MODEL_PYTHON} start cleanly: {exc}")
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ["no output"]
        return record("run", realpath, True, False, f"make {MODEL_PYTHON} start cleanly: {detail[0]}")
    return record("run", realpath, True, True)


def check_import(module: str, label: str, *, critical: bool = True) -> bool:
    del label
    code = (
        "import sys; "
        f"shared={str(SHARED_SITE_PACKAGES)!r}; "
        "sys.path.append(shared) if shared not in sys.path else None; "
        f"__import__({module!r})"
    )
    try:
        proc = run_model_python(code, timeout=30)
    except Exception as exc:
        return record("import", module, critical, False, f"install/fix {module} for {MODEL_PYTHON}: {exc}")
    if proc.returncode == 0:
        return record("import", module, critical, True)
    detail = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ["import failed"]
    package = module.split(".")[0]
    return record(
        "import",
        module,
        critical,
        False,
        f"check diagnostics/triplets.yaml, then install/fix {package} for {MODEL_PYTHON}: {detail[0]}",
    )


def check_zarr_compatibility() -> bool:
    code = (
        "import sys; "
        f"shared={str(SHARED_SITE_PACKAGES)!r}; "
        "sys.path.append(shared) if shared not in sys.path else None; "
        "import zarr; "
        "from zarr.core.chunk_grids import RegularChunkGrid; "
        "print(zarr.__version__)"
    )
    try:
        proc = run_model_python(code, timeout=30)
    except Exception as exc:
        return record("import", "zarr.core.chunk_grids.RegularChunkGrid", True, False, f"pip install 'zarr>=3,<3.2': {exc}")
    if proc.returncode == 0:
        return record("import", "zarr.core.chunk_grids.RegularChunkGrid", True, True)
    detail = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ["zarr compatibility check failed"]
    return record(
        "import",
        "zarr.core.chunk_grids.RegularChunkGrid",
        True,
        False,
        f"check diagnostics/triplets.yaml, then run: pip install 'zarr>=3,<3.2' ({detail[0]})",
    )


def check_tools_compile() -> bool:
    missing = [str(path.relative_to(KI_DIR)) for path in TOOLS if not path.is_file()]
    if missing:
        return record("data", "tools/*.py", True, False, f"restore missing tool files: {', '.join(missing)}")
    try:
        proc = subprocess.run(
            [str(MODEL_PYTHON), "-m", "py_compile", *map(str, TOOLS)],
            cwd=str(KI_DIR),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
    except Exception as exc:
        return record("run", "tools/*.py py_compile", True, False, f"fix tool syntax/import-time setup: {exc}")
    if proc.returncode == 0:
        return record("run", "tools/*.py py_compile", True, True)
    detail = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ["py_compile failed"]
    return record("run", "tools/*.py py_compile", True, False, f"fix tool syntax; see diagnostics/triplets.yaml: {detail[0]}")


def _lfps_routes() -> list[tuple[str, dict[str, str] | None]]:
    """Routes to try: (label, proxies). proxies=None means use the environment."""
    def norm(url: str) -> str:
        return url.strip().rstrip("/")

    # If NO_PROXY covers the host, urllib connects directly even through an
    # explicit ProxyHandler, so every route is effectively direct.
    bypass = bool(proxy_bypass("lfps.usgs.gov"))
    env_proxy = "" if bypass else norm(getproxies().get("https", ""))
    routes: list[tuple[str, dict[str, str] | None]] = [
        (f"environment (proxy {env_proxy})" if env_proxy else "environment (no proxy)", None)
    ]
    seen = {env_proxy}
    if "" not in seen:
        routes.append(("direct (no proxy)", {}))
        seen.add("")
    extra = os.environ.get("SIMFIRE_LFPS_PROXIES", DEFAULT_LFPS_PROXIES)
    for proxy in (norm(p) for p in extra.split(",")):
        effective = "" if bypass else proxy
        if proxy and effective not in seen:
            routes.append((f"proxy {proxy}", {"http": proxy, "https": proxy}))
            seen.add(proxy)
    return routes


def _try_lfps_route(proxies: dict[str, str] | None) -> str:
    """Return '' on success (JSON with a non-empty products list), else the error."""
    opener = build_opener() if proxies is None else build_opener(ProxyHandler(proxies))
    request = Request(LFPS_URL, headers={"User-Agent": "KDT SimFire preflight"})
    try:
        with opener.open(request, timeout=LFPS_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # network, HTTP, SSL, JSON errors
        return f"{type(exc).__name__}: {exc}"
    products = payload.get("products") if isinstance(payload, dict) else None
    if not isinstance(products, list) or not products:
        return "reply had no non-empty 'products' list"
    return ""


def check_lfps() -> bool:
    """LFPS catalog reachability. Non-critical: LFPS is only needed to download
    LANDFIRE data for new sites; the engine and runs on local data do not need it."""
    failures: list[str] = []
    for label, proxies in _lfps_routes():
        error = _try_lfps_route(proxies)
        if not error:
            subject = f"{LFPS_URL} reachable via {label}"
            if failures:
                subject += f" (failed first: {'; '.join(failures)}; downloads must use the working route)"
            return record("network", subject, False, True)
        failures.append(f"{label}: {error}")
    return record(
        "network",
        f"{LFPS_URL} not reachable on any route",
        False,
        False,
        "LandFire Product Service (LFPS) could not be reached, so LANDFIRE data for new sites cannot be "
        "downloaded right now; the SimFire engine and runs on local data are not blocked. Tried: "
        + " | ".join(failures),
    )


def emit_report(model_id: str, report_checks: list[dict[str, object]]) -> None:
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": report_checks}, sort_keys=True))
    failed_critical = any(c["status"] != "pass" and c.get("critical") for c in report_checks)
    sys.exit(1 if failed_critical else 0)


def main() -> None:
    print(f"{' PREFLIGHT: SimFire ':=^60}")
    print()

    check_python_starts()
    check_dir(MODEL_SITE_PACKAGES, "SimFire venv site-packages", critical=True)
    check_dir(SHARED_SITE_PACKAGES, "shared HydroCraft Python site-packages", critical=False)

    check_import("simfire.sim.simulation", "SimFire package", critical=True)
    check_import("numpy", "NumPy", critical=True)
    check_import("rasterio", "rasterio (LandFire georeferencing)", critical=True)
    check_import("xarray", "xarray (ki_tools_common import chain)", critical=True)
    check_import("geopandas", "geopandas (MTBS perimeters)", critical=True)
    check_import("requests", "requests (LandFire/LFPS access)", critical=True)
    check_zarr_compatibility()

    check_file(MTBS_SHAPEFILE, "MTBS fire perimeters", critical=True)
    check_file(TRIPLETS, "diagnostic triplets", critical=False)
    check_tools_compile()
    check_lfps()

    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    print(f"\n  Results: {passed} passed, {failed} failed")
    if any(c["status"] != "pass" and c.get("critical") for c in checks):
        print("  STATUS: PREFLIGHT FAILED - fix blockers above before running SimFire")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with SimFire execution")
    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
