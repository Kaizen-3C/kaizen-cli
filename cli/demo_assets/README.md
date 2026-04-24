# cli/demo_assets — Bundled demo assets for `kaizen demo`

This directory ships inside the `kaizen-cli` PyPI wheel and is located by
`cli/commands/demo.py` via `importlib.resources`.

## What this directory contains

| File | Status | Description |
|------|--------|-------------|
| `__init__.py` | committed | Makes this a Python package so `importlib.resources` can find it |
| `slugify_demo.tar.gz` | **generated** | Pre-recorded kaizen run on `python-slugify` (not yet present) |

## Generating `slugify_demo.tar.gz`

Run (once a real API key is available):

```bash
python scripts/build-demo-cache.py
```

The script clones `https://github.com/un33k/python-slugify` (shallow), runs
`kaizen decompose` and `kaizen recompose` against the Anthropic API, then
bundles the outputs into the tarball.

**Pytest harness note:** both the `before/` and `after/` pytest steps are
invoked with `cwd=<repo_dir>` (the cloned source root for `before/`, the
recomposed output root for `after/`). pytest automatically prepends `cwd` to
`sys.path`, so the target package is importable without mutating the current
venv. No `pip install` of the target package is required.

## Expected tarball structure

```
slugify_demo/
  adr.md              # the produced ADR (shown in Step 1)
  transcript.md       # LLM transcript (optional — shown if present)
  summary.json        # {"files": [...], "elapsed_s": N, "pass_count": M, "pass_count_before": X}
  before/             # original python-slugify source (for reference)
  after/              # post-recompose state — pytest runs against this
```

### `summary.json` schema

```json
{
  "files":              ["slugify/__init__.py", ...],
  "elapsed_s":          42,
  "pass_count":         [N],
  "pass_count_before":  [M]
}
```

The schema keys (`files`, `elapsed_s`, `pass_count`, `pass_count_before`) are
identical across demo targets — only the file names and counts differ.

## Why python-slugify?

- Small and self-contained (~1 module, ~200 LOC)
- Clear public API: `slugify()` and `smart_truncate()` — easy to capture in an ADR
- 50+ deterministic tests covering pure string operations
- No C extensions — pure Python, installs everywhere
- MIT license

## Regenerating after a model change

Re-run `python scripts/build-demo-cache.py` and commit the updated tarball.
The tarball is committed to the repo (binary blob) so end-users never need
an API key to run `kaizen demo`.
