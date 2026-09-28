#!/usr/bin/env python3
"""Build the official NTSG-linked Biome-BGC4.2 C source; never run model cases."""
import argparse
import json
from pathlib import Path
import subprocess

PIN = 'f80d386d6d79ffe73dba46c28d15b40ee877d67b'
REPO = 'https://github.com/bpbond/Biome-BGC.git'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', nargs='?', default='.')
    args = parser.parse_args()
    source = Path(args.source).resolve()
    if not source.is_relative_to(Path.cwd().resolve()):
        raise SystemExit('Source must stay inside the working directory')
    source.mkdir(parents=True, exist_ok=True)
    commands = []
    def run(argv):
        commands.append(argv)
        subprocess.run(argv, check=True)
    if not (source / '.git').exists():
        if any(source.iterdir()):
            raise SystemExit('Source directory must be empty or an existing pinned checkout')
        run(['git', 'clone', '--filter=blob:none', '--no-checkout', REPO, str(source)])
        run(['git', '-C', str(source), 'sparse-checkout', 'init', '--no-cone'])
        run(['git', '-C', str(source), 'sparse-checkout', 'set', '/src/', '/USAGE.TXT', '/READ_ME_FIRST.TXT', '/CHANGES.TXT', '/copyright.txt', '/README.md'])
        run(['git', '-C', str(source), 'checkout', PIN])
    if subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip() != PIN:
        raise SystemExit('Wrong Biome-BGC source revision')
    # Serial upstream all target compiles the real model and companion utilities.
    # Never call the upstream test target: that performs scientific simulations.
    run(['/usr/bin/make', '-C', str(source / 'src'), 'ROOTDIR=' + str(source / 'src'), 'CC=/usr/bin/clang', '-j1', 'all'])
    product = source / 'bgc'
    kind = subprocess.check_output(['file', str(product)], text=True)
    if 'Mach-O' not in kind or 'arm64' not in kind:
        raise SystemExit('Native Apple Silicon model product missing')
    (source / 'native-build-receipt.json').write_text(json.dumps(dict(source_commit=PIN, commands=commands, product=str(product), scientific_execution=False), indent=2))


if __name__ == '__main__':
    main()
