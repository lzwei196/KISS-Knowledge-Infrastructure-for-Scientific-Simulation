#!/usr/bin/env python3
"""Build pinned native CTSM only; never submit/run a case or acquire inputdata."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

PIN = 'dae706a769a04ff13def0a909930c899a265368a'
SUBPINS = {'cime': '92ae0fd8133a3397a95f1cfcfa40dc138562f305',
           'ccs_config': '7c8bd604c818e4e832dda02b8584260fb7e22efc',
           'src/fates': '121723f64e94be97fd91fc95cfd1ba72dfc191ee'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', nargs='?', default='.')
    parser.add_argument('--runtime', default=os.environ.get('CTSM_NATIVE_RUNTIME'))
    parser.add_argument('--python', default=os.environ.get('CTSM_BUILD_PYTHON'))
    parser.add_argument('--configure-only', action='store_true')
    parser.add_argument('--build-stage', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    source = Path(args.source).absolute().resolve()
    config = {}
    for config_path in (source.parent.parent / 'ctsm-build-config.json', source / 'ctsm-build-config.json'):
        if config_path.is_file():
            config.update(json.loads(config_path.read_text()))
    native_path = args.runtime or config.get('native_runtime')
    if not native_path:
        raise SystemExit('Set --runtime or ctsm-build-config.json native_runtime to the genuine ESMF/PIO/MPICH/netCDF prefix')
    runtime = Path(native_path).resolve()
    python = Path(args.python or config.get('build_python') or sys.executable).absolute()  # Preserve venv launcher semantics.
    if not source.is_relative_to(Path.cwd().resolve()):
        raise SystemExit('Source must be inside the current workspace')
    for item in ('lib/esmf.mk', 'mod/esmf.mod', 'include/netcdf.mod', 'bin/mpifort', 'lib/libpioc.dylib'):
        if not (runtime / item).is_file():
            raise SystemExit('Missing genuine native development dependency: ' + str(runtime / item))
    (source / 'ctsm-build-config.json').write_text(json.dumps({'native_runtime': str(runtime), 'build_python': str(python)}, indent=2) + '\n')
    env = os.environ.copy()
    env.update(PATH=str(python.parent) + ':' + str(runtime / 'bin') + ':/opt/homebrew/bin:' + env.get('PATH', ''),
               CTSM_NATIVE_RUNTIME=str(runtime), MPICH_FC='/opt/homebrew/bin/gfortran',
               MPICH_CC='/usr/bin/clang', MPICH_CXX='/usr/bin/clang++',
               NETCDF_PATH=str(runtime), NETCDF_C_PATH=str(runtime), NETCDF_FORTRAN_PATH=str(runtime),
               PNETCDF_PATH=str(runtime), ESMFMKFILE=str(runtime / 'lib/esmf.mk'),
               ESMF_LIBDIR=str(runtime / 'lib'), CMAKE_PREFIX_PATH=str(runtime))
    if args.build_stage:
        if subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip() != PIN:
            raise SystemExit('Refusing wrong source')
        os.environ.update(env)
        os.environ['CIMEROOT'] = str(source / 'cime')
        sys.path.insert(0, str(source / 'cime'))
        from CIME.case import Case
        from CIME.build import case_build
        import logging
        logging.basicConfig(level=logging.INFO)
        casepath = source / 'ki-case'
        os.chdir(casepath)
        with Case(str(casepath), read_only=False, record=True) as case:
            libraries = case.get_values('CASE_SUPPORT_LIBRARIES')
            # Pinned CIME builds CLM as a shared component only when lnd is selected.
            if 'lnd' not in libraries:
                libraries.append('lnd')
            if not libraries:
                raise SystemExit('Pinned case has no support library declarations')
            # Upstream CLI choices omit CDEPS/csm_share. Use its public API with
            # actual case metadata, retaining all required native libraries.
            if not case_build(str(casepath), case, sharedlib_only=True, buildlist=libraries):
                raise SystemExit('CTSM support library build failed')
            # model_only suppresses namelists while buildlist=None links cesm.exe.
            if not case_build(str(casepath), case, model_only=True):
                raise SystemExit('CTSM native component/link build failed')
        return
    commands = []
    def run(argv, cwd=source):
        argv = [str(x) for x in argv]
        commands.append({'argv': argv, 'cwd': str(cwd)})
        print('+', ' '.join(argv), flush=True)
        logfile = source / ('ctsm-build-step-' + str(len(commands)) + '.log')
        print('Build log:', logfile, flush=True)
        with logfile.open('w') as log:
            result = subprocess.run(argv, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            print(logfile.read_text(errors='replace')[-16000:], flush=True)
            raise SystemExit('CTSM command failed rc=' + str(result.returncode) + '; retained log: ' + str(logfile))
    def head(path):
        return subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip()
    if head(source) != PIN:
        raise SystemExit('Refusing wrong CTSM source: expected ' + PIN)
    populated = all((source / sub).is_dir() and (source / sub / '.git').exists() for sub in SUBPINS)
    status = subprocess.check_output(['git', '-C', str(source), 'submodule', 'status'], text=True)
    if not populated or any(line.startswith('-') and 'doc/doc-builder' not in line for line in status.splitlines()):
        run([python, source / 'bin/git-fleximod', 'update'])
    for sub, pin in SUBPINS.items():
        if head(source / sub) != pin:
            raise SystemExit('Unexpected software submodule pin: ' + sub)
    # Customize the upstream Darwin machine only. Do not change physics or write HOME/.cime.
    machine_file = source / 'ccs_config/machines/homebrew/config_machines.xml'
    tree = ET.parse(machine_file)
    machine = tree.getroot()
    paths = {'CIME_OUTPUT_ROOT': source / 'ki-output', 'DIN_LOC_ROOT': source / 'ki-inputdata',
             'DIN_LOC_ROOT_CLMFORC': source / 'ki-inputdata', 'DOUT_S_ROOT': source / 'ki-archive',
             'BASELINE_ROOT': source / 'ki-baselines', 'CCSM_CPRNC': source / 'ki-tools/cprnc'}
    for key, value in paths.items():
        node = machine.find(key)
        if node is not None:
            node.text = str(value)
    variables = machine.find('environment_variables')
    for key in ('NETCDF_PATH', 'NETCDF_C_PATH', 'NETCDF_FORTRAN_PATH', 'PNETCDF_PATH', 'ESMFMKFILE', 'ESMF_LIBDIR'):
        node = next((n for n in variables if n.attrib.get('name') == key), None)
        if node is None:
            node = ET.SubElement(variables, 'env', {'name': key})
        node.text = env[key]
    tree.write(machine_file, encoding='unicode')
    cmake_file = source / 'ccs_config/machines/homebrew/gnu_homebrew.cmake'
    cmake_file.write_text('string(APPEND LDFLAGS " -framework Accelerate")\n' +
        ''.join('set(' + key + ' "' + env[key] + '")\n' for key in
                ('NETCDF_PATH', 'NETCDF_C_PATH', 'NETCDF_FORTRAN_PATH', 'PNETCDF_PATH', 'ESMF_LIBDIR')) +
        'set(SCC "/usr/bin/clang")\nset(SCXX "/usr/bin/clang++")\nset(SFC "/opt/homebrew/bin/gfortran")\n')
    case = source / 'ki-case'
    if not case.exists():
        run([python, source / 'cime/scripts/create_newcase', '--case', case,
             '--compset', 'I2000Clm50SpRsGs', '--res', 'f19_g17', '--machine', 'homebrew',
             '--compiler', 'gnu', '--mpilib', 'mpich', '--pecount', '1', '--run-unsupported'])
    run([python, case / 'xmlchange', ','.join(['EXEROOT=' + str(source / 'ki-build'),
         'RUNDIR=' + str(source / 'ki-run'), 'DIN_LOC_ROOT=' + str(source / 'ki-inputdata'),
         'DIN_LOC_ROOT_CLMFORC=' + str(source / 'ki-inputdata'), 'GET_REFCASE=FALSE', 'GMAKE_J=2'])], case)
    run([python, case / 'case.setup'], case)
    if not args.configure_only:
        run([python, Path(__file__).resolve(), source, '--runtime', runtime, '--python', python, '--build-stage'])
    receipt = {'source_commit': PIN, 'submodules': SUBPINS, 'runtime': str(runtime),
               'python': str(python), 'commands': commands, 'configure_only': args.configure_only,
               'native_product': str(source / 'ki-build/cesm.exe'),
               'scientific_execution': False, 'inputdata_download': False}
    (source / 'ctsm-build-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    if not args.configure_only and not (source / 'ki-build/cesm.exe').is_file():
        raise SystemExit('Native CTSM product missing after build')

if __name__ == '__main__':
    main()
