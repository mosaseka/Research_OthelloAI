#!/usr/bin/env python3
"""Create a test-time-configurable copy of the untouched baseline source.

Only class naming, time/thread/seed configuration hooks are changed.  The
generated source lives under build/ and is never a submission source file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


REPLACEMENTS = (
    (
        "public class OthelloAI_03 {",
        "public class OthelloAI_Baseline {",
    ),
    (
        "static final long move_time_limit_ms = 9_500L;",
        "static final long move_time_limit_ms = Long.parseLong("
        "System.getProperty(\"othello.moveTimeMs\", "
        "System.getenv().getOrDefault(\"OTHELLO_MOVE_TIME_MS\", \"9500\")));",
    ),
    (
        "static final int NUM_THREADS = Runtime.getRuntime().availableProcessors();",
        "static final int NUM_THREADS = Integer.parseInt("
        "System.getProperty(\"othello.threads\", "
        "System.getenv().getOrDefault(\"OTHELLO_THREADS\", "
        "Integer.toString(Runtime.getRuntime().availableProcessors()))));",
    ),
    (
        "static final Random raw_myrandom = new Random(System.currentTimeMillis());",
        "static final Random raw_myrandom = new Random(Long.parseLong("
        "System.getProperty(\"othello.seed\", "
        "System.getenv().getOrDefault(\"OTHELLO_SEED\", "
        "Long.toString(System.currentTimeMillis())))));",
    ),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "original_03" / "OthelloAI_03.java",
        help="untouched baseline Java source",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("build/instrumented-baseline"),
    )
    parser.add_argument("--javac", default="javac")
    parser.add_argument("--no-compile", action="store_true")
    args = parser.parse_args()

    source = args.source.resolve()
    if not source.is_file():
        parser.error(f"baseline source not found: {source}")
    text = source.read_text(encoding="utf-8")
    applied: list[str] = []
    for old, new in REPLACEMENTS:
        count = text.count(old)
        if count != 1:
            raise RuntimeError(f"expected one baseline marker, found {count}: {old}")
        text = text.replace(old, new)
        applied.append(old)

    output_dir = args.output_dir.resolve()
    source_dir = output_dir / "src"
    classes_dir = output_dir / "classes"
    source_dir.mkdir(parents=True, exist_ok=True)
    classes_dir.mkdir(parents=True, exist_ok=True)
    generated = source_dir / "OthelloAI_Baseline.java"
    generated.write_text(text, encoding="utf-8", newline="\n")

    if not args.no_compile:
        subprocess.run(
            [args.javac, "-encoding", "UTF-8", "-d", str(classes_dir), str(generated)],
            check=True,
        )

    manifest = {
        "source": str(source),
        "source_sha256": sha256(source),
        "generated": str(generated),
        "generated_sha256": sha256(generated),
        "class": "OthelloAI_Baseline",
        "classes_dir": str(classes_dir),
        "changes": [
            "public class renamed for side-by-side launch",
            "move time can be overridden for tests",
            "thread count can be overridden for tests",
            "book RNG seed can be overridden for reproducibility",
        ],
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as exc:
        print(f"javac failed with exit code {exc.returncode}", file=sys.stderr)
        sys.exit(exc.returncode)
