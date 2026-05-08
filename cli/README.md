# kaizen-3c-cli

Command-line interface for **Kaizen** — architecture-driven modernization;
audit trail ships by default. The CLI runs the two end-to-end wedges (memory
safety and framework migration) on top of the symmetric decompose / recompose
pipeline, plus the pre-reframe bootstrap orchestrator for generic ADR-driven
runs. Compliance is what good architecture produces, not a feature bolted on.

Apache-2.0. The UI (multi-tenant, RBAC, audit log, approval workflows) is a
separate Kaizen Enterprise Commercial surface — see
[`docs/commercial/FEATURE_MATRIX.md`](../docs/commercial/FEATURE_MATRIX.md)
for the open-core boundary.

## Install

```
pip install kaizen-3c-cli        # or: pipx install kaizen-3c-cli
uv tool install kaizen-3c-cli
winget install Kaizen3C.KaizenCLI
npm install -g kaizen-3c-cli
brew tap Kaizen-3C/tap && brew install kaizen-cli
```

Or from a local checkout: `pip install -e .`

Requires Python 3.10+ (pip/pipx/uv only). winget, npm, and Homebrew install a
standalone binary — no Python required. An LLM provider key is required for
the wedge commands (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) or a reachable
Ollama host for local runs.

## Quickstart — the two wedges

### `kaizen memsafe-roadmap` — C/C++ → Rust

Produces a CISA-format memory-safety roadmap and per-module ADR stubs from a
C/C++ repository. Optionally runs recompose to emit a Rust port.

```
# Plain ADR pipeline (baseline for the 3-arm ablation)
kaizen memsafe-roadmap ./my-c-repo --plain -o roadmap.md

# Domain-enriched schema (memory-safe-specific ADR fields)
kaizen memsafe-roadmap ./my-c-repo -o roadmap.md --adr-dir adrs/

# Full pipeline: roadmap + Rust port
kaizen memsafe-roadmap ./my-c-repo --recompose --rust-output rust-port/
```

Case study: [memsafe-01-inih](../docs/case-studies/memsafe-01-inih/README.md)
— 522 LOC C → Rust. One-shot LLM: 6 `cargo check` errors. Plain ADR pipeline:
1 error. ADR + memory-safe domain schema: **0 errors**.

### `kaizen migrate-plan` — framework modernization

Produces a migration plan and ADR stubs for a framework transition. Supports
nine language/framework pairs:

| `--from`           | `--to`            | Languages     |
|--------------------|-------------------|---------------|
| `angularjs`        | `angular`         | JS → TS       |
| `angularjs`        | `react`           | JS → TS       |
| `jquery`           | `react`           | JS → TS       |
| `dotnet-framework` | `dotnet8`         | C#            |
| `dotnet-framework` | `dotnet9`         | C#            |
| `python2`          | `python3`         | Python        |
| `spring4`          | `spring-boot3`    | Java          |
| `java8`            | `java17`          | Java          |
| `java8`            | `java21`          | Java          |

```
# Plain ADR pipeline
kaizen migrate-plan --from dotnet-framework --to dotnet8 ./my-repo --plain

# Domain-enriched plan + target-code recompose
kaizen migrate-plan --from angularjs --to react ./my-repo \
    --recompose --target-output migrated/
```

Case study:
[framework-01-nancy-context](../docs/case-studies/framework-01-nancy-context/README.md)
— Nancy `NancyContext.cs` .NET Framework → .NET 8, 148 LOC. One-shot: 14
`dotnet build` errors; plain ADR: 0 errors; domain schema captures 15 API
contracts + 6 dependency decisions the plain pipeline misses.

### Shared wedge flags

- `--plain`                 omit domain-specific ADR schema fields (baseline arm)
- `--recompose`             run recompose after planning
- `--provider {anthropic,openai,ollama,litellm,mixed}`
- `--model MODEL`           override provider default
- `--adr-dir PATH`          where ADR stubs are written
- `--glob PATTERN`          source file filter
- `--dry-run`               print the resolved plan and exit
- `--format {human,json}`   output format

## Generic commands

### `kaizen run` — bootstrap orchestrator

Runs the 5-agent denoising loop against an ADR or free-text task. Two modes:

```
# ADR-driven
kaizen run --target-adr ADR-0008 --workspace ./myrepo --provider anthropic

# Free-text (wraps in a synthetic ADR-9999 on disk)
kaizen run --task "modernize auth module" --workspace ./myrepo
```

Key flags:

- `--workspace PATH`   workspace directory (default: `.`)
- `--adr-dir PATH`     ADR directory (default: `<workspace>/.architecture/decisions`)
- `--max-steps N`      maximum denoising steps (default: `5`)
- `--theta F`, `--epsilon F`   convergence thresholds
- `--adaptive-convergence` / `--no-adaptive-convergence`   Thompson-sampling gate (default: on)
- `--priors-file PATH` Thompson priors JSON (loaded at start, saved at end)
- `--provider {anthropic,openai,ollama,litellm,mixed}`
- `--api-key`, `--ollama-host`, `--reasoning-model`, `--litellm-base-url`
- `--dry-run`          print the resolved plan and exit without running
- `--format {human,json}`   output format (default: `human`)

### `kaizen status`

Scans for `taor_observations.jsonl` and `priors.json` and prints a summary
(most recent run, last confidence trajectory).

```
kaizen status
kaizen status --path ./benchmarks
```

### `kaizen priors`

```
kaizen priors show [PATH]     # pretty-print a priors file (default: ./priors.json)
kaizen priors reset [PATH]    # delete a priors file (--yes to skip confirm)
```

### `kaizen version`

Prints the CLI version.

## Global flags

- `--verbose`   print stack traces on error and enable extra logs
- `--no-color`  disable ANSI color output (also honors `NO_COLOR` env var)

## Exit codes

- `0`   success (for `run`, implies convergence)
- `1`   convergence failed / aborted / unhandled exception
- `2`   usage error (bad args, missing workspace, missing credentials)
- `130` interrupted (Ctrl-C); priors are persisted if enabled

## Output conventions

- Normal output → **stdout**
- Errors and warnings → **stderr**
- Color is emitted only when stdout is a TTY and `--no-color` / `NO_COLOR`
  are not set

## Further reading

- [CLI guide](../docs/CLI_GUIDE.md) — full task-focused walkthrough, workflows, web UI, troubleshooting
- [Case studies](../docs/case-studies/) — reproducible ablation measurements
- [Quickstart](../quickstart.md)
