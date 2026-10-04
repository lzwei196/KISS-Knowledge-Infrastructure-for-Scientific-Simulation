#!/usr/bin/env python3
"""
Prepare a CE-QUAL-W2 v5 example for Linux.

Handles two common Windows-to-Linux porting issues:
1. Path separators: Replaces '.\InputFiles\' with '' (files in working directory)
2. Case sensitivity: Creates symlinks for case mismatches between w2_con.csv and actual files

Usage:
    python prepare_example_linux.py /path/to/example/directory
"""

import os
import sys
import re
import shutil
from pathlib import Path


def prepare_example(example_dir):
    example_dir = Path(example_dir)
    w2_con = example_dir / 'w2_con.csv'
    input_files_dir = example_dir / 'InputFiles'

    if not w2_con.exists():
        print(f"ERROR: {w2_con} not found")
        return False

    # Step 1: Copy InputFiles/ contents to working directory if not already there
    if input_files_dir.exists():
        for f in input_files_dir.iterdir():
            if f.is_file():
                dest = example_dir / f.name
                if not dest.exists():
                    shutil.copy2(str(f), str(dest))
                    print(f"  Copied: InputFiles/{f.name} -> {f.name}")

    # Step 2: Read w2_con.csv and fix paths
    with open(w2_con, 'r') as fh:
        content = fh.read()

    original = content

    # Replace Windows path separators: .\InputFiles\ or InputFiles\
    content = re.sub(r'\.\\InputFiles\\', '', content)
    content = re.sub(r'\.\\inputfiles\\', '', content, flags=re.IGNORECASE)
    content = re.sub(r'InputFiles\\', '', content, flags=re.IGNORECASE)
    # Also handle forward slash variants
    content = re.sub(r'\./InputFiles/', '', content)
    content = re.sub(r'InputFiles/', '', content, flags=re.IGNORECASE)

    if content != original:
        with open(w2_con, 'w') as fh:
            fh.write(content)
        print(f"  Fixed path separators in w2_con.csv")

    # Step 3: Extract all filenames referenced in w2_con.csv
    referenced_files = set()
    for line in content.split('\n'):
        # Match filenames at start of line (before first comma)
        parts = line.split(',')
        if parts:
            fname = parts[0].strip()
            if fname and ('.' in fname) and not fname.startswith('#'):
                # Check if it looks like a filename (has extension)
                ext = fname.rsplit('.', 1)[-1].lower()
                if ext in ('csv', 'npt', 'opt', 'dat'):
                    referenced_files.add(fname)

    # Step 4: For each referenced file, check if it exists (case-sensitive)
    # If not, try to find a case-insensitive match and create a symlink
    actual_files = {f.name: f for f in example_dir.iterdir() if f.is_file()}
    actual_lower = {f.name.lower(): f.name for f in example_dir.iterdir() if f.is_file()}

    for ref in referenced_files:
        ref_stripped = ref.strip()
        if ref_stripped in actual_files:
            continue  # Exact match exists

        # Try case-insensitive match
        ref_lower = ref_stripped.lower()
        if ref_lower in actual_lower:
            actual_name = actual_lower[ref_lower]
            symlink_path = example_dir / ref_stripped
            if not symlink_path.exists():
                os.symlink(actual_name, str(symlink_path))
                print(f"  Symlink: {ref_stripped} -> {actual_name} (case fix)")
        else:
            # Check if it's a file that will be created as output
            if ref_stripped.endswith('.opt') or 'not used' in ref_stripped.lower():
                pass  # Output files or placeholder entries
            else:
                print(f"  WARNING: Referenced file not found: {ref_stripped}")

    # Step 5: Also check for commonly referenced auxiliary files
    aux_files = ['w2_Algae_Toxin.csv', 'W2_Algae_Toxin.csv',
                 'w2_diagenesis.npt', 'W2_diagenesis.npt',
                 'w2_habitat.npt', 'W2_habitat.npt',
                 'w2_selective.npt', 'W2_selective.npt',
                 'w2_envirprf.npt', 'W2_envirprf.npt',
                 'w2_multiple_WB.npt', 'W2_multiple_WB.npt',
                 'w2_AlgaeMigration.csv', 'W2_AlgaeMigration.csv',
                 'w2_aerate.npt', 'W2_aerate.npt',
                 'w2_lake_river_contour.csv', 'W2_lake_river_contour.csv']

    for aux in aux_files:
        aux_path = example_dir / aux
        if not aux_path.exists():
            aux_lower = aux.lower()
            if aux_lower in actual_lower:
                actual_name = actual_lower[aux_lower]
                if actual_name != aux:
                    os.symlink(actual_name, str(aux_path))
                    print(f"  Symlink: {aux} -> {actual_name} (aux file case fix)")

    print(f"\n  Example prepared for Linux: {example_dir}")
    return True


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <example_directory>")
        sys.exit(1)

    success = prepare_example(sys.argv[1])
    sys.exit(0 if success else 1)
