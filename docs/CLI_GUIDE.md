# Kaizen CLI Guide

The `kaizen` command-line tool turns legacy codebases into editable
architecture artifacts (ADRs) and — optionally — regenerates code from those
artifacts in a target language.

This guide is task-focused: install once, then follow one of the wedges end-to-end.
For the full flag reference see [`cli/README.md`](../cli/README.md). For the
open-core boundary (what's free vs. commercial) see [`docs/CLI_VS_UI_CAPABILITY_REVIEW.md`](CLI_VS_UI_CAPABILITY_REVIEW.md).

---

## Install

Requires **Python 3.10+**.

```bash
pip install kaizen-cli
```

Add the local web UI (optional, adds FastAPI + uvicorn + a pre-built React SPA):

```bash
pip install 'kaizen-cli[web]'
```

Add the MCP server (optional — lets Claude Desktop / Cursor / Zed call kaizen as a tool):

```bash
pip install 'kaizen-cli[mcp]'
```

Or install everything at once:

```bash
pip install 'kaizen-cli[web,mcp]'
```

Provide at least one LLM credential in your environment — the wedge commands
call a provider to produce ADRs:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
# or
export OPENAI_API_KEY=sk-proj-...
# or run a local Ollama server and skip keys
```

Verify:

```
$ kaizen --version
kaizen 0.3.0
```

---

## Quickstart — 60 seconds

Two reproducible wins, one command each. Both use your local `anthropic` key
(swap to `--provider openai` if you prefer).

### C → Rust memory-safety roadmap

```bash
kaizen memsafe-roadmap ./my-c-lib --output roadmap.md
```

Produces:

- `roadmap.md` — CISA-format memory-safety roadmap
- `adrs/adr-root.md` — root ADR with Key Identifiers + Ownership Decisions
- `adrs/<module>.md` — one ADR stub per key identifier

Add `--recompose --rust-output rust-port/` to also emit a Rust crate. See
the published case study at
[docs/case-studies/memsafe-01-inih/](case-studies/memsafe-01-inih/README.md) —
inih, 522 LOC C, 6 → 1 → 0 `cargo check` errors as scaffolding is added.

### Framework migration plan

```bash
kaizen migrate-plan --from dotnet-framework --to dotnet8 ./my-repo
```

Nine supported pairs:

| `--from`           | `--to`                 |
|--------------------|------------------------|
| `angularjs`        | `angular`, `react`     |
| `jquery`           | `react`                |
| `dotnet-framework` | `dotnet8`, `dotnet9`   |
| `python2`          | `python3`              |
| `spring4`          | `spring-boot3`         |
| `java8`            | `java17`, `java21`     |

Case study: [docs/case-studies/framework-01-nancy-context/](case-studies/framework-01-nancy-context/README.md)
— Nancy `NancyContext.cs`, 148 LOC .NET Framework → .NET 8, 14 → 0 `dotnet build` errors.

---

## Commands

```
kaizen <command> [options]
```

| Command            | Produces                              |
|--------------------|---------------------------------------|
| `decompose`        | an ADR markdown file from a source tree |
| `recompose`        | target-language source code from an ADR |
| `memsafe-roadmap`  | CISA-format memory-safety roadmap + ADRs (C/C++ → Rust wedge) |
| `migrate-plan`     | framework migration plan + ADRs (9 pairs) |
| `status`           | summary of recent Kaizen runs under a path |
| `priors`           | inspect or reset Thompson-sampling priors |
| `resume`           | re-run recompose from the most recent (or specified) ADR |
| `init`             | first-run configuration wizard — writes `~/.kaizen/config.toml` |
| `web`              | start the lite web UI on `127.0.0.1:7865` |
| `mcp-serve`        | run the MCP server so AI clients can invoke kaizen tools |
| `version`          | print the CLI version |

Every command accepts `--help` with the full flag list.

### `kaizen decompose` — source → ADR

Runs the decompose step directly. The wedges (`memsafe-roadmap`,
`migrate-plan`) compose this with domain-specific post-processing; call
`kaizen decompose` when you want the raw ADR without the wedge wrapper —
useful for iterating on ADR schema choices.

```bash
kaizen decompose ./my-repo \
    --output adr-root.md \
    --source-language Python \
    --domain none \
    --provider anthropic
```

Key flags:

- `--glob '*.py'` — source file filter (default `*` — everything)
- `--source-language Python|C|C++|Rust|Go|JavaScript|TypeScript|Java|C#|Bash` — prompt label
- `--domain none|memory-safe|framework-migration` — schema preset
- `--temperature 0.0` — LLM sampling temperature (default deterministic)
- `--no-signatures` — strip signature + attributes from Key Identifiers
- `--dry-run` — print the resolved pipeline command and exit

### `kaizen recompose` — ADR → target code

Regenerates source code from an ADR. Pair with `decompose` for a
round-trip, or feed it an ADR produced by a wedge command.

```bash
kaizen recompose adr-root.md \
    --output-dir recomposed/ \
    --target-language Python \
    --target-python-version 3.12
```

Key flags:

- `--target-language Python|Rust|TypeScript|JavaScript|Java|C#|Go`
- `--cross-language` — translation mode (accept transliterated identifier names)
- `--emit-tests` — hint the model to emit tests alongside implementation
- `--max-tokens 8000` — bump for larger sources (Sonnet 4.5 supports up to 64000)
- `--target-python-version 3.9` — when target is Python; 3.10+ allows PEP 604 unions
- `--no-repair-syntax` — skip the one-shot repair retry for Python syntax errors

### `kaizen memsafe-roadmap` — C/C++ → Rust

Wedge 1. Full flag reference in [`cli/README.md`](../cli/README.md#kaizen-memsafe-roadmap--cc--rust).

```bash
# Three-arm ablation reproduction — scaffolding ladder
kaizen memsafe-roadmap ./my-c-repo --plain -o roadmap.md       # ADR only
kaizen memsafe-roadmap ./my-c-repo -o roadmap.md               # ADR + domain schema
kaizen memsafe-roadmap ./my-c-repo --recompose                 # + Rust crate
```

### `kaizen migrate-plan` — framework modernization

Wedge 2. 9 supported pairs.

```bash
kaizen migrate-plan --from angularjs --to react ./my-repo --recompose \
    --target-output migrated/
```

### `kaizen status` — what's in the local workspace

```bash
kaizen status              # scan ./
kaizen status --path ./out
```

Summarizes the most recent `taor_observations.jsonl` and `priors.json`
files it finds, with the last confidence trajectory.

### `kaizen priors show / reset`

Inspect or wipe the Thompson-sampling priors file that the adaptive
convergence gate reads/writes.

```bash
kaizen priors show              # default path: ./priors.json
kaizen priors show ./mine.json
kaizen priors reset --yes       # skip confirmation
```

### `kaizen init` — first-run wizard

Sets up `~/.kaizen/config.toml` (or `%LOCALAPPDATA%\kaizen\config.toml` on Windows) with your default provider, model, output paths, and pipeline settings. Every subsequent `kaizen` invocation reads this file as a fallback for unset CLI flags — precedence is **CLI flag → env var → config.toml → built-in default**.

```bash
kaizen init                  # interactive wizard
kaizen init --show           # print current config without modifying
kaizen init --non-interactive # write defaults only (CI)
```

Config schema (hand-authored or wizard-written):

```toml
[providers]
default = "anthropic"

[providers.anthropic]
model = "claude-sonnet-4-5"

[output]
adr_dir = "adrs"
roadmap_filename = "roadmap.md"
plan_filename = "plan.md"

[pipeline]
temperature = 0.0
max_tokens = 16000
```

### `kaizen resume` — re-run from a prior ADR

Hand-edit the ADR a wedge produced, then regenerate target code without re-running decompose:

```bash
kaizen resume --list               # show recent candidate ADRs (sorted newest first)
kaizen resume --last               # re-run recompose on the newest ADR found
kaizen resume ./adrs/adr-root.md   # explicit path
kaizen resume inih                 # stem match — finds adr-inih-*.md
kaizen resume --last --target-language Rust --dry-run   # preview the recompose command
```

All `kaizen recompose` flags pass through (`--target-language`, `--cross-language`, `--emit-tests`, `--max-tokens`, etc.).

### `kaizen mcp-serve` — MCP server

Starts an MCP server exposing kaizen's pipeline as tools for Claude Desktop, Cursor, Zed, and any other MCP-capable client. Requires the `[mcp]` extra.

```bash
pip install 'kaizen-cli[mcp]'
kaizen mcp-serve                        # stdio transport (default — for Claude Desktop)
kaizen mcp-serve --transport sse --port 7866   # SSE transport over HTTP
```

Configure Claude Desktop (or any MCP client) at `~/.config/claude-desktop/mcp.json`:

```json
{
  "mcpServers": {
    "kaizen": {
      "command": "kaizen",
      "args": ["mcp-serve"]
    }
  }
}
```

Tools exposed: `decompose`, `recompose`, `memsafe_roadmap`, `migrate_plan`, `list_runs`, `read_adr`. Every tool delegates to the same Python functions the CLI uses — the MCP surface produces identical output to running `kaizen <command>` directly with the same args.

### `kaizen version`

```
$ kaizen version
0.4.0
```

Equivalent to `kaizen --version`.

---

## Pre-recompose approval and adversarial review (v0.4.0)

Two orthogonal flags give you a checkpoint before expensive stages.

### `--approve` / `--yolo` — human checkpoint on `--recompose`

Applies to `memsafe-roadmap` and `migrate-plan`. When you pass `--recompose --approve`, the CLI produces the ADR + roadmap/plan, then prompts:

```
ADR ready at adrs/adr-root.md. Continue to recompose to Rust? [y/N]
```

- Answer `n` (default): exit 0 with partial artifacts already written. Recompose is skipped.
- Answer `y`: continue to recompose.
- `--yolo`: explicit opt-out of the prompt; continues automatically. Equivalent to not passing `--approve`, but scripts can use `--yolo` for clarity.
- In non-TTY environments (CI, piped input), the prompt is skipped and the default ("decline") is used — no hanging build.

### `--llm-review` — adversarial ADR review

Applies to all four pipeline commands. After decompose (or before recompose), a **different model** reviews the produced ADR against anti-vibe-coding heuristics (ADR-0009). The review produces a `<adr>.review.json` sidecar with findings, and `findings_count` / `critical_findings` appear in the final `result` event:

```bash
kaizen memsafe-roadmap ./my-c-lib --llm-review
kaizen decompose ./repo --llm-review --review-model claude-sonnet-4-6
```

The review model is auto-selected via a "flip heuristic" (sonnet-4-5 → sonnet-4-6, gpt-4o → gpt-4.1, etc.) to guarantee a different instance from the write agent. Override explicitly with `--review-model MODEL`.

---

## `kaizen web` — lite web UI

Starts a FastAPI server on `127.0.0.1:7865` that serves a small React SPA +
a JSON API. Every page wraps a CLI command — if `kaizen memsafe-roadmap`
produces an ADR for a given input, the `/memsafe` page in the browser
produces the same ADR for the same input, because the web route calls the
CLI function directly.

### Install

The web UI is an optional extra — it adds `fastapi`, `uvicorn`,
`sse-starlette`, and a pre-built SPA bundle (~90 KB gzipped JS).

```bash
pip install 'kaizen-cli[web]'
```

### Run

```bash
kaizen web --open          # opens your default browser to http://127.0.0.1:7865
kaizen web --port 8080     # custom port
kaizen web --log-level warning   # uvicorn log verbosity
```

```
$ kaizen web --open
kaizen web  listening on  http://127.0.0.1:7865/
  API docs:  http://127.0.0.1:7865/api/docs
```

### Pages

| Route         | Wraps                  | Live streaming? |
|---------------|------------------------|:---------------:|
| `/`           | flow tiles (landing)   | —               |
| `/decompose`  | `kaizen decompose`     | ✅ SSE          |
| `/recompose`  | `kaizen recompose`     | ✅ SSE          |
| `/memsafe`    | `kaizen memsafe-roadmap` | ✅ SSE        |
| `/migrate`    | `kaizen migrate-plan`  | ✅ SSE          |
| `/runs`       | `kaizen status` + local ADR artifacts | — |
| `/adr?path=…` | raw ADR viewer         | —               |

### API

The interactive OpenAPI docs live at `/api/docs` when the server is
running. Every wedge route has a blocking variant (`POST /api/<wedge>`)
and an SSE streaming variant (`POST /api/<wedge>/stream`).

Consume the stream from curl:

```bash
curl -N -X POST http://127.0.0.1:7865/api/memsafe-roadmap/stream \
    -H "Content-Type: application/json" \
    -d '{"repo": "/path/to/repo", "plain": true}'
```

You'll see the event stream unfold:

```
event: run.start
data: {"kind":"run.start","command":"memsafe-roadmap","repo":"/path/to/repo",...}

event: stage
data: {"kind":"stage","name":"decompose","index":1,"total":3,"use_domain":false}

event: detail
data: {"kind":"detail","message":"[decompose] tool-use call 1/1 sent","source":"decompose"}

event: stage.done
data: {"kind":"stage.done","name":"decompose","adr_path":"..."}
...
event: result
data: {"kind":"result","exit_code":0,"roadmap":"roadmap.md",...}

event: end
data: {"kind":"end","exit_code":0}
```

### Security — this is a dev tool

The lite UI binds to `127.0.0.1` by default and has **no authentication**.
`kaizen web --host 0.0.0.0` will work but prints a warning — don't run it
on an untrusted network. For multi-user deployments with auth, audit
trails, approvals, and cost attribution, see the Kaizen Enterprise UI
(a separate, commercial surface — [`docs/commercial/FEATURE_MATRIX.md`](commercial/FEATURE_MATRIX.md)).

---

## Providers and environment variables

The CLI calls an LLM provider to produce the ADR tool-use JSON. Pick one:

| `--provider` | Env var(s) needed              | Notes |
|--------------|--------------------------------|-------|
| `anthropic`  | `ANTHROPIC_API_KEY`            | Default. Claude Sonnet 4.5 by default. |
| `openai`     | `OPENAI_API_KEY`               | GPT-4.1 by default; supports reasoning models. |
| `ollama`     | — (reachable local server)     | Set `--ollama-host` if not localhost. |
| `litellm`    | `LITELLM_API_KEY` + base URL   | Via `--litellm-base-url`. |
| `mixed`      | two of the above               | Per-agent-tier provider mapping. |

You can also drop a `.env` in the directory you invoke the CLI from;
it's loaded automatically and its values are **not overwritten** by any
existing exported env.

```
ANTHROPIC_API_KEY=sk-ant-...
# OPENAI_API_KEY=sk-proj-...
```

Override the model:

```bash
kaizen memsafe-roadmap ./repo --provider anthropic --model claude-sonnet-4-5
```

---

## Output and event streaming

### Human mode (default)

Each stage prints a short progress line:

```
[1/3] decompose
       [decompose] ... subprocess log lines ...
       done: decompose (adr_path=/abs/path/to/adr-root.md)
[2/3] render_roadmap
       done: render_roadmap (roadmap_path=..., identifiers=12, decisions=8)
[3/3] adr_stubs
       done: adr_stubs (stub_count=12, adr_dir=/abs/path/to/adrs)
result: exit_code=0

Done.
  Roadmap:   roadmap.md
  Root ADR:  adrs/adr-root.md
  Stubs:     adrs/ (12 file(s))
```

### NDJSON mode (for scripts, CI, `jq`)

Set `KAIZEN_EVENT_STREAM=ndjson` to switch the CLI to one-event-per-line
JSON — same event schema the web UI's SSE stream uses.

```bash
KAIZEN_EVENT_STREAM=ndjson kaizen memsafe-roadmap ./my-c-lib --plain \
    | jq -c 'select(.kind=="stage" or .kind=="result")'
```

Event kinds: `run.start`, `stage`, `stage.done`, `detail`, `warn`,
`error`, `result`. The final `result` event carries the exit code and
absolute paths to every produced artifact — your CI can parse it and
upload or fail the job accordingly.

### Exit codes

| Code | Meaning                                       |
|:---:|------------------------------------------------|
| 0   | success                                        |
| 1   | pipeline / unhandled exception                 |
| 2   | usage error (bad args, missing repo, bad creds) |
| 3   | decompose did not produce the expected ADR     |
| 130 | interrupted (Ctrl-C). Priors persist if enabled. |

---

## Typical workflows

### Iterate on ADR schema

```bash
# 1. Decompose with no domain schema
kaizen decompose ./my-repo --domain none -o adr.md --source-language Python

# 2. Inspect adr.md, compare Key Identifiers against what you expected

# 3. Re-run with a domain schema
kaizen decompose ./my-repo --domain framework-migration -o adr-enriched.md \
    --source-language Python

# 4. Diff the two ADRs; the extra fields are where the domain schema earns its keep
diff adr.md adr-enriched.md
```

### One-shot baseline for your own measurement

The wedges ship with an inherent control: `--plain` disables the domain
schema so you can measure how much of the win is ADR-as-contract vs.
how much is the schema.

```bash
kaizen memsafe-roadmap ./repo --plain  -o roadmap-plain.md
kaizen memsafe-roadmap ./repo          -o roadmap-full.md
# Compare output. Typically the ADR-as-contract closes most of the gap
# (83% of compile-cleanness on inih); the domain schema is +17% polish.
```

See [docs/case-studies/methodology.md](case-studies/methodology.md) for
the three-arm measurement framework.

### Round-trip

```bash
kaizen decompose ./source    -o adr.md --source-language Python
kaizen recompose adr.md      --output-dir ./recomposed --target-language Python \
    --target-python-version 3.12
diff -r ./source ./recomposed
```

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'fastapi'` when running `kaizen web`.**
You installed the base package but not the `[web]` extra. Rerun:

```bash
pip install 'kaizen-cli[web]'
```

**`ANTHROPIC_API_KEY not set` / `OPENAI_API_KEY not set` warning.**
The web UI's `/api/providers` endpoint will return `configured: false`
for that provider. Export the env var, or drop a `.env` in your working
directory — see [Providers](#providers-and-environment-variables).

**`decompose failed with exit code 1`.** Usually an LLM-side error —
rate limit, invalid model name, quota. Re-run with `--verbose` for the
full stack trace, or check the subprocess output interleaved in the CLI's
stage log.

**Warning: binding to a non-loopback host.**
You passed `kaizen web --host 0.0.0.0`. Intentional if you know what
you're doing; don't do it on untrusted networks — there's no auth.

**`kaizen run` says "invalid choice".** That command shipped in earlier
(pre-v0.3.0) builds and is intentionally not included in the first
public release. Use `kaizen memsafe-roadmap`, `kaizen migrate-plan`, or
`kaizen decompose` + `kaizen recompose` instead.

---

## See also

- [`cli/README.md`](../cli/README.md) — full flag reference for every command
- [`docs/CLI_ROADMAP.md`](CLI_ROADMAP.md) — planned features (config dir, MCP server, TUI, adversarial review)
- [`docs/CLI_VS_UI_CAPABILITY_REVIEW.md`](CLI_VS_UI_CAPABILITY_REVIEW.md) — what's free vs. commercial
- [`docs/commercial/FEATURE_MATRIX.md`](commercial/FEATURE_MATRIX.md) — enterprise wrapper tier
- [`docs/case-studies/`](case-studies/) — reproducible measurements (inih, Nancy)
- [`docs/markets/MEMORY_SAFETY_WEDGE.md`](markets/MEMORY_SAFETY_WEDGE.md) — why C/C++ → Rust
- [`docs/markets/FRAMEWORK_MODERNIZATION_WEDGE.md`](markets/FRAMEWORK_MODERNIZATION_WEDGE.md) — why framework migrations
- [`STRATEGIC_ROADMAP.md`](../STRATEGIC_ROADMAP.md) — where the project is going
