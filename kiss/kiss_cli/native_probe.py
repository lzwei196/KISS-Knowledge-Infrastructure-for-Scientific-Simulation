"""Audited distributed runtime assets for installation-only native startup."""
from __future__ import annotations
import hashlib
from pathlib import Path
import re
import stat

TELEMAC_DICO_SHA256 = '984985dabe1deba5c22d2b1a14ce07f2e38fc720aed071eef5512f72c9e46309'
# Installation probes must not stage arbitrary scientific inputs. Expand this
# audited set only with upstream evidence for a distributed runtime asset.
AUDITED_ASSETS = {'TELEMAC_MASCARET': {'T2DDICO': TELEMAC_DICO_SHA256}}


def stage_runtime_assets(contract, root: Path, destination: Path, model: str) -> list[dict]:
    if contract is None:
        return []
    if not isinstance(contract, dict) or set(contract) != {'runtime_assets'}:
        raise ValueError('native_probe requires only runtime_assets')
    assets = contract['runtime_assets']
    if not isinstance(assets, list) or not assets or len(assets) > 8:
        raise ValueError('runtime_assets must be a nonempty bounded list')
    root = Path(root).resolve(strict=True)
    destination = Path(destination)
    if not destination.is_dir() or any(destination.iterdir()):
        raise ValueError('runtime asset destination must be a fresh empty directory')
    pending, seen = [], set()
    for asset in assets:
        if not isinstance(asset, dict) or set(asset) != {'source', 'target', 'sha256'}:
            raise ValueError('runtime asset requires source, target, sha256')
        source, target, digest = (asset[k] for k in ('source', 'target', 'sha256'))
        if not all(isinstance(v, str) for v in (source, target, digest)):
            raise ValueError('runtime asset fields must be strings')
        rel = Path(source)
        if rel.is_absolute() or '..' in rel.parts or not rel.parts:
            raise ValueError('runtime source must be relative within installation root')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', target) or target in seen:
            raise ValueError('runtime target must be a unique safe filename')
        if not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError('runtime asset requires exact SHA-256')
        if AUDITED_ASSETS.get(model, {}).get(target) != digest:
            raise ValueError('runtime asset is not an audited installation-only resource')
        candidate = root / rel
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(root) or candidate.is_symlink():
            raise ValueError('runtime asset escapes root or is a symlink')
        if not stat.S_ISREG(candidate.stat().st_mode):
            raise ValueError('runtime asset must be a regular file')
        if candidate.stat().st_size > 2 * 1024 * 1024:
            raise ValueError('runtime asset exceeds bounded size')
        data = candidate.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('runtime asset SHA-256 mismatch')
        pending.append((target, data, {'source': source, 'target': target, 'sha256': digest}))
        seen.add(target)
    # Validate every item before copying any verified original bytes.
    for target, data, _ in pending:
        with (destination / target).open('xb') as f:
            f.write(data)
    return [receipt for _, _, receipt in pending]


def telemac_case_boundary(model: str, output: str, returncode: int, receipts: list[dict]) -> bool:
    if model != 'TELEMAC_MASCARET' or returncode != 2:
        return False
    if not any(r.get('target') == 'T2DDICO' and r.get('sha256') == TELEMAC_DICO_SHA256 for r in receipts):
        return False
    if not re.search(r'(?m)^\s*2D\s+VERSION 9\.1\s+FORTRAN 2003\s*$', output):
        return False
    diagnostic = "Fortran runtime error: Cannot open file 'T2DCAS': No such file or directory"
    if diagnostic not in output.splitlines():
        return False
    remaining = output.replace(diagnostic, '')
    if re.search(r'(?i)fortran runtime error|no such file|library not loaded|dyld:|segmentation|sigsegv|symbol not found', remaining):
        return False
    return True

CTSM_DRIVER_SHA256 = '1b98e239a5408e11b0e8b140b9f6ff7cade9388e537d3664830dee699fac17a4'


def ctsm_case_boundary(model: str, binary: Path, root: Path, output: str, returncode: int) -> bool:
    """Pinned CMEPS opens its scientific debug namelist before model initialization."""
    build_dir = {'CLM5___CTSM': 'ki-build', 'FATES': 'ki-fates-build'}.get(model)
    if build_dir is None or returncode != 2 or binary.name != 'cesm.exe':
        return False
    diagnostic = "Fortran runtime error: Cannot open file 'drv_in': No such file or directory"
    if diagnostic not in output.splitlines():
        return False
    if not re.search(r'(?m)^At line 54 of file .*/components/cmeps/(?:cime_config/\.\./)?cesm/driver/esmApp\.F90\s*$', output.replace("\\", "/")):
        return False
    remaining = output.replace(diagnostic, '')
    if re.search(r'(?i)fortran runtime error|no such file|library not loaded|dyld:|segmentation|sigsegv|symbol not found', remaining):
        return False
    try:
        root = Path(root).resolve(strict=True)
        binary = Path(binary).resolve(strict=True)
        source = binary.parent.parent / 'components/cmeps/cesm/driver/esmApp.F90'
        if binary.parent.name != build_dir or not binary.is_relative_to(root):
            return False
        if source.is_symlink() or not source.resolve(strict=True).is_relative_to(root):
            return False
        if not source.is_file() or source.stat().st_size > 1024 * 1024:
            return False
        return hashlib.sha256(source.read_bytes()).hexdigest() == CTSM_DRIVER_SHA256
    except (OSError, ValueError):
        return False
