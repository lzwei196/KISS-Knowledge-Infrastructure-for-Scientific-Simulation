#!/usr/bin/env python3
"""Build the pinned official RAPID and PETSc using genuine native Homebrew dependencies.
Run from the selected installation workspace, using its Python 3.11 venv.
This helper does not run a simulation or create case inputs.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tarfile
import time
import urllib.request

RAPID_COMMIT = '83145101ac8b49b8269e330cfc1372876fce8d7d'
PETSC_URL = 'https://web.cels.anl.gov/projects/petsc/download/release-snapshots/petsc-3.13.6.tar.gz'
PETSC_SHA256 = '02ca534a14c800a96f139f54530ac048b1727eb6703975920953bcb502771b1c'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', default='binaries/RAPID/source/repo')
    parser.add_argument('--deps', default='binaries/RAPID/deps')
    args = parser.parse_args()
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise SystemExit('This audited recipe is for native macOS arm64 only.')
    if sys.version_info[:2] != (3, 11):
        raise SystemExit('Use the genuine workspace Python 3.11 venv; legacy PETSc requires xdrlib/distutils.')
    import xdrlib  # noqa: F401; genuine Python 3.11 stdlib, no fabricated shim
    import distutils.sysconfig  # noqa: F401
    root = Path.cwd().resolve()
    repo, deps = Path(args.repo).resolve(), Path(args.deps).resolve()
    if not all(path.is_relative_to(root) and path != root for path in (repo, deps)):
        raise SystemExit('Source and dependency directories must be inside the installation workspace.')
    actual = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != RAPID_COMMIT:
        raise SystemExit('RAPID source commit does not match the audited pin.')
    if subprocess.check_output(['git', '-C', str(repo), 'status', '--porcelain', '--untracked-files=no'], text=True).strip():
        raise SystemExit('Refusing to build modified tracked RAPID source.')
    brew = Path('/opt/homebrew')
    for required in ('bin/nf-config', 'bin/nc-config', 'opt/mpich/bin/mpicc', 'opt/mpich/bin/mpif90', 'opt/openblas/lib/libopenblas.dylib'):
        if not (brew / required).is_file():
            raise SystemExit('Missing genuine native dependency: ' + str(brew / required))
    deps.mkdir(parents=True, exist_ok=True)
    records = []
    env = dict(os.environ, PATH=str(brew / 'bin') + ':' + os.environ.get('PATH', ''))
    env['MAKEFLAGS'] = '-j2'
    # On this audited host, MPICH/libfabric's default interface selection failed.
    # Caller supplies its verified FI_PROVIDER/FI_TCP_IFACE when needed.
    def run(name, command, cwd, timeout=1800):
        start = time.monotonic()
        logfile = deps / (name + '.log')
        with logfile.open('w') as stream:
            result = subprocess.run(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                    stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
        records.append(dict(step=name, argv=command, cwd=str(cwd), returncode=result.returncode,
                            seconds=round(time.monotonic() - start, 1), log=str(logfile)))
        (deps / 'native-build-receipt.json').write_text(json.dumps(records, indent=2) + '\n')
        print(name, 'returncode', result.returncode, flush=True)
        result.check_returncode()
    archive = deps / 'petsc-3.13.6.tar.gz'
    if not archive.exists():
        with urllib.request.urlopen(PETSC_URL, timeout=120) as response, archive.open('wb') as stream:
            while block := response.read(1024 * 1024):
                stream.write(block)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != PETSC_SHA256:
        raise SystemExit('PETSc source archive hash mismatch.')
    petsc = deps / 'petsc-3.13.6'
    if not petsc.exists():
        with tarfile.open(archive) as source:
            source.extractall(deps, filter='data')
    arch = 'arch-darwin-native'
    run('petsc-configure', [sys.executable, 'configure', 'PETSC_ARCH=' + arch,
        '--with-mpi-dir=/opt/homebrew/opt/mpich', '--with-blaslapack-dir=/opt/homebrew/opt/openblas',
        '--with-debugging=0', '--with-x=0', '--with-make-np=2'], petsc)
    run('petsc-build', ['make', 'PETSC_DIR=' + str(petsc), 'PETSC_ARCH=' + arch, 'all'], petsc)
    nf = str(brew / 'bin/nf-config')
    includes = subprocess.check_output([nf, '--fflags'], text=True).strip()
    libraries = subprocess.check_output([nf, '--flibs'], text=True).strip()
    libraries += ' ' + subprocess.check_output([str(brew / 'bin/nc-config'), '--libs'], text=True).strip()
    # The upstream Fortran makefile races .mod outputs under parallel make.
    run('rapid-build', ['make', '-j1', 'rapid', 'PETSC_DIR=' + str(petsc), 'PETSC_ARCH=' + arch,
                       'NETCDF_INCLUDE=' + includes, 'NETCDF_LIB=' + libraries], repo / 'src')
    print('Native product:', repo / 'src/rapid', flush=True)


if __name__ == '__main__':
    main()
