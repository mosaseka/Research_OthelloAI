#!/usr/bin/env python3
"""Check the C++ bitboard move generator against standard initial perft counts."""

from __future__ import annotations

import argparse
import subprocess


EXPECTED = {1: 4, 2: 12, 3: 56, 4: 244, 5: 1396, 6: 8200, 7: 55092, 8: 390216}
ROWS = ["........", "........", "........", "...10...", "...01...", "........", "........", "........"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--player", required=True)
    parser.add_argument("--max-depth", type=int, default=8)
    args = parser.parse_args()
    depths = [d for d in EXPECTED if d <= args.max_depth]
    payload = "".join(f"0 {d}\n" + "\n".join(ROWS) + "\n" for d in depths)
    result = subprocess.run(
        [args.player, "--perft"], input=payload, text=True,
        capture_output=True, encoding="utf-8", timeout=30, check=True,
    )
    actual = [int(line) for line in result.stdout.splitlines()]
    wanted = [EXPECTED[d] for d in depths]
    if actual != wanted:
        raise SystemExit(f"FAIL actual={actual} expected={wanted}")
    print("PASS " + ", ".join(f"d{d}={EXPECTED[d]}" for d in depths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
