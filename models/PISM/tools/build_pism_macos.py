#!/usr/bin/env python3
"""Build pinned PISM/PETSc with host MPI/GSL/NetCDF and isolated FFTW/UDUNITS.
Run from the selected installation workspace, using its Python 3.11 venv.
This helper does not run a simulation or create case inputs.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request

PISM_COMMIT = '79cae578d27cf90742be04c0c5a8bcf262da41ca'
PETSC_URL = 'https://web.cels.anl.gov/projects/petsc/download/release-snapshots/petsc-3.21.4.tar.gz'
PETSC_SHA256 = 'a9ae076d4617c7d84ce2bed37194022319c19f19b3930edf148b2bc8ecf2248d'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', default='binaries/PISM/source/repo')
    parser.add_argument('--deps', default='binaries/PISM/deps')
    parser.add_argument('--runtime-deps', default='binaries/PISM/deps/runtime')
    parser.add_argument('--build')
    parser.add_argument('--runtime-prefix')
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
    runtime_deps = Path(args.runtime_deps).resolve()
    build = Path(args.build).resolve() if args.build else repo / 'build'
    runtime_prefix = Path(args.runtime_prefix).resolve() if args.runtime_prefix else repo / 'runtime'
    if not all(path.is_relative_to(root) and path != root for path in (runtime_deps, build, runtime_prefix)):
        raise SystemExit('Build and runtime directories must stay inside the workspace.')
    for relative in ('include/fftw3.h', 'include/udunits2.h', 'lib/libfftw3.dylib', 'lib/libudunits2.dylib', 'share/udunits/udunits2.xml'):
        if not (runtime_deps / relative).is_file():
            raise SystemExit('Missing genuine isolated dependency: ' + str(runtime_deps / relative))
    actual = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != PISM_COMMIT:
        raise SystemExit('PISM source commit does not match the audited pin.')
    if subprocess.check_output(['git', '-C', str(repo), 'status', '--porcelain', '--untracked-files=no'], text=True).strip():
        raise SystemExit('Refusing to build modified tracked PISM source.')
    brew = Path('/opt/homebrew')
    for required in ('opt/mpich/bin/mpicc', 'opt/mpich/bin/mpicxx', 'opt/mpich/bin/mpif90', 'opt/netcdf/bin/ncgen', 'opt/gsl/lib/libgsl.dylib'):
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
    arch = 'arch-darwin-pism'
    run('petsc-configure', [sys.executable, 'configure', 'PETSC_ARCH=' + arch,
        '--with-mpi-dir=/opt/homebrew/opt/mpich', '--with-blaslapack-lib=-llapack -lblas',
        '--with-debugging=0', '--with-x=0', '--with-make-np=2',
        '--with-hdf5=0'], petsc)
    if not (petsc / arch / 'lib/petsc/conf/petscvariables').is_file():
        raise SystemExit('PETSc configure did not produce its native build configuration.')
    run('petsc-build', ['make', 'PETSC_DIR=' + str(petsc), 'PETSC_ARCH=' + arch, 'all'], petsc)
    env.update(PETSC_DIR=str(petsc), PETSC_ARCH=arch,
               PKG_CONFIG_PATH=':'.join([str(petsc / arch / 'lib/pkgconfig'),
                   str(runtime_deps / 'lib/pkgconfig'), '/opt/homebrew/opt/gsl/lib/pkgconfig',
                   '/opt/homebrew/opt/netcdf/lib/pkgconfig']),
               UDUNITS2_XML_PATH=str(runtime_deps / 'share/udunits/udunits2.xml'),
               OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
    run('pism-configure', ['cmake', '-S', str(repo), '-B', str(build),
        '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_INSTALL_PREFIX=' + str(runtime_prefix),
        '-DCMAKE_C_COMPILER=/opt/homebrew/opt/mpich/bin/mpicc',
        '-DCMAKE_CXX_COMPILER=/opt/homebrew/opt/mpich/bin/mpicxx',
        '-DCMAKE_PREFIX_PATH=' + str(runtime_deps), '-DUDUNITS2_ROOT=' + str(runtime_deps),
        '-DPism_BUILD_PYTHON_BINDINGS=OFF', '-DPism_ENABLE_DOCUMENTATION=OFF',
        '-DPism_BUILD_DOCS=OFF', '-DPism_USE_PARALLEL_NETCDF4=OFF', '-DPism_USE_PNETCDF=OFF'], repo)
    run('pism-build', ['cmake', '--build', str(build), '--target', 'pism', '--parallel', '2'], repo)
    # The upstream native target generates this configuration from its distributed CDL.
    # Keep its genuine bytes at the compiled-in runtime location; this is not a model input.
    config = runtime_prefix / 'share/pism/pism_config.nc'
    config.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(build / 'pism_config.nc', config)
    print('Native product:', build / 'pism', flush=True)


if __name__ == '__main__':
    main()
