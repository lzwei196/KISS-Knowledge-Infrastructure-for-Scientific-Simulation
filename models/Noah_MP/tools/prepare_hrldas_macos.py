"""Prepare pinned official HRLDAS v5.2.0 for case-insensitive macOS volumes.

Only build files change; never modify model Fortran or create scientific inputs.
"""
import argparse
from pathlib import Path
import subprocess


def main():
    p = argparse.ArgumentParser()
    p.add_argument('source', type=Path)
    a = p.parse_args()
    root = a.source.resolve()
    root.relative_to(Path.cwd().resolve())
    for directory, commit in [(root, 'd9f5b205a9cdee10d9875e656c1b633a539012e2'),
                              (root / 'noahmp', '9fbe672420f4468e7d78aecfd10626927ecc8156')]:
        actual = subprocess.check_output(['git', '-C', str(directory), 'rev-parse', 'HEAD'], text=True).strip()
        if actual != commit:
            raise SystemExit(f'Unexpected upstream revision: {directory}')
    for relative in ['utility/Makefile', 'src/Makefile', 'drivers/hrldas/Makefile']:
        path = root / 'noahmp' / relative
        content = path.read_text()
        if '.ki-preprocessed.f90' not in content:
            # Machine.F90 and Machine.f90 name the SAME file on default APFS.
            # Preserve source, give the intermediate a distinct basename, and
            # explicitly retain upstream object filenames when compiling it.
            content = content.replace('.f90', '.ki-preprocessed.f90')
            content = content.replace('$(COMPILERF90) -c', '$(COMPILERF90) -o $(@) -c')
            path.write_text(content)
    include = subprocess.check_output(['nf-config', '--fflags'], text=True).strip()
    libs = subprocess.check_output(['nf-config', '--flibs'], text=True).strip()
    libs += ' ' + subprocess.check_output(['nc-config', '--libs'], text=True).strip()
    options = root / 'hrldas/user_build_options'
    options.write_text(f'''COMPILERF90 = gfortran
FREESOURCE = -ffree-form -ffree-line-length-none
F90FLAGS = -O2 -fconvert=big-endian -fno-range-check -fallow-argument-mismatch
MODFLAG =
LDFLAGS =
CPP = /usr/bin/cpp
CPPFLAGS = -P -traditional -D_GFORTRAN_
LIBS =
NETCDFMOD = {include}
NETCDFLIB = {libs}
BZIP2 = NO
RM = rm -f
CC = cc
''')
    print('Prepared pinned HRLDAS makefiles and genuine netCDF-Fortran toolchain.')

if __name__ == '__main__':
    main()
