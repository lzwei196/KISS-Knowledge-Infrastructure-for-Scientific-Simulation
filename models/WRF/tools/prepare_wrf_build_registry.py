#!/usr/bin/env python3
"""Repair the audited WRF4.7.1 registry build-tool path overflow, without changing science code."""
import argparse
import hashlib
from pathlib import Path

ORIGINAL_SHA256 = 'bc771aec0981f21f91506cfc497f2b366ac55edb9e02b7a4bddb21ad01b25b80'
PATCHED_SHA256 = '992048ca60e7b472193ea84d82270cf8032562a304b49b2cc41257553e78bac7'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='binaries/WRF/source/repo')
    args = parser.parse_args()
    root = Path.cwd().resolve()
    source = Path(args.source).resolve()
    target = (source / 'tools/reg_parse.c').resolve()
    if not target.is_relative_to(root):
        raise SystemExit('WRF source must remain inside the selected installation workspace.')
    text = target.read_text()
    digest = hashlib.sha256(text.encode()).hexdigest()
    if digest == PATCHED_SHA256:
        print('Audited registry path repair already applied.')
        return
    if digest != ORIGINAL_SHA256:
        raise SystemExit('Refusing unknown or modified WRF registry source.')
    text = text.replace('char include_file_name_local_registry[128] ;\n      char include_file_name[128] ;', 'char include_file_name_local_registry[4096] ;\n      char include_file_name[4096] ;', 1)
    text = text.replace('        sprintf( include_file_name_local_registry, "./Registry/%s", p ) ;\n        sprintf( include_file_name, "%s/%s", dir , p ) ;', '        /* GeoForge Mac build repair: reject oversized paths instead of overflowing. */\n        int local_len = snprintf( include_file_name_local_registry,\n                                  sizeof(include_file_name_local_registry), "./Registry/%s", p );\n        int source_len = snprintf( include_file_name, sizeof(include_file_name), "%s/%s", dir, p );\n        if ( local_len < 0 || source_len < 0 ||\n             (size_t)local_len >= sizeof(include_file_name_local_registry) ||\n             (size_t)source_len >= sizeof(include_file_name) ) {\n          fprintf(stderr, "Registry include path exceeds supported length\\n");\n          return 1;\n        }', 1)
    if hashlib.sha256(text.encode()).hexdigest() != PATCHED_SHA256:
        raise SystemExit('Patched source hash did not match audited result.')
    target.write_text(text)
    print('Applied checked registry path repair. Rebuild the registry executable before code generation.')


if __name__ == '__main__':
    main()
