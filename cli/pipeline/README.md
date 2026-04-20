# Symmetric Decompose / Recompose Pipeline

Direct-API pipeline for bidirectional translation between source code and
Architecture Decision Records (ADRs).

**Full context**: [`docs/demos/SYMMETRIC_PIPELINE_FINDINGS.md`](../../docs/demos/SYMMETRIC_PIPELINE_FINDINGS.md)

**Behavioral proof**: [`docs/demos/SYMMETRIC_PIPELINE_PARITY_TEST_RESULTS.md`](../../docs/demos/SYMMETRIC_PIPELINE_PARITY_TEST_RESULTS.md)

## Scripts

| Script | Direction | Purpose |
|---|---|---|
| `decompose_v2.py` | code → ADR | Sonnet 4.5 + strict JSON schema tool use. Every decision must cite evidence (file:line). |
| `recompose_v2.py` | ADR → code | Sonnet 4.5 + schema tool use. Verifies Key Identifier preservation at write time. Supports `--cross-language` for source-language ≠ target-language. |
| `roundtrip_diff.py` | analysis | AST-based similarity metric. Weighted composite: identifier Jaccard, symbol preservation, LOC ratio, file-count ratio. Python-specific. |
| `specialist_review.py` | analysis | Opus 4.5 Red Team. Auto-triggered when round-trip similarity < 0.65. Structured findings with severity. |

## Minimum-viable round-trip

```bash
# 1. code → ADR
python -m cli.pipeline.decompose_v2 \
  --input path/to/source_dir \
  --output path/to/DERIVED-ADR.md \
  --adr-id "ADR-XXXX-derived"

# 2. ADR → code
python -m cli.pipeline.recompose_v2 \
  --adr path/to/DERIVED-ADR.md \
  --output-dir path/to/reconstructed

# 3. similarity metric
python -m cli.pipeline.roundtrip_diff \
  --original path/to/source_dir \
  --reconstructed path/to/reconstructed \
  --label "roundtrip_XXXX" \
  --output path/to/report.json

# 4. Red Team review (only if similarity is low)
python -m cli.pipeline.specialist_review \
  --adr path/to/DERIVED-ADR.md \
  --source-dir path/to/source_dir \
  --roundtrip-report path/to/report.json \
  --output path/to/review.json
```

## Cross-language (proven: bash → Python)

```bash
python -m cli.pipeline.decompose_v2 \
  --input bash_source_dir --output ADR-xxx.md --adr-id ... \
  --glob "*" --source-language "Bash"

python -m cli.pipeline.recompose_v2 \
  --adr ADR-xxx.md --output-dir python_output \
  --target-language Python --cross-language
```

## Environment

- Requires `ANTHROPIC_API_KEY` in env or `.env` at repo root.
- Python 3.9+ with `anthropic` SDK ≥ 0.86.0.
- Models used: `claude-sonnet-4-5` (Decompose, Recompose), `claude-opus-4-5` (Specialist review).
- All API calls stream and retry on transient disconnects (proven necessary on larger payloads).

## What the pipeline replaces

Before: Kaizen orchestrator multi-step loop with 6-signal convergence gate. $0.38–0.84, 12–21 min, 41–67% symbol preservation, 3–12× LOC bloat.

After: Direct-API call with tool-use schema. $0.03–0.13, 15–85 seconds, 88–100% symbol preservation, 0.84–1.04× LOC ratio.

See the findings doc for the full before/after comparison.
