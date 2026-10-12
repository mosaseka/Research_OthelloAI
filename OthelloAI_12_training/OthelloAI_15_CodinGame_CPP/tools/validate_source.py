#!/usr/bin/env python3
"""Validate generated CodinGame source size, placeholders, and license header."""

from __future__ import annotations

import argparse
from pathlib import Path


LIMIT=100_000


def main()->int:
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("sources",nargs="+",type=Path);args=parser.parse_args()
    failed=False
    for path in args.sources:
        text=path.read_text(encoding="utf-8-sig");units=len(text.encode("utf-16-le"))//2
        problems=[]
        if units>LIMIT:problems.append(f"{units:,}>{LIMIT:,} UTF-16 units")
        if "/*__MODEL_DATA__*/" in text or "/*__HIDDEN__*/" in text:problems.append("unresolved build placeholder")
        if "GPL-3.0-or-later" not in text or "Takuto Yamana" not in text:problems.append("license/provenance header missing")
        print(f"{'FAIL' if problems else 'PASS'} {path}: {units:,} UTF-16 units"+("; "+"; ".join(problems) if problems else ""))
        failed|=bool(problems)
    return int(failed)


if __name__=="__main__":raise SystemExit(main())
