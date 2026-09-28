#!/usr/bin/env python3
"""Build the pinned official PFLOTRAN and PETSc using genuine native Homebrew dependencies.
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

PFLOTRAN_COMMIT = 'fab315dc6559306f2f93b27571bf5add812dd820'
PETSC_URL = 'https://web.cels.anl.gov/projects/petsc/download/release-snapshots/petsc-3.21.4.tar.gz'
PETSC_SHA256 = 'a9ae076d4617c7d84ce2bed37194022319c19f19b3930edf148b2bc8ecf2248d'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', default='binaries/PFLOTRAN/source/repo')
    parser.add_argument('--deps', default='binaries/PFLOTRAN/deps')
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
    if actual != PFLOTRAN_COMMIT:
        raise SystemExit('PFLOTRAN source commit does not match the audited pin.')
    if subprocess.check_output(['git', '-C', str(repo), 'status', '--porcelain', '--untracked-files=no'], text=True).strip():
        raise SystemExit('Refusing to build modified tracked PFLOTRAN source.')
    brew = Path('/opt/homebrew')
    for required in ('opt/mpich/bin/mpicc', 'opt/mpich/bin/mpif90'):
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
    archive = deps / 'petsc-3.21.4.tar.gz'
    if not archive.exists():
        with urllib.request.urlopen(PETSC_URL, timeout=120) as response, archive.open('wb') as stream:
            while block := response.read(1024 * 1024):
                stream.write(block)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != PETSC_SHA256:
        raise SystemExit('PETSc source archive hash mismatch.')
    petsc = deps / 'petsc-3.21.4'
    if not petsc.exists():
        with tarfile.open(archive) as source:
            source.extractall(deps, filter='data')
    arch = 'arch-darwin-pflotran'
    run('petsc-configure', [sys.executable, 'configure', 'PETSC_ARCH=' + arch,
        '--with-mpi-dir=/opt/homebrew/opt/mpich', '--with-blaslapack-lib=-llapack -lblas',
        '--with-debugging=0', '--with-x=0', '--with-make-np=2',
        '--download-hdf5', '--with-hdf5-fortran-bindings=1'], petsc)
    run('petsc-build', ['make', 'PETSC_DIR=' + str(petsc), 'PETSC_ARCH=' + arch, 'all'], petsc)
    # PFLOTRAN expects bare directories; PETSc's HDF5 variables contain flag strings.
    # Pass these explicitly on the command line to avoid -I-I and -L-L corruption.
    run('pflotran-build', ['make', '-j2', 'pflotran', 'PETSC_DIR=' + str(petsc), 'PETSC_ARCH=' + arch,
        'have_hdf5=1', 'HDF5_INCLUDE=' + str(petsc / arch / 'include'),
        'HDF5_LIB=' + str(petsc / arch / 'lib')], repo / 'src/pflotran')
    print('Native product:', repo / 'src/pflotran/pflotran', flush=True)



if __name__ == '__main__':
    main()
