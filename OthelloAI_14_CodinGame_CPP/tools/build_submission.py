#!/usr/bin/env python3
"""Generate deterministic single-file C++17 CodinGame submissions.

The width-16 model uses exactly the same phase-local symmetric int16
quantization and 15-bit BMP packing as the established Java submission.
"""

from __future__ import annotations

import argparse
import hashlib
import math
from pathlib import Path
import struct
import sys
import zlib


PARAMETER_COUNT = 25_436
PHASE_COUNT = 4
PARAMETERS_PER_PHASE = 6_359
QUANTIZED_MAX = 32_767
SYMBOL_BITS = 15
SYMBOL_MASK = (1 << SYMBOL_BITS) - 1
SYMBOL_BASE = 0x3400
MAX_LITERAL_CHARS = 8_000
CODINGAME_CODE_LIMIT = 100_000
MARKERS = (
    "/*__MODEL_DATA__*/",
    "/*__MODEL_SCALES__*/",
    "/*__MODEL_CRC32__*/",
    "/*__MODEL_SHA256__*/",
    "/*__VARIANT_DEFINE__*/",
    "/*__MOVE_BUDGET_MS__*/",
    "/*__HIDDEN__*/",
    "/*__PARAMETER_COUNT__*/",
)
VARIANTS = {
    "cpp16_baseline": (
        '#define OTHELLO_LAZY_MODEL 1\n'
        '#define OTHELLO_VARIANT_NAME "cpp16_baseline"'
    ),
    "cpp16_optimized": (
        '#define OTHELLO_OPTIMIZED 1\n'
        '#define OTHELLO_VARIANT_NAME "cpp16_optimized"'
    ),
    "cpp_egaroucid_enhanced": (
        '#define OTHELLO_OPTIMIZED 1\n'
        '#define OTHELLO_ENHANCED 1\n'
        '#define OTHELLO_VARIANT_NAME "cpp_egaroucid_enhanced"'
    ),
}


class BuildError(ValueError):
    pass


def read_parameters(path: Path) -> list[float]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as error:
        raise BuildError(f"cannot read {path}: {error}") from error
    if len(lines) != PARAMETER_COUNT:
        raise BuildError(
            f"expected {PARAMETER_COUNT:,} parameters, got {len(lines):,}"
        )
    values: list[float] = []
    for line_no, raw in enumerate(lines, 1):
        try:
            value = float(raw)
        except ValueError as error:
            raise BuildError(f"invalid parameter on line {line_no}") from error
        if not math.isfinite(value):
            raise BuildError(f"non-finite parameter on line {line_no}")
        values.append(value)
    return values


def quantize(values: list[float]) -> tuple[list[float], list[int]]:
    scales: list[float] = []
    result: list[int] = []
    for phase in range(PHASE_COUNT):
        start = phase * PARAMETERS_PER_PHASE
        phase_values = values[start : start + PARAMETERS_PER_PHASE]
        maximum = max(abs(v) for v in phase_values)
        scale = maximum / QUANTIZED_MAX if maximum else 1.0
        scales.append(scale)
        for value in phase_values:
            q = round(value / scale)
            result.append(max(-QUANTIZED_MAX, min(QUANTIZED_MAX, q)))
    return scales, result


def pack_15bit(raw: bytes) -> str:
    out: list[str] = []
    acc = 0
    bits = 0
    for byte in raw:
        acc |= byte << bits
        bits += 8
        while bits >= SYMBOL_BITS:
            out.append(chr(SYMBOL_BASE + (acc & SYMBOL_MASK)))
            acc >>= SYMBOL_BITS
            bits -= SYMBOL_BITS
    if bits:
        out.append(chr(SYMBOL_BASE + (acc & SYMBOL_MASK)))
    return "".join(out)


