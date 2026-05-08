# Kaizen

**Architecture-driven modernization. Audit trail ships by default.** Decompose legacy codebases into editable ADRs, recompose to modern stacks — compliance falls out of doing the architecture right, not bolted on after.

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE.md)
[![License: Commercial](https://img.shields.io/badge/Enterprise-Kaizen_Commercial-orange.svg)](LICENSE-COMMERCIAL.md)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
![Status](https://img.shields.io/badge/status-public%20beta-blue)

## Install

| Method | Command |
|---|---|
| **winget** (Windows) | `winget install Kaizen3C.KaizenCLI` |
| **npm** | `npm install -g kaizen-cli` |
| **Homebrew** (macOS/Linux) | `brew tap Kaizen-3C/tap && brew install kaizen-cli` |
| **pipx** (Python, recommended) | `pipx install kaizen-3c-cli` |
| **uv** | `uv tool install kaizen-3c-cli` |
| **pip** | `pip install kaizen-3c-cli` |

winget, npm, and Homebrew install a standalone binary (no Python required). pipx/uv/pip install the full package including `[web]` and `[mcp]` extras.

```bash
export ANTHROPIC_API_KEY=...     # or OPENAI_API_KEY, or a local Ollama host
kaizen memsafe-roadmap ./my-c-lib --output roadmap.md
```

## Does it work? — measured outcomes

| Case study | One-shot LLM | Kaizen (plain ADR) | Kaizen (+ domain schema) |
|---|:-:|:-:|:-:|
| [inih](docs/case-studies/memsafe-01-inih/README.md) — C → Rust, 522 LOC (`cargo check`) | 6 errors | 1 error | **0 errors** |
| [Nancy](docs/case-studies/framework-01-nancy-context/README.md) — `NancyContext.cs` .NET Fx → .NET 8, 148 LOC (`dotnet build`) | 14 errors | **0 errors** | 0 errors |

Methodology: three-arm ablation (one-shot control, plain ADR pipeline, ADR + domain schema) on real OSS repos. Exact commands, prompts, and raw outputs in each case-study directory.

## What it isn't

Kaizen is **not** a code-generation tool. The ADR is the product; the LLM is the tool that produces it. An ADR is an editable, auditable record of an architectural decision — the thing a compliance officer signs off on, the thing a reviewer pushes back on, the thing that survives when the model changes next quarter. Recompose is the CI check that the ADR actually predicts working code.

## The two wedges

- **`kaizen memsafe-roadmap <repo>`** — C/C++ → Rust. Produces a CISA-format memory-safety roadmap + per-module ADR stubs. Optionally recomposes to a Rust port.
- **`kaizen migrate-plan --from X --to Y <repo>`** — framework modernization (9 pairs: AngularJS → Angular/React, jQuery → React, .NET Framework → .NET 8/9, Python 2 → 3, Java 8 → 17/21, Spring 4 → Spring Boot 3).

Full CLI reference: [cli/README.md](cli/README.md).

## License

Kaizen is **dual-licensed**:

- **Apache-2.0** for the CLI, pipeline, and provider adapters — `cli/`, `cli/pipeline/`, `agents/src/providers/`. Free forever. Installable via `pip install kaizen-3c-cli`.
- **Kaizen Enterprise Commercial** for the enterprise wrapper — multi-tenancy, RBAC, SSO, MFA, audit-log export, approval workflows, cost attribution UI, budget caps. Lives under `interface/` and is priced in [docs/commercial/PRICING.md](docs/commercial/PRICING.md).

The open-core boundary is explicit and enumerated in [ADR-0053](.architecture/decisions/ADR-0053-dual-license-apache2-commercial.md). No pipeline capability is paywalled — the commercial tier wraps infrastructure, not pipeline. Validated in [docs/CLI_VS_UI_CAPABILITY_REVIEW.md](docs/CLI_VS_UI_CAPABILITY_REVIEW.md).

## Documentation

- [Quickstart](quickstart.md)
- [CLI guide](docs/CLI_GUIDE.md) — task-focused walkthrough of every command + the lite web UI
- [CLI reference](cli/README.md) — full flag reference
- [Case studies](docs/case-studies/) — reproducible measurements

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md). All Apache-2.0 inbound; Commercial-tier work happens in the private dev repo, not via public PRs. Code of Conduct: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Security

To report a vulnerability, follow [SECURITY.md](SECURITY.md). Do not open a public issue for security-related findings.

---

## For contributors — internals

### Architecture

Kaizen uses a four-tier architecture with a multi-agent denoising convergence loop. The CLI + pipeline (top-left in the diagram) is the Apache-2.0 surface; the ASP.NET + React UI is the Commercial wrapper.

```
┌─────────────────────────────────────────────────────┐
│  React / TypeScript UI  (interface/ui/)             │  ← Commercial
│  Vite, Zustand, TanStack Query, Monaco, Recharts    │
└────────────────────┬────────────────────────────────┘
                     │ REST / HTTP
┌────────────────────▼────────────────────────────────┐
│  C# / ASP.NET Core 9 API  (interface/)              │  ← Commercial
│  PostgreSQL, Redis, JWT + MFA                       │
└────────────────────┬────────────────────────────────┘
                     │ gRPC (deferred — see ADR-0061)
┌────────────────────▼────────────────────────────────┐
│  Rust Orchestrator  (core/)                         │  ← Apache (deferred modules)
│  Concurrent decomposition engine, convergence gate  │
└────────────────────┬────────────────────────────────┘
                     │ in-process / gRPC
┌────────────────────▼────────────────────────────────┐
│  Python Agent Services  (cli/, agents/)             │  ← Apache — the shipped product
│  Researcher, Red Team, Draft, Write, Evaluator      │
│  LLM provider abstraction (Anthropic, OpenAI,       │
│  Ollama, LiteLLM)                                   │
└─────────────────────────────────────────────────────┘
```

The five agents (Researcher, Red Team, Draft, Write, Evaluator) iterate over the decomposition output. Each round produces grounded confidence scores (test pass rate, static analysis, coverage); the orchestrator gates completion via a Thompson-sampling convergence decision (see ADR-0052).

### Developer setup

See [quickstart.md](quickstart.md) for environment prerequisites, Docker Compose setup for the full stack, and first-run instructions. For CLI-only development, `pip install -e .` at the repo root is enough.

### Release process

The public `kaizen` repo is curated from this `kaizen-delta` dev repo via an allowlist-driven export script. Maintainer runbook: [docs/release/RELEASE_PROCESS.md](docs/release/RELEASE_PROCESS.md). The authoritative allowlist: [docs/release/PUBLIC_REPO_ALLOWLIST.md](docs/release/PUBLIC_REPO_ALLOWLIST.md).
