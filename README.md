# kaizen-cli

[![PyPI version](https://img.shields.io/pypi/v/kaizen-3c-cli.svg)](https://pypi.org/project/kaizen-3c-cli/)
[![Python versions](https://img.shields.io/pypi/pyversions/kaizen-3c-cli.svg)](https://pypi.org/project/kaizen-3c-cli/)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

**Architecture-first AI for software modernization. Planning leads, code follows — every decision cited to `file:line`, reviewable as an ADR before a line of target code is written.**

```bash
pip install "kaizen-3c-cli[demo]"
kaizen demo
```

`[demo]` is recommended for the full experience — it pulls in `pytest` so Step 3 runs live against the recomposed code; the bare `pip install kaizen-3c-cli` still works but prints the pre-recorded test output instead.

`kaizen demo` replays a pre-recorded decompose/recompose against [`python-slugify`](https://github.com/un33k/python-slugify), then runs `pytest` live against the recomposed code. No API key required, no network calls, no credits spent. Takes under a minute end-to-end.

---

## What it does

Three wedge commands cover the modernization workflows kaizen-cli was built for. Each emits an Architectural Decision Record (ADR) you can read, edit, or reject before any target code is generated.

- **`kaizen memsafe-roadmap <repo>`** — CISA-format memory-safety port plan with per-module ADR stubs. Optional `--recompose` step emits a Rust scaffold grounded in the ADR.

  ```bash
  kaizen memsafe-roadmap ./my-c-lib --recompose --rust-output ./rust-port
  ```

- **`kaizen migrate-plan <repo> --from <X> --to <Y>`** — framework-migration plan across supported transitions (`python3.6 -> python3.12`, `dotnet-framework -> dotnet8`, `angularjs -> angular`, `java8 -> java21`, and others).

  ```bash
  kaizen migrate-plan ./legacy-project --from "Python 3.6" --to "Python 3.12"
  ```

- **`kaizen bench`** — analyse commit0 benchmark results from [`Kaizen-3C/benchmarks`](https://github.com/Kaizen-3C/benchmarks). `fingerprint` computes per-cell value-add scores; `compare` diffs two architectures side-by-side. Full-sweep reproduction lives in the benchmarks repo itself — `kaizen bench commit0` prints exact steps and requirements.

  ```bash
  kaizen bench fingerprint --results ./commit0-results/
  ```

The full v1.0 command set: `decompose`, `recompose`, `memsafe-roadmap`, `migrate-plan`, `status`, `priors`, `resume`, `init`, `web`, `mcp-serve`, `bench`, `demo`, `version`.

---

## Demo — `kaizen demo`

Pre-recorded on `python-slugify`, runs offline, no API key required.

```
$ kaizen demo

  Library:   python-slugify (string-to-slug converter, 1 module, 50+ tests)
  LLM work:  pre-recorded — no API key required, no network calls.
  pytest:    runs LIVE against the recomposed code — output is real.
             (if the `[demo]` extras are installed; otherwise the pre-recorded run is printed)

Step 1/3: Decomposing python-slugify...
  ADR-python-slugify-decomposed   6 identifiers, 15 decisions, 8 consequences
  (preview of first 30 lines of the ADR, full at adr.md)

Step 2/3: Recomposing 6 files based on the ADR...
  Elapsed (original run): 97s
  Tests passed (cached):  33
  Files recomposed:       slugify/__init__.py, slugify/slugify.py, slugify/__main__.py

Step 3/3: Running pytest against recomposed code...
  ================ 1 failed, 33 passed in 0.21s ================
```

Honest results on the cached run: `python-slugify`'s own test suite shows **82 passing** on the original source; the recomposed package's own emitted test suite shows **33 passing, 1 failing** (a real behavioral divergence — `test_lowercase_false` reveals the recompose strips wrong characters when `lowercase=False`). The failure is not curated away — it's exactly the kind of first-pass gap the architecture-first workflow is built to surface before you ship.

---

## Why another AI CLI?

Honest feature comparison against adjacent tools. None of these are "better than" verdicts — they describe what each tool does and doesn't do in its current form. Sourced from the `docs/CLI_ROADMAP.md` gap analysis.

| Axis | kaizen-cli | OpenHands-CLI | Aider | Cursor |
|---|:-:|:-:|:-:|:-:|
| ADR-first workflow (plan before code) | yes | no (interactive agent loop) | no (edit-in-place) | no (in-editor completion) |
| Offline replay / `demo` without an API key | yes | no | no | no |
| Rust port output (C/C++ memory-safety wedge) | yes | partial (generic code-gen) | partial | partial |
| Benchmarks reproduction subcommand | yes (`kaizen bench`) | no | no | no |
| Governance / audit artifact (ADR + evidence) | yes (core) + signed ADR (commercial) | no | no | no |
| Interactive TUI | deferred (post-1.0) | yes | yes | n/a (IDE) |
| MCP server (expose the tool to Claude Desktop / Cursor / Zed) | yes (`kaizen mcp-serve`) | partial (client only) | no | host |

Kaizen is **batch and measurable** — give it a repo, get an ADR you can diff, sign, or hand to a reviewer. OpenHands is **interactive and agentic** — chat with the agent, approve actions as it works. Different trust models, different product shapes.

---

## Upstream: the benchmarks

The methodology, raw data, and analysis scripts live upstream at **[Kaizen-3C/benchmarks](https://github.com/Kaizen-3C/benchmarks)**: an 8-architecture × 16-library matrix on the commit0 lite split, roughly 80 per-library result JSONs, plus two named architectural ceilings (marshmallow attribute-access, jinja relative-import). `kaizen bench` vendors the analysis scripts (`fingerprint`, `compare`) so the CLI works standalone on any results directory. Full-sweep reproduction runs from the benchmarks repo directly — it owns the environment conventions, Docker containers, and runner scripts. `kaizen bench commit0` inside the CLI prints the exact commands.

---

## 3C lineage

Kaizen-3C reframes the original Kaizen 3C method — **Concern · Cause · Countermeasure**, born on Toyota factory floors — for the software industry as **Code · Compose · Compliance**. The discipline is the same: observe the system before changing it, understand the cause before applying a fix, document the countermeasure so it survives audit. Architecture-first AI is the technical claim; 3C is the methodological lineage. Depth at [kaizen-3c.dev](https://kaizen-3c.dev).

---

For deployment with governance (signed ADRs, audit-log export, multi-tenant): hello@kaizen-3c.dev.

---

## Contributing, License, Security

- Contributions: see [`CONTRIBUTING.md`](CONTRIBUTING.md). DCO sign-off required.
- License: Apache-2.0. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
- Security disclosures: see [`SECURITY.md`](SECURITY.md) or email security@kaizen-3c.dev.
