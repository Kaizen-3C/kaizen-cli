# kaizen-3c-cli

**Architecture-first AI for software modernization. Planning leads, code follows — every decision cited to `file:line`, reviewable as an ADR before a line of target code is written.**

## Install

```bash
pip install "kaizen-3c-cli[demo]"
```

`[demo]` is recommended for the full demo experience — it pulls in `pytest` so `kaizen demo`'s Step 3 runs live; the bare `pip install kaizen-3c-cli` still works but prints the pre-recorded test output instead.

Requires Python 3.10+.

## Try it

```bash
kaizen demo
```

Replays a pre-recorded decompose/recompose against [`python-slugify`](https://github.com/un33k/python-slugify), then runs pytest live against the recomposed code. No API key required, under a minute end-to-end. On the cached run: 82 tests passing on the original, 33 of 34 passing on the recomposed (one real behavioral divergence captured, not hidden).

## What it does

- **`kaizen memsafe-roadmap <repo>`** — CISA-format memory-safety port plan with per-module ADR stubs. Optional `--recompose` step emits a Rust scaffold grounded in the ADR.

  ```bash
  kaizen memsafe-roadmap ./my-c-lib --recompose --rust-output ./rust-port
  ```

- **`kaizen migrate-plan <repo> --from <X> --to <Y>`** — framework-migration plan across supported transitions (`python3.6 -> python3.12`, `dotnet-framework -> dotnet8`, `angularjs -> angular`, `java8 -> java21`, and others).

  ```bash
  kaizen migrate-plan ./legacy-project --from "Python 3.6" --to "Python 3.12"
  ```

- **`kaizen bench fingerprint --results <dir>`** — compute per-cell value-add scores on any commit0 results directory. Also: `kaizen bench compare` for head-to-head architecture diffs, and `kaizen bench commit0` for upstream-reproduction instructions.

The full v1.0 command set: `decompose`, `recompose`, `memsafe-roadmap`, `migrate-plan`, `status`, `priors`, `resume`, `init`, `web`, `mcp-serve`, `bench`, `demo`, `version`.

## Demo flow

Pre-recorded on `python-slugify`, runs offline, no API key required.

```
$ kaizen demo
Step 1/3: Decomposing python-slugify...
  ADR-python-slugify-decomposed   6 identifiers, 15 decisions, 8 consequences
Step 2/3: Recomposing 6 files based on the ADR...
  Files: slugify/__init__.py, slugify/slugify.py, slugify/__main__.py
Step 3/3: Running pytest against recomposed code...
  ================ 1 failed, 33 passed in 0.21s ================
```

Baseline (original `python-slugify`): 82 passing. Recomposed: 33 of 34 passing — the 1 failure is a real behavioral divergence surfaced by the workflow, not curated away.

## Links

- GitHub (source, issues, full README): https://github.com/Kaizen-3C/kaizen-cli
- Upstream benchmarks: https://github.com/Kaizen-3C/benchmarks
- Project homepage: https://kaizen-3c.dev
- Commercial tier (signed ADRs, audit-log export, multi-tenant): hello@kaizen-3c.dev
- Security disclosures: security@kaizen-3c.dev

## License

Apache-2.0.
