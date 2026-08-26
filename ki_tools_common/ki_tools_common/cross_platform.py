"""
cross_platform.py — Binary detection and cross-platform execution.

Handles ELF binaries (native Linux), PE32 executables (Windows via Wine),
and broken ELF interpreter paths (e.g., from Compute Canada HPC builds).

Out of 123 HydroCraft models:
  - ~77 use native ELF binaries (Fortran/C compiled)
  - DLBreach uses Wine (PE32 console binary)
  - DNDC is PE32 GUI — doesn't work headless
  - RZWQM2 needed patchelf for broken ELF interpreter

Usage::

    from ki_tools_common.cross_platform import detect_binary_type, run_binary

    info = detect_binary_type('/path/to/model.exe')
    print(info['type'], info['runnable'], info['method'])

    result = run_binary('/path/to/model.exe', workdir='/tmp/run')
    print(result['exit_code'], result['method'])
"""

import os
import struct
import subprocess
import shutil
import time
from typing import Dict, List, Optional


def detect_binary_type(path: str) -> Dict:
    """Read magic bytes to classify a binary file.

    Returns:
        dict with:
          'type': 'elf_native' | 'pe32_console' | 'pe32_gui' | 'elf_broken_interp' | 'unknown'
          'runnable': bool — can this binary be executed on this system?
          'method': str — how to run it ('direct', 'wine', 'patchelf_needed', 'unsupported')
          'issues': list[str] — problems found
          'details': dict — type-specific details (interpreter path, PE subsystem, etc.)
    """
    result = {
        'type': 'unknown',
        'runnable': False,
        'method': 'unsupported',
        'issues': [],
        'details': {},
    }

    if not os.path.isfile(path):
        result['issues'].append(f'File not found: {path}')
        return result

    try:
        with open(path, 'rb') as f:
            magic = f.read(4)

            # ELF binary
            if magic[:4] == b'\x7fELF':
                return _analyze_elf(f, path, result)

            # PE (MZ header)
            if magic[:2] == b'MZ':
                return _analyze_pe(f, path, result)

            result['issues'].append(f'Unknown magic bytes: {magic.hex()}')
            return result

    except Exception as e:
        result['issues'].append(f'Failed to read binary: {e}')
        return result


def _analyze_elf(f, path, result):
    """Analyze an ELF binary."""
    f.seek(0)
    header = f.read(64)

    # ELF class: 32 or 64 bit
    ei_class = header[4]
    result['details']['bits'] = 32 if ei_class == 1 else 64

    # Find PT_INTERP (program interpreter)
    # ELF header: e_phoff at offset 32 (64-bit) or 28 (32-bit)
    if ei_class == 2:  # 64-bit
        e_phoff = struct.unpack_from('<Q', header, 32)[0]
        e_phentsize = struct.unpack_from('<H', header, 54)[0]
        e_phnum = struct.unpack_from('<H', header, 56)[0]
    else:
        e_phoff = struct.unpack_from('<I', header, 28)[0]
        e_phentsize = struct.unpack_from('<H', header, 42)[0]
        e_phnum = struct.unpack_from('<H', header, 44)[0]

    interp = None
    for i in range(min(e_phnum, 20)):
        f.seek(e_phoff + i * e_phentsize)
        phdr = f.read(e_phentsize)
        p_type = struct.unpack_from('<I', phdr, 0)[0]
        if p_type == 3:  # PT_INTERP
            if ei_class == 2:
                p_offset = struct.unpack_from('<Q', phdr, 8)[0]
                p_filesz = struct.unpack_from('<Q', phdr, 32)[0]
            else:
                p_offset = struct.unpack_from('<I', phdr, 4)[0]
                p_filesz = struct.unpack_from('<I', phdr, 16)[0]
            f.seek(p_offset)
            interp = f.read(p_filesz).rstrip(b'\x00').decode('ascii', errors='replace')
            break

    result['details']['interpreter'] = interp

    if interp and os.path.isfile(interp):
        result['type'] = 'elf_native'
        result['runnable'] = True
        result['method'] = 'direct'
    elif interp:
        result['type'] = 'elf_broken_interp'
        result['runnable'] = False
        result['method'] = 'patchelf_needed'
        result['issues'].append(
            f'ELF interpreter not found: {interp}. '
            f'Fix: patchelf --set-interpreter /lib64/ld-linux-x86-64.so.2 {path}'
        )
    else:
        # Static binary or couldn't find interp
        result['type'] = 'elf_native'
        result['runnable'] = True
        result['method'] = 'direct'

    return result


