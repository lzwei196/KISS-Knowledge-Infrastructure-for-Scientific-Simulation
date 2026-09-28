#!/usr/bin/env python3
"""Build KI-pinned SWAP4.2.0 and native TTUTIL4.2.7; never run a model."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import time


def blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', default='binaries/SWAP')
    args = parser.parse_args()
    if (platform.system(), platform.machine()) != ('Darwin', 'arm64'):
        raise SystemExit('This recipe requires native macOS arm64.')
    root = Path.cwd().resolve()
    prefix = Path(args.prefix).resolve()
    if prefix == root or not prefix.is_relative_to(root):
        raise SystemExit('Prefix must be a directory inside the installation workspace.')
    lock = json.loads(Path(__file__).with_name('macos-source-lock.json').read_text())
    env = dict(os.environ, FC='/opt/homebrew/bin/gfortran',
               FFLAGS='-O2 -ffree-line-length-none -fallow-argument-mismatch -std=legacy')
    if not Path(env['FC']).is_file():
        raise SystemExit('Install genuine native gfortran first.')
    for tool in ('meson', 'ninja', 'curl'):
        if shutil.which(tool) is None:
            raise SystemExit('Missing build tool: ' + tool)
    prefix.mkdir(parents=True, exist_ok=True)
    records = []
    def run(name, argv):
        start = time.monotonic()
        with (prefix / (name + '.log')).open('w') as stream:
            result = subprocess.run(argv, env=env, stdin=subprocess.DEVNULL,
                                    stdout=stream, stderr=subprocess.STDOUT, timeout=1800)
        records.append(dict(stage=name, argv=argv, returncode=result.returncode,
                            seconds=round(time.monotonic()-start, 3)))
        (prefix / 'build-receipt.json').write_text(json.dumps(records, indent=2)+'\n')
        if result.returncode:
            raise SystemExit('Build failed; inspect ' + str(prefix / (name + '.log')))
    for model, metadata in lock.items():
        source = prefix / 'source' / model
        for relative, expected in metadata['files'].items():
            target = source / relative
            if not target.resolve().is_relative_to(prefix):
                raise SystemExit('Unsafe source path')
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.is_file():
                url = 'https://raw.githubusercontent.com/SWAP-model/' + model + '/' + metadata['commit'] + '/' + relative
                subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error',
                                '--max-time', '60', url, '-o', str(target)], check=True)
            if target.is_symlink() or blob(target.read_bytes()) != expected:
                raise SystemExit('Pinned source hash mismatch: ' + str(target))
    # Preserve pinned original sources and isolate only the Meson platform adaptation.
    original = prefix / 'source' / 'swap'
    adapted = prefix / 'source' / 'repo'
    adapted.mkdir(parents=True, exist_ok=True)
    shutil.copytree(original / 'src', adapted / 'src', dirs_exist_ok=True)
    # Transparent CLI-only branch, before any model/file initialization.
    driver = adapted / 'src' / 'swap_main.f90'
    driver_text = driver.read_text()
    old_driver = "integer              :: getun\n\n! open logfile and read rerun file"
    new_driver = """integer              :: getun
character(len=132) :: Version
character(len=32) :: ki_cli_argument

! KI macOS installation-only CLI; version comes from upstream description.fi.
call get_command_argument(1, ki_cli_argument)
if (trim(ki_cli_argument) == '--version') then
   include 'description.fi'
   write(*,'(a)') 'SWAP '//trim(Version)
   stop
end if

! open logfile and read rerun file"""
    if driver_text.count(old_driver) != 1:
        raise SystemExit('Unexpected pinned SWAP main driver')
    driver.write_text(driver_text.replace(old_driver, new_driver))
    text = (original / 'meson.build').read_text()
    old = "link_args = ['-static']\n    executable_name = 'swap'"
    if text.count(old) != 1:
        raise SystemExit('Unexpected pinned non-Windows linker stanza')
    (adapted / 'meson.build').write_text(text.replace(old, "link_args = []\n    executable_name = 'swap'"))
    ttbuild = prefix / 'ttutil-build'
    build = adapted / 'build'
    run('ttutil-configure', ['meson','setup',str(ttbuild),str(prefix/'source'/'ttutil')] +
        (['--reconfigure'] if (ttbuild/'build.ninja').exists() else []))
    run('ttutil-build', ['ninja','-C',str(ttbuild),'-j1'])
    (build/'lib').mkdir(parents=True, exist_ok=True)
    shutil.copy2(ttbuild/'libttutil427.a',build/'lib'/'libttutil.a')
    run('swap-configure', ['meson','setup',str(build),str(adapted)] +
        (['--reconfigure'] if (build/'build.ninja').exists() else []))
    run('swap-build',['ninja','-C',str(build),'-j1'])
    print('Built genuine native SWAP at '+str(build/'swap'))
    print('No simulation or executable probe has been run by this helper.')

if __name__ == '__main__':
    main()
