#!/usr/bin/env python3
"""Build the final_48 single-file CodinGame Java submission deterministically.

The 142,812-parameter evaluator is quantized tensor-by-tensor to signed 11-bit,
DEFLATE-compressed, and packed as 15-bit BMP symbols.  Tensor-local scales
preserve substantially more precision than one global scale while the
compressed payload remains below CodinGame's 100,000 UTF-16-unit source cap.
"""

from __future__ import annotations

import argparse
import hashlib
import math
from pathlib import Path
import struct
import sys
import zlib


PARAMETER_COUNT = 142_812
PHASE_COUNT = 4
PATTERN_SIZES = (8, 8, 8, 5, 6, 7, 8, 10, 10, 10, 10)
PATTERN_HIDDEN = 48
ADD_HIDDEN = 8
QUANTIZED_MAX = 1_023
SYMBOL_BITS = 15
SYMBOL_MASK = (1 << SYMBOL_BITS) - 1
SYMBOL_BASE = 0x3400
SYMBOL_LIMIT = 0xB3FF
MAX_LITERAL_CHARS = 8_000
CODINGAME_CODE_LIMIT = 100_000

MODEL_DATA_MARKER = "/*__MODEL_DATA__*/"
MODEL_COMPRESSED_BYTES_MARKER = "/*__MODEL_COMPRESSED_BYTES__*/"
MODEL_RAW_BYTES_MARKER = "/*__MODEL_RAW_BYTES__*/"
MODEL_CRC32_MARKER = "/*__MODEL_CRC32__*/"
MODEL_SHA256_MARKER = "/*__MODEL_SHA256__*/"
MARKERS = (
    MODEL_DATA_MARKER,
    MODEL_COMPRESSED_BYTES_MARKER,
    MODEL_RAW_BYTES_MARKER,
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


def tensor_lengths() -> list[int]:
    """Return parameter tensor lengths in the exact Java/Python export order."""

    result: list[int] = []
    for _phase in range(PHASE_COUNT):
        for pattern_size in PATTERN_SIZES:
            result.extend(
                (
                    pattern_size * 2 * PATTERN_HIDDEN,
                    PATTERN_HIDDEN,
                    PATTERN_HIDDEN * PATTERN_HIDDEN,
                    PATTERN_HIDDEN,
                    PATTERN_HIDDEN,
                    1,
                )
            )
        result.extend(
            (
                3 * ADD_HIDDEN,
                ADD_HIDDEN,
                ADD_HIDDEN * ADD_HIDDEN,
                ADD_HIDDEN,
                19,
                1,
            )
        )
    if len(result) != 288 or sum(result) != PARAMETER_COUNT:
        raise AssertionError("invalid final_48 tensor layout")
    return result


def quantize_parameters(
    values: list[float],
) -> tuple[list[float], list[int], float, float]:
    if len(values) != PARAMETER_COUNT:
        raise BuildError(
            f"internal parameter count mismatch: {len(values)} != {PARAMETER_COUNT}"
        )

    scales: list[float] = []
    quantized: list[int] = []
    squared_error = 0.0
    maximum_error = 0.0
    offset = 0
    for length in tensor_lengths():
        tensor_values = values[offset : offset + length]
        offset += length
        maximum = max(abs(value) for value in tensor_values)
        scale = maximum / QUANTIZED_MAX if maximum != 0.0 else 1.0
        # Java decodes the emitted binary32 value, so compute diagnostics and
        # integer values against that exact scale rather than Python binary64.
        scale = struct.unpack("<f", struct.pack("<f", scale))[0]
        scales.append(scale)
        for value in tensor_values:
            # Python round is deterministic round-to-nearest, ties-to-even.
            integer = round(value / scale)
            integer = max(-QUANTIZED_MAX, min(QUANTIZED_MAX, integer))
            quantized.append(integer)
            error = value - integer * scale
            squared_error += error * error
            maximum_error = max(maximum_error, abs(error))

    if len(quantized) != PARAMETER_COUNT:
        raise AssertionError("quantizer produced the wrong parameter count")
    rmse = math.sqrt(squared_error / PARAMETER_COUNT)
    return scales, quantized, rmse, maximum_error


def build_raw_payload(scales: list[float], values: list[int]) -> bytes:
    if len(values) != PARAMETER_COUNT:
        raise BuildError(
            f"quantized parameter count must be {PARAMETER_COUNT}, got {len(values)}"
        )
    if len(scales) != len(tensor_lengths()):
        raise BuildError(
            f"scale count must be {len(tensor_lengths())}, got {len(scales)}"
        )
    try:
        scale_bytes = struct.pack(f"<{len(scales)}f", *scales)
        value_bytes = struct.pack(f"<{len(values)}h", *values)
        return scale_bytes + value_bytes
    except struct.error as error:
        raise BuildError(f"cannot encode quantized model payload: {error}") from error


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
    compressed_bytes: int,
    raw_bytes: int,
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

    result = replace_marker_once(template, MODEL_DATA_MARKER, data_replacement)
    result = replace_marker_once(
        result, MODEL_COMPRESSED_BYTES_MARKER, str(compressed_bytes)
    )
    result = replace_marker_once(result, MODEL_RAW_BYTES_MARKER, str(raw_bytes))
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

    progress.step("quantizing 288 evaluator tensors to symmetric signed 11-bit")
    scales, quantized, quantization_rmse, quantization_max_error = (
        quantize_parameters(values)
    )
    raw = build_raw_payload(scales, quantized)
    compressed = zlib.compress(raw, level=9)

    progress.step("checksumming, DEFLATE-compressing, and packing the model")
    crc32 = zlib.crc32(raw) & 0xFFFFFFFF
    sha256 = hashlib.sha256(parameter_path.read_bytes()).hexdigest().upper()
    packed = pack_15bit_little_endian(compressed)
    if unpack_15bit_little_endian(packed, len(compressed)) != compressed:
        raise BuildError("15-bit model pack round-trip failed")
    try:
        if zlib.decompress(compressed) != raw:
            raise BuildError("DEFLATE model round-trip failed")
    except zlib.error as error:
        raise BuildError(f"cannot verify DEFLATE payload: {error}") from error
    chunks = split_literals(packed)

    progress.step("injecting model literals into the Java template")
    try:
        template = template_path.read_bytes().decode("utf-8-sig")
    except (OSError, UnicodeError) as error:
        raise BuildError(f"cannot read UTF-8 template {template_path}: {error}") from error
    source = render_submission(
        template, chunks, len(compressed), len(raw), crc32, sha256
    )
    # Rendering is intentionally pure and must be byte-for-byte reproducible.
    if source != render_submission(
        template, chunks, len(compressed), len(raw), crc32, sha256
    ):
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
        "tensors": len(scales),
        "scales": scales,
        "crc32": f"{crc32:08X}",
        "sha256": sha256,
        "raw_bytes": len(raw),
        "compressed_bytes": len(compressed),
        "compression_ratio": len(compressed) / len(raw),
        "quantization_rmse": quantization_rmse,
        "quantization_max_error": quantization_max_error,
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
    parser.add_argument("--param", type=Path, required=True, help="142,812-line value_param.txt")
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
    print(f"Tensor scales: {report['tensors']}")
    print(
        "Quantization error: "
        f"RMSE {report['quantization_rmse']:.9g}, "
        f"max {report['quantization_max_error']:.9g}"
    )
    print(f"Raw/DEFLATE bytes: {report['raw_bytes']:,}/{report['compressed_bytes']:,} "
          f"({report['compression_ratio']:.1%})")
    print(f"Quantized payload CRC32: {report['crc32']}")
    print(f"Source parameter SHA-256: {report['sha256']}")
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
