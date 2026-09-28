"""Explicit, source-bound bundled Python variants; never official upstream proof."""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import tempfile

VARIANTS = {
    'HEC_HMS': ('hec-hms-python-equiv', 'tools/run_hec_hms.py'),
    'KINEROS2': ('hydrocraft-kineros2-lumped', 'tools/run_kineros2.py'),
    'LPJ_GUESS': ('lpj-guess-analytic', 'tools/run_lpjguess.py'),
    'QUINCY': ('quincy-analytic-py', 'tools/run_quincy.py'),
    'WASP': ('hydrocraft-wasp', 'tools/run_wasp.py'),
    'VELMA': ('velma-python-4layer', 'tools/run_velma.py'),
}

def resolve(ki, contract):
    """Validate the declared identity and exact materialized source before execution."""
    if not isinstance(contract, dict) or set(contract) != {'implementation_id', 'path', 'sha256'}:
        raise ValueError('python_script requires exactly implementation_id, path, sha256')
    expected = VARIANTS.get(getattr(ki, 'name', ''))
    if not expected or (contract['implementation_id'], contract['path']) != expected:
        raise ValueError('Unrecognized declared Python implementation or runner path')
    if (getattr(ki, 'meta', {}) or {}).get('impl_id') != expected[0]:
        raise ValueError('Python implementation ID does not match KI metadata')
    digest = contract['sha256']
    if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
        raise ValueError('Invalid Python source SHA256')
    root = Path(ki.root).absolute()
    path = root / contract['path']
    if root.is_symlink() or any(p.is_symlink() for p in [path, *path.parents] if p == root or root in p.parents):
        raise ValueError('Symlink substitutes are not permitted for the Python runner')
    if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError('Declared Python source is missing or outside the KI')
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError('Declared Python source SHA256 mismatch')
    return path

def check(v, ki, contract, cfg, python, env=None, timeout=25):
    v.kind = 'declared python script'
    v.needs_binary = True
    v.installation_scope = 'declared-python-variant'
    v.official_upstream_verified = False
    v.implementation_id = contract.get('implementation_id', '') if isinstance(contract, dict) else ''
    try:
        path = resolve(ki, contract)
        v.binary = str(path)
        v.present = v.shaped = True
        if cfg is None or not path.resolve().is_relative_to(Path(cfg.root).resolve()):
            raise ValueError('Declared runner must be in the configured workspace')
        runtime = subprocess.run([python, '-c', 'import json,sys;print(json.dumps([sys.prefix,sys.base_prefix]))'],
                                 stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env, timeout=10)
        if runtime.returncode:
            raise ValueError('Workspace Python did not start')
        prefix, base = json.loads(runtime.stdout)
        if prefix == base or not Path(prefix).resolve().is_relative_to(Path(cfg.root).resolve()):
            raise ValueError('Declared Python variant requires a real workspace venv')
        if not v.imports_ok:
            v.detail = 'Required workspace Python imports failed'
            return v
        v.linked = True
        v.probe_command = [python, '-B', str(path), '--help']
        with tempfile.TemporaryDirectory(prefix='kiss-python-help-') as cwd:
            try:
                result = subprocess.run(v.probe_command, cwd=cwd, env=env,
                                        stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                        timeout=min(max(timeout, 1), 25))
                v.probe_returncode = result.returncode
                v.probe_output = (result.stdout + '\n' + result.stderr).strip()[-16000:]
            except subprocess.TimeoutExpired as exc:
                v.probe_timed_out = True
                v.detail = 'Declared Python help probe timed out'
            v.probe_created_paths = [str(p.relative_to(cwd)) for p in Path(cwd).rglob('*')]
        # Recheck source binding after execution; do not accept a replaced runner.
        resolve(ki, contract)
        v.responds = (not v.probe_timed_out and v.probe_returncode == 0 and
                      not v.probe_created_paths and 'usage:' in v.probe_output.lower() and
                      path.name in v.probe_output)
        if not v.detail:
            v.detail = ('Declared implementation help passed; official upstream unverified' if v.responds
                        else 'Declared Python help must return 0, identify its runner, and create no files')
    except (ValueError, TypeError, OSError, subprocess.SubprocessError) as exc:
        v.responds = False
        v.detail = str(exc)
    return v
