#!/usr/bin/env python3
"""Build the single-file CodinGame Java submission deterministically.

The learned value evaluator contains 25,436 floating-point parameters.  This
tool quantizes each of the four 6,359-parameter phases with one symmetric
int16 scale, checksums the little-endian short stream, and packs that stream
as 15-bit symbols in a safe BMP range.  The generated Java source therefore
needs no model file at runtime.
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
SYMBOL_LIMIT = 0xB3FF
MAX_LITERAL_CHARS = 8_000
CODINGAME_CODE_LIMIT = 100_000

MODEL_DATA_MARKER = "/*__MODEL_DATA__*/"
MODEL_SCALES_MARKER = "/*__MODEL_SCALES__*/"
MODEL_CRC32_MARKER = "/*__MODEL_CRC32__*/"
MODEL_SHA256_MARKER = "/*__MODEL_SHA256__*/"
MARKERS = (
    MODEL_DATA_MARKER,
    MODEL_SCALES_MARKER,
    MODEL_CRC32_MARKER,
    MODEL_SHA256_MARKER,
)


class BuildError(ValueError):
    """A deterministic, user-correctable submission build failure."""


class Progress:
    """Small CUI progress indicator for the six deterministic build stages."""

    def __init__(self, total: int = 6, width: int = 24) -> None:
        self.total = total
        self.width = width
        self.current = 0

    def step(self, message: str) -> None:
        self.current += 1
        filled = self.width * self.current // self.total
        bar = "#" * filled + "." * (self.width - filled)
        print(
            f"[build {self.current}/{self.total}] |{bar}| {message}",
            file=sys.stderr,
            flush=True,
        )


def read_parameters(path: Path) -> list[float]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as error:
        raise BuildError(f"cannot read parameter file {path}: {error}") from error

    lines = text.splitlines()
    if len(lines) != PARAMETER_COUNT:
        raise BuildError(
            f"parameter count must be {PARAMETER_COUNT:,}, got {len(lines):,}"
        )

    values: list[float] = []
    for line_number, raw in enumerate(lines, 1):
        if not raw.strip():
            raise BuildError(f"blank parameter at line {line_number}")
        try:
            value = float(raw)
        except ValueError as error:
            raise BuildError(
                f"invalid parameter at line {line_number}: {raw!r}"
            ) from error
        if not math.isfinite(value):
            raise BuildError(f"non-finite parameter at line {line_number}")
        values.append(value)
    return values


def quantize_parameters(values: list[float]) -> tuple[list[float], list[int]]:
    if len(values) != PARAMETER_COUNT:
        raise BuildError(
            f"internal parameter count mismatch: {len(values)} != {PARAMETER_COUNT}"
        )

    scales: list[float] = []
    quantized: list[int] = []
    for phase in range(PHASE_COUNT):
        start = phase * PARAMETERS_PER_PHASE
        phase_values = values[start : start + PARAMETERS_PER_PHASE]
        maximum = max(abs(value) for value in phase_values)
        scale = maximum / QUANTIZED_MAX if maximum != 0.0 else 1.0
        scales.append(scale)
        for value in phase_values:
            # Python round is deterministic round-to-nearest, ties-to-even.
            integer = round(value / scale)
            integer = max(-QUANTIZED_MAX, min(QUANTIZED_MAX, integer))
            quantized.append(integer)

    if len(quantized) != PARAMETER_COUNT:
        raise AssertionError("quantizer produced the wrong parameter count")
    return scales, quantized


def little_endian_shorts(values: list[int]) -> bytes:
    if len(values) != PARAMETER_COUNT:
        raise BuildError(
            f"quantized parameter count must be {PARAMETER_COUNT}, got {len(values)}"
        )
    try:
        return struct.pack(f"<{len(values)}h", *values)
    except struct.error as error:
        raise BuildError(f"quantized parameter is outside int16: {error}") from error


def pack_15bit_little_endian(raw: bytes) -> str:
    """Pack a byte stream low-bit-first into U+3400..U+B3FF symbols."""

    symbols: list[str] = []
    accumulator = 0
    bit_count = 0
    for byte in raw:
        accumulator |= byte << bit_count
        bit_count += 8
        while bit_count >= SYMBOL_BITS:
            symbol = accumulator & SYMBOL_MASK
            symbols.append(chr(SYMBOL_BASE + symbol))
            accumulator >>= SYMBOL_BITS
            bit_count -= SYMBOL_BITS
    if bit_count:
        symbols.append(chr(SYMBOL_BASE + (accumulator & SYMBOL_MASK)))

    packed = "".join(symbols)
    if any(not SYMBOL_BASE <= ord(char) <= SYMBOL_LIMIT for char in packed):
        raise AssertionError("packed model contains an out-of-range symbol")
    return packed


def unpack_15bit_little_endian(packed: str, byte_count: int) -> bytes:
    """Reference decoder used to verify every generated model bit-for-bit."""

    output = bytearray()
    accumulator = 0
    bit_count = 0
    for char in packed:
        symbol = ord(char) - SYMBOL_BASE
        if not 0 <= symbol <= SYMBOL_MASK:
            raise BuildError(f"packed symbol outside the model alphabet: U+{ord(char):04X}")
        accumulator |= symbol << bit_count
        bit_count += SYMBOL_BITS
        while bit_count >= 8 and len(output) < byte_count:
            output.append(accumulator & 0xFF)
            accumulator >>= 8
            bit_count -= 8

    if len(output) != byte_count:
        raise BuildError(
            f"packed model decoded to {len(output)} bytes, expected {byte_count}"
        )
    # The final symbol is zero-padded above the exact payload bit length.
    if accumulator != 0:
        raise BuildError("packed model has non-zero trailing padding bits")
    return bytes(output)


def split_literals(packed: str) -> list[str]:
    chunks = [
        packed[offset : offset + MAX_LITERAL_CHARS]
        for offset in range(0, len(packed), MAX_LITERAL_CHARS)
    ]
    if not chunks or any(len(chunk) > MAX_LITERAL_CHARS for chunk in chunks):
        raise AssertionError("invalid Java literal split")
    return chunks


def java_double(value: float) -> str:
    # Hexadecimal floating literals preserve the exact Python binary64 scale.
    literal = value.hex()
    if literal in {"inf", "-inf", "nan"}:
        raise BuildError(f"cannot emit non-finite Java double: {value!r}")
    return literal


def marker_indent(template: str, marker: str) -> str:
    position = template.index(marker)
    line_start = template.rfind("\n", 0, position) + 1
    prefix = template[line_start:position]
    return prefix if not prefix.strip() else ""


def replace_marker_once(source: str, marker: str, replacement: str) -> str:
    count = source.count(marker)
    if count != 1:
        raise BuildError(f"template must contain {marker} exactly once, found {count}")
    return source.replace(marker, replacement, 1)


def render_submission(
    template: str,
    chunks: list[str],
    scales: list[float],
    crc32: int,
    sha256: str,
) -> str:
    for marker in MARKERS:
        if template.count(marker) != 1:
            raise BuildError(
                f"template must contain {marker} exactly once, "
                f"found {template.count(marker)}"
            )

    indent = marker_indent(template, MODEL_DATA_MARKER)
    data_replacement = (",\n" + indent).join(f'"{chunk}"' for chunk in chunks)
    scales_replacement = ", ".join(java_double(value) for value in scales)

    result = replace_marker_once(template, MODEL_DATA_MARKER, data_replacement)
    result = replace_marker_once(result, MODEL_SCALES_MARKER, scales_replacement)
    result = replace_marker_once(result, MODEL_CRC32_MARKER, f"0x{crc32:08X}L")
    result = replace_marker_once(result, MODEL_SHA256_MARKER, f'"{sha256}"')
    if "__MODEL_" in result:
        raise BuildError("generated source still contains an unresolved model placeholder")
    return result


def source_sizes(source: str) -> tuple[int, int]:
    utf16_units = len(source.encode("utf-16-le")) // 2
    utf8_bytes = len(source.encode("utf-8"))
    return utf16_units, utf8_bytes


def build(template_path: Path, parameter_path: Path, output_path: Path) -> dict[str, object]:
    if output_path.resolve() == template_path.resolve():
        raise BuildError("--output must not overwrite the Java template")
    if output_path.resolve() == parameter_path.resolve():
        raise BuildError("--output must not overwrite the parameter file")

    progress = Progress()
    progress.step(f"reading {PARAMETER_COUNT:,} parameters")
    values = read_parameters(parameter_path)

    progress.step("quantizing four evaluator phases to symmetric int16")
    scales, quantized = quantize_parameters(values)
    raw = little_endian_shorts(quantized)

    progress.step("checksumming and packing the little-endian model")
    crc32 = zlib.crc32(raw) & 0xFFFFFFFF
    sha256 = hashlib.sha256(raw).hexdigest().upper()
    packed = pack_15bit_little_endian(raw)
    if unpack_15bit_little_endian(packed, len(raw)) != raw:
        raise BuildError("15-bit model pack round-trip failed")
    chunks = split_literals(packed)

    progress.step("injecting model literals into the Java template")
    try:
        template = template_path.read_bytes().decode("utf-8-sig")
    except (OSError, UnicodeError) as error:
        raise BuildError(f"cannot read UTF-8 template {template_path}: {error}") from error
    source = render_submission(template, chunks, scales, crc32, sha256)
    # Rendering is intentionally pure and must be byte-for-byte reproducible.
    if source != render_submission(template, chunks, scales, crc32, sha256):
        raise AssertionError("submission rendering is not deterministic")

    progress.step("checking CodinGame source-size limits")
    utf16_units, utf8_bytes = source_sizes(source)
    if utf16_units > CODINGAME_CODE_LIMIT:
        raise BuildError(
            f"generated source has {utf16_units:,} UTF-16 code units; "
            f"CodinGame limit is {CODINGAME_CODE_LIMIT:,}"
        )

    progress.step(f"writing {output_path}")
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(source.encode("utf-8"))
    except OSError as error:
        raise BuildError(f"cannot write output {output_path}: {error}") from error

    return {
        "parameters": len(values),
        "scales": scales,
        "crc32": f"{crc32:08X}",
        "sha256": sha256,
        "packed_chars": len(packed),
        "literal_chunks": len(chunks),
        "largest_literal": max(map(len, chunks)),
        "utf16_units": utf16_units,
        "utf8_bytes": utf8_bytes,
        "output_bytes": output_path.stat().st_size,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, required=True, help="PlayerTemplate.java")
    parser.add_argument("--param", type=Path, required=True, help="25,436-line param.txt")
    parser.add_argument("--output", type=Path, required=True, help="generated Player.java")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = build(args.template, args.param, args.output)
    except (BuildError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    print(f"Generated: {args.output.resolve()}")
    print(f"Parameters: {report['parameters']:,}")
    print("Phase scales: " + ", ".join(f"{value:.17g}" for value in report["scales"]))
    print(f"Quantized CRC32 (LE): {report['crc32']}")
    print(f"Quantized SHA-256 (LE): {report['sha256']}")
    print(
        f"Packed model: {report['packed_chars']:,} UTF-16 chars, "
        f"{report['literal_chunks']} literals, largest {report['largest_literal']:,} chars"
    )
    print(
        f"Java source: {report['utf16_units']:,}/{CODINGAME_CODE_LIMIT:,} UTF-16 units, "
        f"{report['utf8_bytes']:,} UTF-8 bytes"
    )
    if report["utf8_bytes"] > CODINGAME_CODE_LIMIT:
        print(
            "Note: UTF-8 bytes exceed 100,000; CodinGame's stated source limit "
            "is checked above in UTF-16 code units."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
