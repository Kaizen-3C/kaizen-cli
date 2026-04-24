# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [1.0.0] - 2026-04-23

First public release on PyPI as `kaizen-3c-cli`, published from the public
repo `Kaizen-3C/kaizen-cli` (Apache-2.0). Prior versions shipped from the
private `kaizen-delta` monorepo under the package name `kaizen-cli`; the
`kaizen-cli` PyPI namespace was already held by an unrelated abandoned
project (Saurav Panda, last release 2024-09-30), so the public name pivots
to `kaizen-3c-cli`. The shell command stays `kaizen`.

### Changed

- **Package renamed** `kaizen-cli` → `kaizen-3c-cli` for PyPI publication.
  Shell command remains `kaizen`.
- **Repository URLs** in `pyproject.toml` point at `Kaizen-3C/kaizen-cli`
  (new public repo) and `https://kaizen-3c.dev` for the homepage.
- **Packaging self-contained under `cli/`:** the sibling top-level packages
  `kaizen_web/` and `kaizen_mcp/` were vendored into `cli/web_server/` and
  `cli/mcp_server/` respectively. All imports rewritten; `git mv` preserved
  history. `pyproject.toml [tool.setuptools.packages.find]` narrowed to
  `["cli*"]`. This enables clean `git subtree split --prefix=cli` extraction
  into the public repo.
- **`license-files`** in `pyproject.toml` now points at `LICENSE` (bare name,
  standard for Apache-2.0 projects) plus `NOTICE`.

### Removed

- **`cli/commands/run.py`** — unregistered dead code that still imported from
  the private `agents.src.*` tree. Never wired into `cli/main.py`, not
  reachable from any registered subcommand, safe delete. Removed to avoid
  shipping a module with private-monorepo import references in the public
  wheel.

### Deferred to v1.1

`kaizen bench reproduce` was scoped and prototyped during W2 but deferred
to v1.1. The benchmarks repository at https://github.com/Kaizen-3C/benchmarks
remains the canonical path for reproduction; `kaizen bench commit0` now
prints an informational pointer to it with exact steps and requirements.

### Added

- **`[demo]` extras** — `pip install "kaizen-3c-cli[demo]"` pulls in `pytest` so `kaizen demo`'s Step 3 runs live against the recomposed code. Without the extras, Step 3 prints the pre-recorded pytest output from the tarball — no ImportError, no confusion.
- Pre-recorded demo tarball at `cli/demo_assets/wcwidth_demo.tar.gz`: a
  real Python-to-Python recomposition of `wcwidth` (decompose + recompose
  with `--target-language Python`) so `kaizen demo` plays back a genuine
  before/after with pytest deltas, not a tautology.
- `LICENSE`, `NOTICE`, `CONTRIBUTING.md`, `SECURITY.md` scaffolding
  (authored as part of W2) — Apache-2.0, DCO-signed contributions,
  90-day security disclosure via `security@kaizen-3c.dev`.

## [0.4.0] - 2026-04-22

Second release. Adds config-dir + first-run wizard + resume + adversarial LLM
review + approval prompt and ships the
**MCP server** as the v0.5.0 headline — kaizen is now callable as a tool from
Claude Desktop, Cursor, Zed, and any other MCP-capable client. Python floor
bumped to 3.10+.

### Added

#### CLI subcommands

- `kaizen init` — first-run wizard. Interactive provider pick + env-var probe
  + writes `~/.kaizen/config.toml` (platform-appropriate dir via
  `platformdirs`). Flags: `--non-interactive` (CI), `--show` (print config
  without modifying).
- `kaizen resume [--last | <run_id>]` — re-run recompose against the most
  recent local ADR. Scans the working tree for `adr-root.md`, `roadmap.md`,
  `plan.md`, `adr-*.md`, `ADR-*.md`; skips standard noisy dirs. `--list`
  enumerates candidates. Passthrough flags for all recompose options.
- `kaizen mcp-serve` — MCP server (new `kaizen_mcp/` package). Exposes six
  tools: `decompose`, `recompose`, `memsafe_roadmap`, `migrate_plan`,
  `list_runs`, `read_adr`. Tool handlers call the same Python functions the
  CLI uses, so every surface stays in lockstep. Transport: stdio (default,
  for Claude Desktop) or SSE (`--transport sse --port 7866`). Requires
  `pip install 'kaizen-cli[mcp]'`.

