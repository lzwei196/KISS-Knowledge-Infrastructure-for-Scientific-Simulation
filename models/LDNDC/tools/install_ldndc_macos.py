#!/usr/bin/env python3
"""Install verified official LDNDC1.37 arm64 software without model cases or HOME writes."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import platform
import subprocess
import tarfile

URL = 'https://ldndc.imk-ifu.kit.edu/ldndc/downloads/public/packages/mac64/ldndc-1.37.mac64.2026-03-03.tar.bz2'
SHA256 = '6b0bd740ae1cbecf2c92c412f58466c6f88aa3bb0c71c60c48070e8f214566ce'
BINARY_SHA256 = '9697491f237cd80971a26f858e642e4f5e0e8d6a586a8a8930c8613aa9db49a0'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', default='binaries/ldndc/ldndc-1.37.mac64')
    args=parser.parse_args()
    if (platform.system(), platform.machine()) != ('Darwin','arm64'):
        raise SystemExit('This official binary is native macOS arm64.')
    root=Path.cwd().resolve();prefix=Path(args.prefix).resolve()
    if prefix==root or not prefix.is_relative_to(root):raise SystemExit('Prefix must remain inside workspace')
    prefix.mkdir(parents=True,exist_ok=True);archive=prefix.parent/'ldndc-1.37.mac64.tar.bz2'
    subprocess.run(['curl','--fail','--location','--silent','--show-error','--max-time','600',URL,'-o',str(archive)],check=True)
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=SHA256:raise SystemExit('Official archive SHA256 mismatch')
    extracted=[]
    with tarfile.open(archive,'r:bz2') as tar:
        for member in tar:
            parts=PurePosixPath(member.name).parts
            if not parts or parts[0]!='ldndc-1.37.mac64' or '..' in parts:raise SystemExit('Unsafe archive member')
            relative=PurePosixPath(*parts[1:])
            if not relative.parts:continue
            if relative.parts[0]!='bin' and str(relative) not in {'Lresources','LICENSE','revision','ldndc.conf'}:continue
            destination=prefix.joinpath(*relative.parts)
            if not destination.resolve().is_relative_to(prefix) or destination.is_symlink():raise SystemExit('Unsafe destination')
            if member.isdir():destination.mkdir(parents=True,exist_ok=True);continue
            if not member.isfile():raise SystemExit('Unexpected nonregular software member')
            data=tar.extractfile(member).read();destination.parent.mkdir(parents=True,exist_ok=True)
            destination.write_bytes(data);destination.chmod(0o755 if relative.parts[0]=='bin' else 0o644)
            extracted.append(str(relative))
    binary=prefix/'bin/ldndc'
    if hashlib.sha256(binary.read_bytes()).hexdigest()!=BINARY_SHA256:raise SystemExit('Native executable SHA256 mismatch')
    (prefix/'installation-receipt.json').write_text(json.dumps(dict(url=URL,archive_sha256=SHA256,binary_sha256=BINARY_SHA256,software_members=extracted),indent=2)+'\n')
    print('Installed genuine LDNDC software at '+str(prefix))
    print('No installer script or model execution was performed.')

if __name__=='__main__':main()
