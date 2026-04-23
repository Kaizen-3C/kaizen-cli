# cli/demo_assets — Bundled demo assets for `kaizen demo`

This directory ships inside the `kaizen-cli` PyPI wheel and is located by
`cli/commands/demo.py` via `importlib.resources`.

## What this directory contains

| File | Status | Description |
|------|--------|-------------|
| `__init__.py` | committed | Makes this a Python package so `importlib.resources` can find it |
| `wcwidth_demo.tar.gz` | **generated** | Pre-recorded kaizen run on `wcwidth` (not yet present) |

## Generating `wcwidth_demo.tar.gz`

Run (once a real API key is available):

```bash
python scripts/build-demo-cache.py
```

> **TODO**: `scripts/build-demo-cache.py` is a forthcoming script. When
> written it should perform a real `kaizen decompose` + `kaizen recompose`
> run on the `wcwidth` source, capture the outputs, and produce the tarball
> below.

## Expected tarball structure

```
wcwidth_demo/
  adr.md              # the produced ADR (shown in Step 1)
  transcript.md       # LLM transcript (optional — shown if present)
  summary.json        # {"files": [...], "elapsed_s": N, "pass_count": M}
  before/             # original wcwidth source (for reference)
  after/              # post-recompose state — pytest runs against this
```

### `summary.json` schema

```json
{
  "files":       ["wcwidth.py", "table_wide.py", ...],
  "elapsed_s":   42,
  "pass_count":  28
}
```

## Why wcwidth?

- Small and self-contained (~6 files, ~28 tests)
- Has a real test suite so pytest gives meaningful signal
- No C extensions — pure Python, installs everywhere
- Familiar to developers (used by prompt-toolkit, rich, etc.)

## Regenerating after a model change

Re-run `python scripts/build-demo-cache.py` and commit the updated tarball.
The tarball is committed to the repo (binary blob) so end-users never need
an API key to run `kaizen demo`.
