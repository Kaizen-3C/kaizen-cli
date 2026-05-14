# Security Policy

## Reporting a vulnerability

**Please do not open public GitHub issues for security vulnerabilities.**

Instead, report security issues via email to:

> **security@kaizen-3c.dev**

Include, where possible:

- A description of the vulnerability and its potential impact.
- Steps to reproduce, or a proof-of-concept.
- The affected file(s), commit SHA, or release version (PyPI package
  `{{PACKAGE_NAME}}` version string).
- Any suggested fix or mitigation.

PGP-encrypted reports are welcome (key published at
https://kaizen-3c.dev when available; until then, plain email is fine —
please do not include sensitive credentials in plaintext, redact them).

## Response timeline

| Stage                                      | Target                                      |
|--------------------------------------------|---------------------------------------------|
| Acknowledgement of receipt                 | Within 72 hours                             |
| Initial triage + severity assessment       | Within 7 days                               |
| Status update (fix / mitigation / dispute) | Within 30 days                              |
| Public disclosure window                   | 90 days from initial report (coordinated)   |

We follow a **90-day coordinated-disclosure** model. If you have a
stricter or looser disclosure preference, mention it in your initial
report and we will work with you.

## Scope

This policy covers the `kaizen-cli` repository and the `kaizen` CLI
tool it produces. It also covers:

- The `[web]` optional-dependency group (FastAPI server, SSE endpoint).
- The `[mcp]` optional-dependency group (MCP tool-provider server).
- Any future Kaizen-3C public repositories as they are launched.

For the broader Kaizen-3C organization scope, see the SECURITY.md in
the relevant repository or contact security@kaizen-3c.dev.

## Dependency vulnerabilities

If you discover a security vulnerability in a **dependency** (e.g.,
`anthropic`, `openai`, `httpx`, `fastapi`, `mcp`) that is exploitable
specifically through a `kaizen` CLI command or its packaged server
components, please report it here in addition to (or instead of) the
upstream project. We track our dependency exposure and will issue an
advisory and version bump promptly for any confirmed exploitable path,
even when the root cause is upstream.

Vulnerabilities in dependencies that are not exploitable via any kaizen
code path do not need to be reported here — please report those directly
to the upstream project.

## What is NOT a security vulnerability

To save everyone time, the following are **not** security issues for
this repository:

- **LLM outputs containing problematic content.** Model behavior is the
  upstream provider's concern; please report directly to the model
  vendor (Anthropic, OpenAI, etc.).
- **High API costs from running pipeline commands.** Unexpected spend is
  a usage issue, not a security issue — open a regular GitHub Issue.
- **Test failures unrelated to code execution or data exposure.**

## What IS in scope

- Code-execution vulnerabilities in CLI commands or the optional web/MCP
  server components. Sandbox / host-execution policy is governed by
  [ADR-0042: Sandbox Bypass Policy](https://github.com/Kaizen-3C/kaizen-staging/blob/main/.architecture/decisions/ADR-0042-sandbox-bypass-policy.md)
  in the staging repository — cite ADR-0042 in any disclosure that
  touches host-execution semantics.
- Credential or API-key leakage in commands, CI configs, or committed
  artifacts.
- Prompt-injection or tool-call-hijacking vulnerabilities in the
  pipeline layer that allow an attacker-controlled input to cause
  unintended host-system actions.
- Supply-chain risks (e.g., dependency confusion, typosquatted packages
  we depend on).
- Vulnerabilities in any future hosted Kaizen-3C infrastructure
  (dashboards, leaderboards) that ship from this org.

## Recognition

We are grateful to security researchers who report responsibly. With
your permission, we will acknowledge your contribution in the release
notes for the fix and (if you wish) in a future SECURITY-HALL-OF-FAME.md
as the contributor base grows.

---

Thank you for helping keep Kaizen-3C secure.