def unpack_15bit(packed: str, byte_count: int) -> bytes:
    out = bytearray()
    acc = 0
    bits = 0
    for char in packed:
        q = ord(char) - SYMBOL_BASE
        if not 0 <= q <= SYMBOL_MASK:
            raise BuildError(f"packed character outside alphabet: U+{ord(char):04X}")
        acc |= q << bits
        bits += SYMBOL_BITS
        while bits >= 8 and len(out) < byte_count:
            out.append(acc & 255)
            acc >>= 8
            bits -= 8
    if len(out) != byte_count or acc:
        raise BuildError("15-bit round trip failed")
    return bytes(out)


def replace_once(source: str, marker: str, replacement: str) -> str:
    if source.count(marker) != 1:
        raise BuildError(f"template must contain {marker} exactly once")
    return source.replace(marker, replacement, 1)


def build(
    template_path: Path,
    parameter_path: Path,
    output_path: Path,
    variant: str,
    budget_ms: int,
) -> dict[str, object]:
    if variant not in VARIANTS:
        raise BuildError(f"unknown variant: {variant}")
    if not 1 <= budget_ms <= 140:
        raise BuildError("budget must stay in 1..140 ms; 115 ms is the safe baseline")
    values = read_parameters(parameter_path)
    scales, quantized = quantize(values)
    raw = struct.pack(f"<{len(quantized)}h", *quantized)
    packed = pack_15bit(raw)
    if unpack_15bit(packed, len(raw)) != raw:
        raise BuildError("packed model round trip mismatch")
    chunks = [packed[i : i + MAX_LITERAL_CHARS] for i in range(0, len(packed), MAX_LITERAL_CHARS)]
    template = template_path.read_text(encoding="utf-8-sig")
    for marker in MARKERS:
        if template.count(marker) != 1:
            raise BuildError(f"unresolved or duplicate marker: {marker}")
    source = template
    source = replace_once(
        source,
        "/*__MODEL_DATA__*/",
        ",\n".join(f'u"{chunk}"' for chunk in chunks),
    )
    source = replace_once(
        source,
        "/*__MODEL_SCALES__*/",
        ", ".join(value.hex() for value in scales),
    )
    crc = zlib.crc32(raw) & 0xFFFFFFFF
    sha = hashlib.sha256(raw).hexdigest().upper()
    source = replace_once(source, "/*__MODEL_CRC32__*/", f"0x{crc:08X}U")
    source = replace_once(source, "/*__MODEL_SHA256__*/", f'"{sha}"')
    source = replace_once(source, "/*__VARIANT_DEFINE__*/", VARIANTS[variant])
    source = replace_once(source, "/*__MOVE_BUDGET_MS__*/", str(budget_ms))
    source = replace_once(source, "/*__HIDDEN__*/", "16")
    source = replace_once(source, "/*__PARAMETER_COUNT__*/", str(PARAMETER_COUNT))
    utf16_units = len(source.encode("utf-16-le")) // 2
    if utf16_units > CODINGAME_CODE_LIMIT:
        raise BuildError(
            f"source has {utf16_units:,} UTF-16 units; limit is {CODINGAME_CODE_LIMIT:,}"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(source, encoding="utf-8", newline="\n")
    return {
        "variant": variant,
        "budget_ms": budget_ms,
        "parameters": len(values),
        "crc32": f"{crc:08X}",
        "sha256": sha,
        "packed_chars": len(packed),
        "utf16_units": utf16_units,
        "utf8_bytes": len(source.encode("utf-8")),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, default=Path("template/PlayerTemplate.cpp"))
    parser.add_argument("--param", type=Path, default=Path("model/width16_param.txt"))
    parser.add_argument("--output", type=Path, default=Path("Player.cpp"))
    parser.add_argument("--variant", choices=sorted(VARIANTS), default="cpp16_baseline")
    parser.add_argument("--budget-ms", type=int, default=115)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = build(args.template, args.param, args.output, args.variant, args.budget_ms)
    except (BuildError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(f"Generated: {args.output.resolve()}")
    for key, value in report.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
