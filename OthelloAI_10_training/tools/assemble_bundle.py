"""Create a non-overwriting original_10 runtime model bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PARAMETER_COUNT = 25_436
FEATURE_SCHEMA = "exact-mobility-v1"


def verify_parameter(path: Path) -> tuple[str, int]:
    values: list[float] = []
    with path.open("r", encoding="utf-8") as source:
        for line_number, raw in enumerate(source, 1):
            if not raw.strip():
                raise ValueError(f"{path}:{line_number}: blank parameter")
            try:
                value = float(raw)
            except ValueError as error:
                raise ValueError(f"{path}:{line_number}: invalid parameter") from error
            if not math.isfinite(value):
                raise ValueError(f"{path}:{line_number}: non-finite parameter")
            values.append(value)
    if len(values) != PARAMETER_COUNT:
        raise ValueError(
            f"{path}: expected {PARAMETER_COUNT} parameters, got {len(values)}"
        )
    digest = hashlib.sha256(path.read_bytes()).hexdigest().upper()
    return digest, len(values)


def next_directory(requested: Path) -> Path:
    if not requested.exists():
        return requested
    stem = requested.name
    digits = ""
    while stem and stem[-1].isdigit():
        digits = stem[-1] + digits
        stem = stem[:-1]
    if not digits:
        raise FileExistsError(f"bundle directory already exists: {requested}")
    number = int(digits)
    while True:
        number += 1
        candidate = requested.with_name(f"{stem}{number:0{len(digits)}d}")
        if not candidate.exists():
            return candidate


def assemble(value: Path, policy: Path, requested: Path) -> Path:
    value = value.resolve()
    policy = policy.resolve()
    value_sha, value_count = verify_parameter(value)
    policy_sha, policy_count = verify_parameter(policy)
    output = next_directory(requested.resolve())
    output.mkdir(parents=True, exist_ok=False)
    value_out = output / "param.txt"
    policy_out = output / "policy.txt"
    shutil.copyfile(value, value_out)
    shutil.copyfile(policy, policy_out)
    properties = (
        "format=othello-model-bundle-v1\n"
        f"feature.schema={FEATURE_SCHEMA}\n"
        "value.file=param.txt\n"
        f"value.sha256={value_sha}\n"
        "policy.file=policy.txt\n"
        f"policy.sha256={policy_sha}\n"
    )
    (output / "model.properties").write_text(properties, encoding="ascii", newline="\n")
    receipt = {
        "format": "othello-model-bundle-v1",
        "feature_schema": FEATURE_SCHEMA,
        "value": {
            "source": str(value),
            "file": "param.txt",
            "sha256": value_sha,
            "parameters": value_count,
        },
        "policy": {
            "source": str(policy),
            "file": "policy.txt",
            "sha256": policy_sha,
            "parameters": policy_count,
        },
    }
    (output / "bundle_manifest.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    # Verify the copied bytes, not only the sources.
    if verify_parameter(value_out)[0] != value_sha:
        raise RuntimeError("copied value parameter hash mismatch")
    if verify_parameter(policy_out)[0] != policy_sha:
        raise RuntimeError("copied policy parameter hash mismatch")
    print(json.dumps({"event": "bundle_created", "path": str(output), **receipt}))
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--value", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "bundles" / "model_candidate_001",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    assemble(args.value, args.policy, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
