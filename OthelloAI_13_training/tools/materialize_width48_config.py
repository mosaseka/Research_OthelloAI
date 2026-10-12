"""Bind a width-48 initialization manifest to a training config template."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


EXPECTED_SCHEMA = "othello-width48-initialization-v2"
EXPECTED_COUNT = 142_812


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def replace(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, str):
        for source, target in replacements.items():
            value = value.replace(source, target)
        return value
    if isinstance(value, list):
        return [replace(item, replacements) for item in value]
    if isinstance(value, dict):
        return {
            key: replace(item, replacements)
            for key, item in value.items()
        }
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--initialization-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    template_path = args.template.expanduser().resolve()
    manifest_path = args.initialization_manifest.expanduser().resolve()
    output_path = args.output.expanduser().resolve()
    if output_path.exists() and not args.overwrite:
        raise FileExistsError(f"refusing to overwrite config: {output_path}")
    template = json.loads(template_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != EXPECTED_SCHEMA:
        raise ValueError("unexpected initialization manifest schema")
    if manifest.get("function_preserving") is not True:
        raise ValueError("initialization was not function preserving")
    if manifest.get("symmetry_broken") is not True:
        raise ValueError("initialization did not break replica symmetry")
    if int(manifest.get("parameter_count", -1)) != EXPECTED_COUNT:
        raise ValueError("initialization parameter count is not width-48")
    initial_path = Path(str(manifest["output"])).expanduser().resolve()
    expected_hash = str(manifest["output_sha256"]).lower()
    if not initial_path.is_file() or sha256(initial_path) != expected_hash:
        raise ValueError("initialization file/hash does not match manifest")

    config = replace(template, {
        "__WIDTH48_INITIAL_PATH__": initial_path.as_posix(),
        "__WIDTH48_INITIAL_SHA256__": expected_hash,
    })
    encoded = json.dumps(
        config, ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"
    if "__WIDTH48_" in encoded:
        raise ValueError("unresolved width-48 placeholder remains")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(encoded, encoding="utf-8")
    print(str(output_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
