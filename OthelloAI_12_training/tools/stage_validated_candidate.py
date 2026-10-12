#!/usr/bin/env python3
"""Stage an eligible original_11 value candidate without adopting it.

The default prints a plan only.  ``--commit`` creates a new numbered candidate
directory using exclusive-create semantics.  A staged candidate still requires
the prescribed arena A/B tests before root resources may be changed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sys
from typing import Any, Sequence
import uuid


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PARAMETER_COUNT = 25_436
VARIANT = re.compile(r"value_11(?:a(?:_fresh)?|b)")


def resolve(raw: str | Path) -> Path:
    path = Path(raw).expanduser()
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def check_parameter(path: Path) -> tuple[str, int]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) != EXPECTED_PARAMETER_COUNT:
        raise ValueError(
            f"candidate requires {EXPECTED_PARAMETER_COUNT} lines, got {len(lines)}"
        )
    for line_number, raw in enumerate(lines, 1):
        try:
            value = float(raw)
        except ValueError as error:
            raise ValueError(f"invalid parameter at line {line_number}") from error
        if not math.isfinite(value):
            raise ValueError(f"non-finite parameter at line {line_number}")
    return sha256(path), len(lines)


def next_target(root: Path, variant: str) -> Path:
    for number in range(1, 10_000):
        candidate = root / f"{variant}_candidate_{number:03d}"
        if not candidate.exists():
            return candidate
    raise RuntimeError("no free candidate number below 10000")


def plan(
    candidate: Path,
    report_path: Path,
    variant: str,
    target_root: Path,
) -> dict[str, Any]:
    if VARIANT.fullmatch(variant) is None:
        raise ValueError("--variant must be value_11a, value_11a_fresh, or value_11b")
    if not (
        target_root.name == "candidates"
        and target_root.parent.name == "resources"
        and target_root.parent.parent.name == "original_11"
        and (target_root.parent.parent / "OthelloAI_11.java").is_file()
    ):
        raise ValueError(
            "target-root must explicitly name an existing original_11 runtime's "
            "resources/candidates directory"
        )
    candidate_sha, count = check_parameter(candidate)
    report = load_object(report_path)
    decision = report.get("decision")
    if not isinstance(decision, dict) or not bool(decision.get("pass")):
        raise ValueError("validation report decision.pass is not true")
    if not bool(decision.get("eligible_for_ab")):
        raise ValueError("candidate is not eligible_for_ab")
    if report.get("candidate_feature_schema") != "exact-mobility-v1":
        raise ValueError("validation report candidate_feature_schema is not exact-mobility-v1")
    if report.get("baseline_feature_schema") != "exact-mobility-v1":
        raise ValueError("validation report baseline_feature_schema is not exact-mobility-v1")
    report_candidate = report.get("candidate")
    if not isinstance(report_candidate, dict):
        raise ValueError("validation report has no candidate section")
    if str(report_candidate.get("sha256", "")).lower() != candidate_sha:
        raise ValueError("validation report candidate SHA-256 differs")
    if int(report_candidate.get("count", -1)) != count:
        raise ValueError("validation report candidate count differs")
    report_baseline = report.get("baseline")
    expected_baseline_sha = str(
        report.get("config", {}).get("expected_baseline_sha256", "")
    ).lower()
    if (
        not isinstance(report_baseline, dict)
        or not bool(report_baseline.get("pass"))
        or not bool(report_baseline.get("hash_matches"))
        or str(report_baseline.get("sha256", "")).lower() != expected_baseline_sha
    ):
        raise ValueError("validation report does not bind the pinned baseline SHA-256")
    report_variant = report.get("config", {}).get("experiment", {}).get("variant")
    accepted_report_variants = {variant}
    if variant == "value_11a_fresh":
        accepted_report_variants.add("value_11a")
    if report_variant not in accepted_report_variants:
        raise ValueError(
            f"validation report variant {report_variant!r} does not match {variant!r}"
        )
    target = next_target(target_root, variant)
    return {
        "schema": "original_11_candidate_stage_plan_v1",
        "commit": False,
        "adopted": False,
        "candidate": str(candidate),
        "candidate_sha256": candidate_sha,
        "parameter_count": count,
        "validation_report": str(report_path),
        "validation_report_sha256": sha256(report_path),
        "variant": variant,
        "target": str(target),
        "files": ["value_param.txt", "model.properties", "provenance.json"],
        "next_required_step": "arena A/B; do not copy to root resources yet",
    }


def commit(plan_value: dict[str, Any]) -> None:
    target = Path(plan_value["target"])
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(f"candidate target already exists: {target}")
    temporary = target.parent / f".{target.name}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir(parents=False, exist_ok=False)
    try:
        value_out = temporary / "value_param.txt"
        shutil.copyfile(plan_value["candidate"], value_out)
        if sha256(value_out) != plan_value["candidate_sha256"]:
            raise RuntimeError("copied value parameter SHA-256 mismatch")
        properties = (
            "format=othello-model-bundle-v1\n"
            "feature.schema=exact-mobility-v1\n"
            "value.file=value_param.txt\n"
            f"value.sha256={plan_value['candidate_sha256'].upper()}\n"
        )
        properties_path = temporary / "model.properties"
        properties_path.write_text(properties, encoding="ascii", newline="\n")
        provenance = {
            **plan_value,
            "commit": True,
            "atomic_stage": True,
            "staged_files_sha256": {
                "value_param.txt": sha256(value_out),
                "model.properties": sha256(properties_path),
            },
        }
        provenance_path = temporary / "provenance.json"
        with provenance_path.open("x", encoding="utf-8", newline="\n") as output:
            json.dump(provenance, output, ensure_ascii=False, indent=2)
            output.write("\n")
        if sha256(value_out) != plan_value["candidate_sha256"]:
            raise RuntimeError("staged value parameter changed before commit")
        temporary.rename(target)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--validation-report", type=Path, required=True)
    parser.add_argument("--variant", required=True)
    parser.add_argument(
        "--target-root", type=Path, required=True,
        help="explicit .../original_11/resources/candidates path",
    )
    parser.add_argument("--commit", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        value = plan(
            resolve(args.candidate),
            resolve(args.validation_report),
            str(args.variant),
            resolve(args.target_root),
        )
        value["commit"] = bool(args.commit)
        print(json.dumps(value, ensure_ascii=False, indent=2))
        if args.commit:
            commit(value)
        return 0
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