#### CLI flags on existing pipeline commands

- `--llm-review` (on `decompose`, `recompose`, `memsafe-roadmap`,
  `migrate-plan`) — adversarial review of the produced ADR by a different
  model instance than the write agent (anti-vibe-coding guardrail per
  ADR-0009). Review findings appear in the `result` event and as a
  `<adr>.review.json` sidecar.
- `--review-model MODEL` — explicit override for the review-stage model
  (otherwise auto-selected via a "flip heuristic": sonnet-4-5 → sonnet-4-6,
  gpt-4o → gpt-4.1, etc.).
- `--approve` (on `memsafe-roadmap`, `migrate-plan`) — when combined with
  `--recompose`, pause after the ADR is produced and prompt before continuing.
- `--yolo` — explicit opt-out of the approval prompt; equivalent to the
  default behavior but usable in scripts for clarity.

#### Configuration

- New `cli/config.py` module with `load_config()` / `save_config()` /
  `apply_defaults(args)`. Applied at the top of every pipeline command.
  Precedence (highest wins): explicit CLI flag → env var → `config.toml` →
  argparse defaults. Config schema covers `[providers]`, `[providers.<name>]`,
  `[output]`, `[pipeline]`.

#### Internal

- New `cli/events.py` event kinds: `stage` with `name="llm_review"` and
  `name="approval"` flow through the existing SSE + NDJSON schema
  unchanged — web UI and CLI consumers see review findings and approval
  decisions as normal events.
- `cli/review.py` — thin wrapper over the existing `cli/pipeline/specialist_review.py`
  pipeline script; exposes `run_llm_review(adr_path, ...)` with auto-selected
  review model and event emission.
