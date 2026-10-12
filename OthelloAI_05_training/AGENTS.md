# Othello AI development rules

- Preserve the production protocol: print only `READY` and `y x [value]` to stdout. Send diagnostics to stderr.
- Keep the no-argument production limit at about 9.5 seconds. Test overrides must use system properties or environment variables.
- Do not overwrite `resources/param.txt` or replace the baseline implicitly. Write candidates under `artifacts/` and compare them with paired games.
- Do not modify the sibling baseline directory. `tools/prepare_instrumented_baseline.py` may create a generated copy under `build/` for short-time tests.
- Do not commit or redistribute Egaroucid raw data or large processed samples. Commit only scripts, configuration, provenance, hashes, and learned parameters whose distribution is permitted.
- Treat resources/Egaroucid_Train_Data_v0002_0 and _1 as non-redistributable raw input. Keep generated shards and receipts under ignored data/processed/.
- Keep v0002 transcript replay/conversion in `converter/egaroucid_v2_converter.cpp`; Python consumes only completed schema-v2 shards/manifests. Preserve byte compatibility with existing Python-generated receipts when changing the converter.
- Make one strength-related change at a time. Record the source hash, seed, commands, time setting, opening positions, W/D/L, disc difference, depth, NPS, and faults.
- Before accepting a change, compile with `-Xlint:all`, run `OthelloAIRegressionTest`, and run paired A/B games with colors exchanged.
- Board encoding is black=`0`, white=`1`, empty=`.`, with zero-based output coordinates `y x`.
- Keep Java production dependencies to the standard library.
