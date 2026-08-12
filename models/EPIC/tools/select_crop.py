#!/usr/bin/env python3
"""Browse CROPCOM.DAT and return crop code / name / key parameters.

Usage:
    python select_crop.py --list
    python select_crop.py --name CORN
    python select_crop.py --code 2
"""
import argparse
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import template_path, read_text_crlf


def load_crops():
    text = read_text_crlf(template_path("CROPCOM.DAT"))
    lines = text.splitlines()
    crops = []
    for line in lines[2:]:
        tokens = line.split()
        if len(tokens) < 3:
            continue
        try:
            code = int(tokens[0])
        except ValueError:
            continue
        name = tokens[1]
        desc_tokens = []
        for tok in reversed(tokens):
            try:
                float(tok)
                break
            except ValueError:
                desc_tokens.insert(0, tok)
        desc = " ".join(desc_tokens)
        crops.append((code, name, desc, line))
    return crops


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--name")
    ap.add_argument("--code", type=int)
    args = ap.parse_args()

    crops = load_crops()

    if args.list:
        print(f"{'code':>4}  {'name':<6}  description")
        print("-" * 50)
        for code, name, desc, _ in crops:
            print(f"{code:>4}  {name:<6}  {desc}")
        print(f"\nTotal: {len(crops)} crops")
        return

    if args.name:
        hits = [c for c in crops if c[1].upper() == args.name.upper()]
    elif args.code is not None:
        hits = [c for c in crops if c[0] == args.code]
    else:
        ap.error("provide --list, --name, or --code")

    if not hits:
        print("No crop found for query", file=sys.stderr)
        sys.exit(1)
    for code, name, desc, _ in hits:
        print(f"code={code} name={name}  {desc}")


if __name__ == "__main__":
    main()