- `cli/approval.py` — `approval_prompt(message, yolo=False, default=False)`
  helper. Non-TTY environments fall back to `default` without prompting
  (so CI pipelines don't hang).

### Changed

- Python floor bumped from 3.9 to **3.10** (needed for the MCP SDK; also
  aligns with modern tooling). Classifiers updated.
- `anthropic` dep pinned to `>=0.87.0` (fixes GHSA-q5f5-3gjm-7mfm +
  GHSA-w828-4qhx-vxx3).
- New `[mcp]` optional extra for the MCP server.
- New `platformdirs>=4.0.0` runtime dep (used by `cli.config` for
  cross-platform config-dir resolution).

### Test coverage delta

Test count grew from 33 (v0.3.0) to **145** (v0.4.0):
- `cli/tests/test_config.py` — 22 tests
- `cli/tests/test_init.py` — 22 tests
- `cli/tests/test_resume.py` — 11 tests
- `cli/tests/test_review.py` — 21 tests
- `cli/tests/test_approval.py` — 17 tests
- `kaizen_mcp/tests/test_server.py` — 19 tests

Pre-existing suites (events, wedge routes, SSE) unchanged and still green.

### Still not shipped

- `kaizen run` — remains in dev repo only (requires `agents/src/` transitive
  closure; see v0.3.0 notes).
- Standalone binary, translated READMEs, interactive TUI — tracked in
  the internal CLI roadmap for later releases.

---

## [0.3.0] - 2026-04-21

First public release — `pip install kaizen-cli`. Apache-2.0 core, dual-licensed
with the Kaizen Enterprise Commercial License (see ADR-0053).

### Added

#### CLI (`kaizen-cli`)

- `kaizen memsafe-roadmap <repo>` — C/C++ → Rust. Produces a CISA-format memory
  safety roadmap and per-module ADR stubs. Supports `--plain`,
  `--domain memory-safe`, `--recompose`, `--dry-run`, `--provider` (anthropic /
  openai / ollama / litellm / mixed).
- `kaizen migrate-plan --from X --to Y <repo>` — framework modernization plan
  across 9 language/framework pairs (AngularJS → Angular/React, jQuery → React,
  .NET Framework → .NET 8/9, Python 2 → 3, Java 8 → 17/21, Spring 4 →
  Spring Boot 3). Same flag surface as `memsafe-roadmap`.
- `kaizen decompose <repo>` — direct pipeline access (Source → ADR). Wraps
  `cli.pipeline.decompose_v2` with all its flags (`--source-language`, `--glob`,
  `--domain`, `--temperature`, `--no-signatures`).
- `kaizen recompose <adr>` — direct pipeline access (ADR → target code).
  Wraps `cli.pipeline.recompose_v2` with its full flag surface.
- `kaizen status [--path]` — summarize recent Kaizen runs in a directory.
- `kaizen priors show|reset [--path]` — inspect / reset Thompson priors files.
- `kaizen web [--port] [--host] [--open]` — start the lite web UI on
  `127.0.0.1:7865`. Requires `pip install 'kaizen-cli[web]'`.
- Structured progress events via `cli.events` — CLI prints human-readable
  lines by default; `KAIZEN_EVENT_STREAM=ndjson` switches to NDJSON for
  `jq` / CI log ingestion. Wedge commands emit
  `run.start` / `stage` / `detail` / `stage.done` / `result` events.

#### Web UI (`kaizen-cli[web]`, optional)

- FastAPI backend at `kaizen_web/` — 11 routes over the CLI surface. Blocking
  and SSE variants for all four pipeline commands (decompose, recompose,
  memsafe-roadmap, migrate-plan). Read-only routes for status, priors,
  artifact listing, ADR markdown fetch, provider/version introspection.
- React SPA at `ui-lite/` — 7 pages: Home, Decompose, Recompose, Memsafe,
  Migrate, Local runs, ADR viewer. Vite + React 18 + Tailwind + React Query +
  `@microsoft/fetch-event-source` for POST-SSE consumption.
- Single-origin deployment: `kaizen web` serves the pre-built SPA at `/`
  alongside `/api/*` — no CORS, no separate dev server after install.
- Live progress streaming: every long-running wedge/pipeline call renders
  stage-by-stage in the browser via SSE.

#### Documentation & Release Tooling (internal)

Release tooling + the allowlist-driven public-extract pipeline live in the
upstream monorepo and are not shipped in this repo. Public users consume
the released wheel on PyPI; contributors see the Apache-2.0 source here.

### Dual-license boundary (ADR-0053)

Apache-2.0 covers the public CLI + web + MCP surfaces shipped here. The
Kaizen Enterprise Commercial License covers the .NET + React Commercial UI
(multi-tenancy, auth, audit-log, approval workflows, cost attribution) which
lives in a separate private repo. See `NOTICE` for the tier summary and
contact hello@kaizen-3c.dev for the commercial surface.

### Not shipped in v0.3.0

- `kaizen run` (pre-reframe generic bootstrap orchestrator) — stays in the
  private dev repo. Requires the `agents/src/` transitive closure which is
  not on the public allowlist for v0.3.0. The Phase B wedges and the
  decompose/recompose primitives cover the public surface.
- Rust orchestrator (`core/`) — 40+ deferred modules; Python pipeline is the
  only end-to-end path in v0.3.0.
- Enterprise components (auth, MFA, SSO, RBAC, multi-tenancy, audit-log
  export, approval workflows, cost attribution UI) — Commercial-tier only.

### Case studies (reproducible)

Case-study writeups live in the upstream monorepo alongside source artifacts:

- **memsafe-01-inih** — C → Rust, 522 LOC. One-shot LLM: 6 `cargo check`
  errors. Plain ADR pipeline: 1 error. ADR + memory-safe domain schema:
  **0 errors**.
- **framework-01-nancy-context** — .NET Fx → .NET 8, 148 LOC. One-shot:
  14 `dotnet build` errors. Plain ADR pipeline: **0 errors**.

---

## [Unreleased]
### Added
- Beta release preparation (security hardening, documentation, ADR cleanup)

---

## [0.1.0-alpha] - 2026-04-10

### Core Engine

#### Added
- Rust orchestrator foundation with TTD-TOAR (renamed CD-AOR/TAOR) denoising loop
- Three-stream parallel execution pipeline in gRPC orchestrator
- Convergence gate and TAOR optimization with production benchmarks
- Phase 4B/Phase 5 48-hour baseline validation and 14-day RL training run
- 24-hour production monitoring and deployment approval workflow
- Cloud baseline validation with dual-track testing and cost routing analysis
- Held-out validation set for Opus critical review methodology

#### Fixed
- Rust type inference errors with explicit annotations across orchestrator modules
- Proto import paths and oneof Result enum usage in agent responses
- `Result` type name conflict resolved via fully qualified paths
- Deferred unimplemented Phase 9–11 modules to unblock orchestrator build

---

### Agents

#### Added
- Python gRPC agent layer with intelligent provider routing and liteLLM fallback
- Dual-provider configuration with independent Local/Cloud enabled/disabled toggles
- Real-time provider health status checking with auto-refresh
- Dynamic provider selection and cost estimation (7× cloud multiplier)
- Phase 27: Two-step goal submission with in-memory file upload session service
- Provider routing implementation guide and architecture documentation

#### Fixed
- Duplicate `ProviderOptions` and `RlConfig` definitions removed
- gRPC service serving deferred until proto integration complete
- gRPC client compilation errors resolved

---

### API

#### Added
- Phase 28: C# REST API with user authentication and PostgreSQL session management
- Phase 29: User profiles, refresh tokens, audit logging, and password reset
- Phase 30: Enhanced security with session hardening and CSRF/token rotation
- Database migrations and PostgreSQL connectivity
- CORS configuration driven by environment variables
- Comprehensive testing infrastructure with project isolation
- Goal history and artifact persistence API (Phases 1–5)
- Work sessions API with frontend integration

#### Changed
- Renamed CD-AOR/TAOR fields across entire C# API and proto layer (was TTD-TOAR/TOAR)
- Login set as initial landing route; home page gains Sign In button

#### Fixed
- HTTP 400 error on goal submission due to missing required fields
- API URL corrected to port 8001 across all consumers
- Login field name mismatch (`email` vs `username`)
- JSON deserialization issues in authentication API responses
- CORS configuration for separated UI/API container topology

---

### Frontend

#### Added
- React UI with decompose/recompose pages and goal submission workflow
- Enhanced submit-goal form with comprehensive CD-AOR controls and file upload
- Goal History system: create, list, detail, and artifact persistence (Phases 1–5)
- Work Sessions system with modal, list, and session state management
- Expandable textarea modal for composing large prompts
- Model selection flyout menu with 5 LLM options (GPT-4, Claude, Llama 2, etc.)
- 40+ `data-testid` attributes added for E2E test coverage
- Outline icons for all sidebar and toolbar buttons; infinity symbol in header

#### Changed
- Sidebar button styling updated to square shape matching AGENTS panel
- Model button repositioned to far-right of button row, aligned with textarea edge

#### Fixed
- Blank dashboard display resolved with welcome content
- UI API URL configuration corrected for browser (non-container) access
- Send/expand button arrows always visible (removed `transition-all` opacity conflict)
- `NewSessionModal` missing import and rendering restored
- Sidebar icons always visible with explicit fill, stroke, and opacity values

---

### Infrastructure

#### Added
- Docker Compose stacks for API, UI, LLM, and orchestrator services
- Nginx reverse proxy configuration for multi-container topology
- GitHub Actions CI/CD workflow for automated LaTeX PDF compilation
- CI/CD pipeline improvements and versioning scheme (P3 remediation)
- Comprehensive QA testing infrastructure and E2E test suite (Playwright)
- 13/13 authentication E2E tests passing; goals/decompose/recompose tests with graceful skipping

#### Fixed
- Docker dependency injection configuration enabling full stack deployment
- GitHub Actions updated to latest stable action versions
- Line endings normalized to LF for LaTeX source files

---

### Architecture

#### Added
- Three-tier workspace architecture with mirror script
- Comprehensive development roadmap covering Phases 1–30+
- ADR gap analysis across five iterations (V1–V5); all 49 gaps resolved at V5
- 14 residual issues (R1–R14) identified and remediated across P0–P2 implementation
- LaTeX empirical paper and research paper variants with statistical validation
- Hit-and-Adjust summary with Phase 4B findings
- PDF compilation guide with five build methods and Python helper script

#### Changed
- TTD-TOAR/TOAR terminology renamed to CD-AOR/TAOR across all ADRs and documentation

---

### Enterprise

#### Added
- Multi-tenancy foundation via PostgreSQL user and session isolation
- Audit logging for user management events (Phase 29)
- Password reset flow with token lifecycle management
- Refresh token rotation with session revocation support

---

## [0.0.1] - 2026-03-01 (estimated)
### Added
- Initial repository setup with three-tier workspace architecture
- Phase 1 Picasso Study: CD-AOR/TAOR foundation in kaizen-alpha
- Base Docker infrastructure and LLM stack scaffolding
- Dashboard and form baseline from early UI prototype