def _analyze_pe(f, path, result):
    """Analyze a PE (Windows) binary."""
    f.seek(0x3C)
    pe_offset = struct.unpack_from('<I', f.read(4))[0]

    f.seek(pe_offset)
    pe_sig = f.read(4)
    if pe_sig != b'PE\x00\x00':
        result['issues'].append('Invalid PE signature')
        return result

    # COFF header
    f.seek(pe_offset + 4)
    machine = struct.unpack_from('<H', f.read(2))[0]
    result['details']['machine'] = hex(machine)

    # Optional header — SUBSYSTEM at offset 0x5C from PE sig for PE32
    f.seek(pe_offset + 0x5C)
    subsystem = struct.unpack_from('<H', f.read(2))[0]
    result['details']['subsystem'] = subsystem

    wine_ok = check_wine_available()

    if subsystem == 3:  # IMAGE_SUBSYSTEM_WINDOWS_CUI (Console)
        result['type'] = 'pe32_console'
        if wine_ok['available']:
            result['runnable'] = True
            result['method'] = 'wine'
        else:
            result['runnable'] = False
            result['method'] = 'wine_needed'
            result['issues'].append('Wine not installed. Install: sudo apt install wine')
    elif subsystem == 2:  # IMAGE_SUBSYSTEM_WINDOWS_GUI
        result['type'] = 'pe32_gui'
        result['runnable'] = False
        result['method'] = 'unsupported'
        result['issues'].append(
            'GUI binary — cannot run headless. Options: '
            '(1) Recompile from source for Linux, '
            '(2) xvfb-run wine model.exe -batch (if model has batch mode)'
        )
    else:
        result['type'] = 'pe32_console'  # Assume console for unknown subsystem
        if wine_ok['available']:
            result['runnable'] = True
            result['method'] = 'wine'
        else:
            result['issues'].append(f'Unknown PE subsystem {subsystem}. Wine not available.')

    return result


def run_binary(binary_path: str, args: Optional[List[str]] = None,
               workdir: Optional[str] = None, stdin_text: Optional[str] = None,
               timeout: int = 3600, env: Optional[Dict] = None) -> Dict:
    """Auto-detect binary type and execute.

    Returns:
        dict with: exit_code, stdout, stderr, method, runtime_s
    """
    info = detect_binary_type(binary_path)

    if not info['runnable']:
        raise RuntimeError(
            f"Cannot execute {binary_path}: {info['type']}. "
            f"Issues: {'; '.join(info['issues'])}"
        )

    if info['method'] == 'direct':
        cmd = [binary_path] + (args or [])
    elif info['method'] == 'wine':
        run_env = dict(os.environ)
        run_env['WINEDEBUG'] = '-all'
        if env:
            run_env.update(env)
        env = run_env
        cmd = ['wine', binary_path] + (args or [])
    else:
        raise RuntimeError(f"Unsupported method: {info['method']}")

    start = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=workdir,
            capture_output=True,
            timeout=timeout,
            input=stdin_text.encode() if stdin_text else None,
            env=env,
        )
        elapsed = time.time() - start

        result = {
            'exit_code': proc.returncode,
            'stdout': proc.stdout.decode('utf-8', errors='replace'),
            'stderr': proc.stderr.decode('utf-8', errors='replace'),
            'method': info['method'],
            'runtime_s': round(elapsed, 1),
        }

        # Wine exit codes are unreliable — warn if using wine
        if info['method'] == 'wine' and proc.returncode == 0:
            result['wine_warning'] = (
                'Wine returned exit code 0, but this is not reliable. '
                'Always verify output files exist.'
            )

        return result

    except subprocess.TimeoutExpired:
        return {
            'exit_code': -1,
            'stdout': '',
            'stderr': f'Timeout after {timeout}s',
            'method': info['method'],
            'runtime_s': timeout,
        }


def fix_elf_interpreter(binary_path: str, output_path: Optional[str] = None) -> str:
    """Fix broken ELF interpreter using patchelf.

    Args:
        binary_path: Path to the ELF binary with broken interpreter
        output_path: Where to write the fixed binary (default: overwrite in place)

    Returns:
        Path to the fixed binary
    """
    patchelf = shutil.which('patchelf')
    if not patchelf:
        raise RuntimeError(
            'patchelf not installed. Install: sudo apt install patchelf'
        )

    target = output_path or binary_path
    if output_path and output_path != binary_path:
        shutil.copy2(binary_path, output_path)

    interp = '/lib64/ld-linux-x86-64.so.2'
    if not os.path.isfile(interp):
        interp = '/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2'

    proc = subprocess.run(
        [patchelf, '--set-interpreter', interp, target],
        capture_output=True
    )
    if proc.returncode != 0:
        raise RuntimeError(f'patchelf failed: {proc.stderr.decode()}')

    return target


def check_wine_available() -> Dict:
    """Check if Wine is installed and return version info."""
    wine_path = shutil.which('wine')
    if not wine_path:
        return {'available': False, 'version': None, 'path': None}

    try:
        proc = subprocess.run(
            ['wine', '--version'], capture_output=True, timeout=10
        )
        version = proc.stdout.decode().strip()
        return {'available': True, 'version': version, 'path': wine_path}
    except Exception:
        return {'available': True, 'version': 'unknown', 'path': wine_path}
