# Kaizen

**Architecture-driven modernization. Audit trail ships by default.** Decompose legacy codebases into editable Architectural Decision Records (ADRs), recompose to modern stacks — compliance is what good architecture produces, not a feature you bolt on.

> The ADR is the product. Every architectural decision is cited to `file:line` in the source, reviewable as markdown, signable for compliance. The code generation is downstream of the contract — a human reviewer can accept, edit, or reject decisions *before* any modern code is written.

## Install

```bash
# Recommended: isolated install, no virtualenv needed
pipx install kaizen-3c-cli

# uv (faster resolver)
uv tool install kaizen-3c-cli

# pip
pip install kaizen-3c-cli
```

Also available without Python:

```bash
winget install Kaizen3C.KaizenCLI          # Windows
npm install -g kaizen-cli                  # any platform with Node
brew tap Kaizen-3C/tap && brew install kaizen-cli  # macOS / Linux
```

Requires Python 3.10+ (pipx/uv/pip installs only). You will also need:

- `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` in your environment (or a local `.env` file).
- Rust toolchain (`cargo`) if using `--recompose` for C/C++ → Rust memory-safety work.
- .NET SDK (`dotnet`) if using `--recompose` for framework-migration work targeting .NET 8.

## Quick start

### Memory safety roadmap (C/C++ → Rust)

For CISA memory-safety roadmap compliance. Produces a CISA-format roadmap markdown + per-module ADR stubs.

```bash
kaizen memsafe-roadmap ./my-c-lib \
  --output roadmap.md \
  --adr-dir ./adrs \
  --glob "*" \
  --provider openai

# Plain mode (no --domain schema — sufficient for most cases):
kaizen memsafe-roadmap ./my-c-lib --plain -o roadmap.md

# With Rust code generation:
kaizen memsafe-roadmap ./my-c-lib --recompose --rust-output ./rust-port
```

### Framework migration plan (.NET Framework → .NET 8, AngularJS → Angular, etc.)

```bash
kaizen migrate-plan ./legacy-csharp-project \
  --from dotnet-framework --to dotnet8 \
  --output migration-plan.md \
  --provider openai
```

Supported transitions: `angularjs->angular`, `angularjs->react`, `jquery->react`, `dotnet-framework->dotnet8`, `dotnet-framework->dotnet9`, `python2->python3`, `spring4->spring-boot3`, `java8->java17`, `java8->java21`.

### Dry-run first

```bash
kaizen memsafe-roadmap ./my-c-lib --dry-run
kaizen migrate-plan ./project --from angularjs --to angular --dry-run
```

Prints the planned pipeline steps without calling any LLM. Use it to check paths, glob patterns, and provider settings before spending tokens.

## Why this instead of one-shot AI coding tools?

Measured on 2 case studies at `temperature=0`:

| Case study | One-shot LLM (compiles?) | Kaizen plain ADR (compiles?) |
|---|---|---|
| `inih` C → Rust (522 LOC) | ❌ 6 `cargo check` errors | ✅ 1 error (minor gap) |
| Nancy `NancyContext.cs` .NET Fx → .NET 8 (148 LOC) | ❌ 14 `dotnet build` errors | ✅ 0 errors |

The ADR-as-contract closes ~83–100% of the "will it compile?" gap that one-shot LLMs leave open. The `--domain memory-safe` / `--domain framework-migration` schema flags add enterprise-tier plan-document richness (CISA-format roadmap, API-contract tables, dependency upgrade paths) on top.

The one-shot baseline control is shipped with the CLI — run `oneshot_baseline.py` on the same source to measure the delta on your own code.

## Positioning vs. alternatives

- **vs. LegacyLeap** (full-lifecycle enterprise modernization platform) — we ship only the ADR + recompose pieces; cloud-agnostic; developer-led distribution.
- **vs. Amazon Q Developer Transform** (Java 8 → 17 auto-upgrade) — we're LLM-agnostic (Anthropic or OpenAI), cloud-agnostic (runs on a laptop or air-gapped), cover broader language pairs, and expose the ADR as editable intermediate.
- **vs. Google Jules / OpenHands / SWE-agent** (generic AI coding agents) — we're synchronous + deterministic (`temperature=0` default); auditable ADR artifact; different trust model for architecture-driven workflows where compliance is the goal architecture serves.

## The ADR-as-contract claim, measured

Three-arm ablation ([case study](https://github.com/aaronadame/Kaizen-delta/blob/main/docs/case-studies/memsafe-01-inih/README.md)):

- **One-shot LLM** (no pipeline): 6 errors on `cargo check`.
- **Kaizen plain ADR** (no domain schema): 1 error. +5 errors closed by the ADR alone.
- **Kaizen + `--domain memory-safe`**: 0 errors. +1 additional error closed by the domain schema.

The plain ADR pipeline captures ~83% of the measurable value. The domain schemas are enterprise polish. Commercially, this is an open-core model: free plain ADR, paid domain schemas + audit-log + air-gapped deployment.

## License

Apache-2.0. See `LICENSE`.

## Contributing / Issues

https://github.com/Kaizen-3C/kaizen-cli

## Status

**1.0.0 — Alpha.** CLI subcommands `memsafe-roadmap`, `migrate-plan`, `run`, `priors`, `status` are end-to-end. PyPI package bundles the pipeline scripts via sdist for now; Phase C will move them under `cli/pipeline/` as a proper subpackage.

Case studies:

- [inih C → Rust](https://github.com/aaronadame/Kaizen-delta/blob/main/docs/case-studies/memsafe-01-inih/README.md) (Phase A, three-arm)
- [Nancy `NancyContext.cs` .NET Fx → .NET 8](https://github.com/aaronadame/Kaizen-delta/blob/main/docs/case-studies/framework-01-nancy-context/README.md) (Phase B, three-arm)
- [adr-tools bash → Python](https://github.com/aaronadame/Kaizen-delta/blob/main/docs/case-studies/01-adr-tools/README.md) (prior-session cross-language reference)

See [docs/markets/](https://github.com/aaronadame/Kaizen-delta/tree/main/docs/markets) for the product wedge docs (memory safety + framework modernization) and [ARCHITECTURE_VALUE_MATRIX.md](https://github.com/aaronadame/Kaizen-delta/blob/main/docs/demos/ARCHITECTURE_VALUE_MATRIX.md) for the honest value claims backed by data.
