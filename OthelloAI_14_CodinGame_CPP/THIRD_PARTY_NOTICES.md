# Third-party notices

The search and bitboard implementation is derived in part from:

- Egaroucid 7.8.2
- Copyright (C) Takuto Yamana (Nyanyan)
- Upstream commit: `112981e381801a38604f54714d46eb9d90322b80`
- License: GPL-3.0-or-later

The learned width-16 evaluator and Java/CodinGame integration were developed in
the course project. The C++ port keeps the evaluator's parameter order,
quantization, phase mapping, and search semantics for controlled comparison.

The small DEFLATE decoder in the generated width-48 candidate is an original,
purpose-limited implementation of the public RFC 1950/RFC 1951 formats. It does
not copy zlib/miniz source code and performs strict length and distance checks.
