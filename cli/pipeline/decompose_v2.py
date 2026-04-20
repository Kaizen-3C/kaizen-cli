"""Decompose v2: structured-schema extraction via Anthropic tool use.

Eliminates the prose-level invention failure mode from v1 (4-tier hallucination)
by forcing every decision to cite source evidence. The model fills a strict
JSON schema; we template-render to ADR markdown.
"""
import argparse
import copy
import json
import sys
import time
from pathlib import Path

import anthropic

MODEL = "claude-sonnet-4-5"
DEFAULT_OPENAI_MODEL = "gpt-4.1"


def _call_anthropic(client, *, tool, system, user, temperature):
    """Wrap Anthropic's messages.create to mirror the return shape we want."""
    resp = client.messages.create(
        model=MODEL, max_tokens=8000, system=system, temperature=temperature,
        tools=[tool], tool_choice={"type": "tool", "name": tool["name"]},
        messages=[{"role": "user", "content": user}],
    )
    tool_use = next((b for b in resp.content if b.type == "tool_use"), None)
    data = tool_use.input if tool_use else None
    return {
        "data": data,
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
        "stop_reason": getattr(resp, "stop_reason", None),
    }


def _call_openai(client, *, tool, system, user, temperature, model: str):
    """Wrap OpenAI's chat.completions.create as a mirror of the Anthropic shape.

    OpenAI's tool schema nests under {"type": "function", "function": {...}},
    and tool-call arguments come back as a JSON *string* (Anthropic returns a dict).
    Reasoning models (o*, gpt-5*) reject temperature and need max_completion_tokens.
    """
    openai_tool = {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],
        },
    }
    is_reasoning = model.lower().startswith(("o1", "o3", "o4", "gpt-5"))
    kwargs = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "tools": [openai_tool],
        "tool_choice": {"type": "function", "function": {"name": tool["name"]}},
    }
    if is_reasoning:
        kwargs["max_completion_tokens"] = 16000
    else:
        kwargs["max_tokens"] = 8000
        kwargs["temperature"] = temperature
    resp = client.chat.completions.create(**kwargs)
    msg = resp.choices[0].message
    call = (msg.tool_calls or [None])[0]
    data = None
    if call and call.function and call.function.arguments:
        try:
            data = json.loads(call.function.arguments)
        except json.JSONDecodeError:
            data = None
    return {
        "data": data,
        "input_tokens": resp.usage.prompt_tokens,
        "output_tokens": resp.usage.completion_tokens,
        "stop_reason": resp.choices[0].finish_reason,
    }

# --- JSON schema the LLM must fill ---------------------------------------

ADR_TOOL = {
    "name": "emit_adr",
    "description": (
        "Emit an ADR in structured form. Every claim in decision_claims or "
        "consequences must cite source evidence (file:line_range or identifier). "
        "Do not include claims not evidenced in source."
    ),
    "input_schema": {
        "type": "object",
        "required": ["title", "status", "context", "decision_drivers",
                     "decision_claims", "consequences", "key_identifiers"],
        "properties": {
            "title": {"type": "string", "description": "Short ADR title"},
            "status": {"type": "string",
                       "enum": ["Accepted", "Proposed", "Deprecated", "Superseded"]},
            "context": {
                "type": "string",
                "description": "2-4 sentences: why does this code exist? What problem?"
            },
            "decision_drivers": {
                "type": "array",
                "description": "Bulleted forces that shaped the design, inferred from code.",
                "items": {"type": "string"}
            },
            "decision_claims": {
                "type": "array",
                "description": "Each claim is one architectural decision evidenced in source.",
                "items": {
                    "type": "object",
                    "required": ["claim", "evidence"],
                    "properties": {
                        "claim": {"type": "string",
                                  "description": "Imperative: 'Use X', 'Implement Y as Z'"},
                        "evidence": {"type": "string",
                                     "description": "file.py:line_start-line_end OR ClassName.method"}
                    }
                }
            },
            "consequences": {
                "type": "object",
                "required": ["positive", "negative", "neutral"],
                "properties": {
                    "positive": {"type": "array", "items": {
                        "type": "object", "required": ["claim"],
                        "properties": {"claim": {"type": "string"},
                                       "evidence": {"type": "string"}}}},
                    "negative": {"type": "array", "items": {
                        "type": "object", "required": ["claim"],
                        "properties": {"claim": {"type": "string"},
                                       "evidence": {"type": "string"}}}},
                    "neutral":  {"type": "array", "items": {
                        "type": "object", "required": ["claim"],
                        "properties": {"claim": {"type": "string"}}}}
                }
            },
            "key_identifiers": {
                "type": "array",
                "description": (
                    "Core symbols a reimplementation must preserve. 'kind' is a "
                    "short language-appropriate label: class, function, constant, "
                    "enum, dataclass (Python); function, variable, command, "
                    "sourced-file (bash); struct, trait, fn, const (Rust); etc. "
                    "For functions/methods: include 'signature' with exact "
                    "argument list AND return type as a single string, using "
                    "source-language syntax. For classes: include 'attributes' "
                    "listing public class-level attributes. These are LOAD-"
                    "BEARING — the reimplementation must match them exactly."
                ),
                "items": {
                    "type": "object",
                    "required": ["name", "kind", "file"],
                    "properties": {
                        "name": {"type": "string"},
                        "kind": {"type": "string",
                                 "description": "Language-appropriate symbol kind"},
                        "file": {"type": "string"},
                        "signature": {
                            "type": "string",
                            "description": (
                                "For functions/methods ONLY. Full signature incl. "
                                "argument names, default values, return type. "
                                "Use source-language syntax verbatim. Examples: "
                                "'def fix_package_name(package_or_url: str, package_name: str) -> str:' or "
                                "'def valid_pypi_name(package_spec: str) -> Optional[str]:'. "
                                "Omit for non-function kinds."
                            )
                        },
                        "attributes": {
                            "type": "array",
                            "description": (
                                "For classes ONLY. Public class-level attributes "
                                "(not instance attributes set in __init__ unless "
                                "they are documented API). Examples for a "
                                "YesNoPrompt class: ['yes_choices', 'no_choices']. "
                                "Omit for non-class kinds."
                            ),
                            "items": {"type": "string"}
                        }
                    }
                }
            },
            "output_contracts": {
                "type": "array",
                "description": (
                    "For CLI tools or anything with an observable IO interface: "
                    "one row per user-facing command or entry point capturing the "
                    "EXACT stdout format, exit-code conventions, and side effects. "
                    "This is load-bearing — downstream pipes and tests depend on "
                    "byte-level format. Omit entirely for pure library code."
                ),
                "items": {
                    "type": "object",
                    "required": ["command"],
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "Invocation form, e.g. 'adr list' or 'adr new TITLE'"
                        },
                        "stdout_format": {
                            "type": "string",
                            "description": (
                                "Exact stdout template with placeholders in angle brackets. "
                                "Include newlines and separators verbatim. Example: "
                                "'<rel-path>\\n  (one line per ADR, sorted)'"
                            )
                        },
                        "stderr_format": {
                            "type": "string",
                            "description": "Stderr on error cases, if any"
                        },
                        "exit_codes": {
                            "type": "string",
                            "description": "e.g. '0 on success, 1 on usage error'"
                        },
                        "side_effects": {
                            "type": "string",
                            "description": "File-system writes, env reads, etc."
                        },
                        "evidence": {
                            "type": "string",
                            "description": "file:line_range grounding the contract"
                        }
                    }
                }
            }
        }
    }
}

SYSTEM = """You are an architectural-decomposition expert. You emit ADRs by
calling the emit_adr tool. Every decision_claim or consequence claim MUST cite
the source evidence (file.py:line_range or ClassName.method). If you can't cite
evidence, do not include the claim. Never invent features not in the source."""

SYSTEM_MEMORY_SAFE_ADDENDUM = """

DOMAIN: memory-safe (C/C++ \u2192 Rust). Fill these additional schema fields:

- ownership_decisions: for every resource the source manages (heap string, buffer,
  pointer, owned struct), pick the Rust ownership model (owned T, borrowed &T,
  mutably borrowed &mut T, shared Arc<T>, interior-mutable RefCell<T>). Cite the
  source usage pattern as evidence.
- lifetime_annotations: for any references carried across function boundaries,
  name the lifetime bound implied by source usage.
- unsafe_justifications: only populate for code that genuinely cannot be
  expressed in safe Rust (FFI, raw-pointer arithmetic with provably-sound
  contracts). Prefer empty array; each retained `unsafe` block raises the
  audit-review cost of the output.

These fields are LOAD-BEARING: the Rust reimplementation MUST honor them.
"""

SYSTEM_FRAMEWORK_MIGRATION_ADDENDUM = """

DOMAIN: framework-migration. Fill these additional schema fields:

- api_contract: the public surface that MUST survive the framework transition
  exactly (HTTP routes, exported functions, event names, CLI flags). These are
  what customers depend on and must not change.
- state_management_model: how the source framework holds state (AngularJS
  services+$scope, .NET Framework static/HttpContext, Spring 4 singletons),
  and the intended target (Angular signals+injectables, .NET 8 scoped DI,
  Spring Boot 3 @Bean). Evidence: file:line where the pattern is established.
- routing_model: source and target routing approach.
- dependency_upgrade_path: per third-party dependency, decide upgrade / replace
  / remove.

These fields are LOAD-BEARING: the reimplementation MUST honor them.
"""


def gather_sources(input_dir: Path, glob_pat: str = "*.py") -> tuple[str, dict]:
    # Support explicit file-list mode (pattern starts with "@") for files without
    # standard extensions (e.g. bash scripts with no .sh suffix).
    if glob_pat == "*":
        files = sorted(p for p in input_dir.iterdir()
                       if p.is_file() and p.stat().st_size > 0)
    else:
        files = sorted(p for p in input_dir.glob(glob_pat) if p.stat().st_size > 0)
    parts = []
    meta = {}
    for p in files:
        body = p.read_text(encoding="utf-8", errors="replace")
        # prefix with 1-indexed line numbers so the LLM can cite accurately
        numbered = "\n".join(f"{i+1:4}  {line}" for i, line in enumerate(body.splitlines()))
        parts.append(f"=== FILE: {p.name} ===\n{numbered}\n")
        meta[p.name] = body.count("\n") + 1
    return "\n".join(parts), meta


def _as_list(v) -> list[str]:
    """Normalize to list[str] — handles LLM schema slips where an array field
    arrives as a newline/bullet-delimited string."""
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str):
        import re
        parts = re.split(r"(?:^|\n)\s*[-*]\s+", v)
        return [p.strip() for p in parts if p.strip()]
    return []


def render_markdown(adr_id: str, data: dict) -> str:
    lines = [f"# {adr_id}: {data['title']}", ""]
    lines += ["## Status", data["status"], ""]
    lines += ["## Context", data["context"], ""]
    lines += ["## Decision Drivers"]
    lines += [f"- {d}" for d in _as_list(data.get("decision_drivers", []))]
    lines += [""]
    lines += ["## Decision"]
    for c in data.get("decision_claims", []):
        lines += [f"- {c['claim']}  _(evidence: `{c['evidence']}`)_"]
    lines += [""]
    lines += ["## Consequences", ""]
    cons_raw = data.get("consequences", {})
    # Defensive: Sonnet sometimes serializes the object as a JSON string.
    if isinstance(cons_raw, str):
        try:
            cons_raw = json.loads(cons_raw)
        except json.JSONDecodeError:
            cons_raw = {}
    cons = cons_raw if isinstance(cons_raw, dict) else {}
    for bucket, label in [("positive", "Positive"),
                          ("negative", "Negative"),
                          ("neutral",  "Neutral")]:
        lines += [f"### {label}"]
        bucket_items = cons.get(bucket, []) or []
        if isinstance(bucket_items, str):
            # list-of-objects degenerated to a string: fall back to bullet lines
            for line in bucket_items.splitlines():
                ln = line.strip().lstrip("-* ").strip()
                if ln:
                    lines += [f"- {ln}"]
        else:
            for c in bucket_items:
                if isinstance(c, str):
                    lines += [f"- {c}"]
                    continue
                ev = c.get("evidence", "")
                suffix = f"  _(evidence: `{ev}`)_" if ev else ""
                lines += [f"- {c.get('claim', str(c))}{suffix}"]
        lines += [""]
    def _cell_safe(s: str) -> str:
        """Collapse newlines and escape pipe characters so the markdown table row
        doesn't split into phantom columns. Signatures may legitimately contain
        `|` (e.g. `str | bool` type unions) or `\\n` (decorators on their own
        line). Both break | separated tables."""
        return str(s).replace("\n", " ").replace("|", r"\|").strip()

    # Determine whether any identifier carries signature/attributes data.
    # If not, fall back to the legacy 3-column Key Identifiers format so the
    # --no-signatures case produces clean ADRs without empty trailing columns.
    ki_entries = data.get("key_identifiers", [])
    any_sig_or_attrs = any(
        k.get("signature") or k.get("attributes") for k in ki_entries
    )

    lines += ["## Key Identifiers", ""]
    if any_sig_or_attrs:
        lines += ["| Name | Kind | File | Signature / Attributes |",
                  "|------|------|------|------------------------|"]
    else:
        lines += ["| Name | Kind | File |", "|------|------|------|"]
    for k in ki_entries:
        sig = k.get("signature") or ""
        attrs = k.get("attributes") or []
        if isinstance(attrs, str):
            try:
                attrs = json.loads(attrs)
            except json.JSONDecodeError:
                attrs = [a.strip() for a in attrs.split(",") if a.strip()]
        if not any_sig_or_attrs:
            lines += [f"| `{k['name']}` | {k['kind']} | `{k['file']}` |"]
            continue
        if sig:
            extra = f"`{_cell_safe(sig)}`"
        elif attrs:
            extra = ", ".join(f"`{_cell_safe(a)}`" for a in attrs)
        else:
            extra = ""
        lines += [f"| `{k['name']}` | {k['kind']} | `{k['file']}` | {extra} |"]
    lines += [""]
    # If any identifiers carry signatures/attributes, call them out explicitly so
    # the recompose prompt can lean on them. This section is a duplicate of the
    # table for readability — the recompose parser only uses the table.
    sigs = [k for k in data.get("key_identifiers", []) if k.get("signature")]
    attrs_list = [k for k in data.get("key_identifiers", [])
                  if k.get("attributes") and not k.get("signature")]
    if sigs or attrs_list:
        lines += ["### Load-bearing signatures / attributes", ""]
        lines += ["Implementations MUST match these exactly.", ""]
        for k in sigs:
            lines += [f"- **`{k['name']}`** ({k['kind']}): `{k['signature']}`"]
        for k in attrs_list:
            attr_list = k["attributes"]
            if isinstance(attr_list, str):
                try:
                    attr_list = json.loads(attr_list)
                except json.JSONDecodeError:
                    attr_list = [a.strip() for a in attr_list.split(",") if a.strip()]
            attrs_str = ", ".join(f"`{a}`" for a in attr_list)
            lines += [f"- **`{k['name']}`** ({k['kind']}): attributes {attrs_str}"]
        lines += [""]

    # Output Contracts — only emit the section if non-empty.
    contracts = data.get("output_contracts") or []
    if contracts:
        lines += ["## Output Contracts", ""]
        lines += ["**Load-bearing**: implementations must reproduce these exactly."]
        lines += [""]
        for c in contracts:
            lines += [f"### `{c.get('command', '(unspecified)')}`"]
            if c.get("stdout_format"):
                lines += ["", "**stdout format:**", "```", c["stdout_format"].rstrip(), "```"]
            if c.get("stderr_format"):
                lines += ["", "**stderr format:**", "```", c["stderr_format"].rstrip(), "```"]
            if c.get("exit_codes"):
                lines += ["", f"**exit codes:** {c['exit_codes']}"]
            if c.get("side_effects"):
                lines += ["", f"**side effects:** {c['side_effects']}"]
            if c.get("evidence"):
                lines += ["", f"**evidence:** `{c['evidence']}`"]
            lines += [""]

    # Memory-safe domain sections (--domain memory-safe).
    own = data.get("ownership_decisions") or []
    if own:
        lines += ["## Ownership Decisions (memory-safe domain)", ""]
        lines += ["**Load-bearing**: the Rust reimplementation MUST honor each row."]
        lines += ["", "| Resource | Target ownership | Evidence |",
                  "|----------|------------------|----------|"]
        for o in own:
            lines += [f"| {_cell_safe(o.get('resource',''))} | "
                      f"`{_cell_safe(o.get('ownership',''))}` | "
                      f"`{_cell_safe(o.get('evidence',''))}` |"]
        lines += [""]
    lifetimes = data.get("lifetime_annotations") or []
    if lifetimes:
        lines += ["## Lifetime Annotations", ""]
        for lt in lifetimes:
            lines += [f"- `{lt.get('symbol','')}`: {lt.get('lifetime','')}"]
        lines += [""]
    unsafe = data.get("unsafe_justifications") or []
    if unsafe:
        lines += ["## Retained `unsafe` Blocks", "",
                  "**Each block below must be justified and minimized in the output.**", ""]
        for u in unsafe:
            lines += [f"### `{u.get('block','unnamed')}`",
                      "",
                      f"**Justification**: {u.get('justification','(missing)')}",
                      "",
                      f"**Evidence**: `{u.get('evidence','')}`", ""]

    # Framework-migration domain sections (--domain framework-migration).
    api = data.get("api_contract") or []
    if api:
        lines += ["## API Contract (framework-migration domain)", ""]
        lines += ["**Load-bearing**: each row MUST survive the framework transition exactly."]
        lines += ["", "| Contract | Shape | Evidence |",
                  "|----------|-------|----------|"]
        for a in api:
            lines += [f"| `{_cell_safe(a.get('contract',''))}` | "
                      f"{_cell_safe(a.get('shape',''))} | "
                      f"`{_cell_safe(a.get('evidence',''))}` |"]
        lines += [""]
    state = data.get("state_management_model") or {}
    if isinstance(state, dict) and (state.get("source") or state.get("target")):
        lines += ["## State Management Model", "",
                  f"- **Source**: {state.get('source','(unspecified)')}",
                  f"- **Target**: {state.get('target','(unspecified)')}"]
        if state.get("evidence"):
            lines += [f"- **Evidence**: `{state['evidence']}`"]
        lines += [""]
    routing = data.get("routing_model") or {}
    if isinstance(routing, dict) and (routing.get("source") or routing.get("target")):
        lines += ["## Routing Model", "",
                  f"- **Source**: {routing.get('source','(unspecified)')}",
                  f"- **Target**: {routing.get('target','(unspecified)')}"]
        if routing.get("evidence"):
            lines += [f"- **Evidence**: `{routing['evidence']}`"]
        lines += [""]
    deps = data.get("dependency_upgrade_path") or []
    if deps:
        lines += ["## Dependency Upgrade Path", "",
                  "| Dependency | Decision | Evidence |",
                  "|------------|----------|----------|"]
        for d in deps:
            lines += [f"| {_cell_safe(d.get('dependency',''))} | "
                      f"{_cell_safe(d.get('decision',''))} | "
                      f"`{_cell_safe(d.get('evidence',''))}` |"]
        lines += [""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--adr-id", required=True)
    ap.add_argument("--glob", default="*.py",
                    help="File glob (default *.py). Use '*' for all files (e.g. bash scripts).")
    ap.add_argument("--source-language", default="Python",
                    help="Source language label, informs the prompt (e.g. Python, Bash, Rust)")
    ap.add_argument("--temperature", type=float, default=0.0,
                    help="Sampling temperature (default 0.0, nearly deterministic). "
                         "Pass 1.0 to reproduce pre-2026-04-19 pipeline behavior.")
    ap.add_argument("--no-signatures", action="store_true",
                    help="Strip 'signature' and 'attributes' fields from Key "
                         "Identifiers. Default includes them. Omit signatures "
                         "when targeting mock-heavy test suites where tight "
                         "signature typing clashes with duck-typed mocks "
                         "(see SIGNATURE_SCHEMA_EXPERIMENT_2026-04-19.md).")
    ap.add_argument("--provider", default="anthropic", choices=["anthropic", "openai"],
                    help="LLM provider (default anthropic). 'openai' uses the "
                         "OpenAI chat.completions + function-calling API.")
    ap.add_argument("--model", default=None,
                    help="Model name. Default: claude-sonnet-4-5 for anthropic, "
                         f"{DEFAULT_OPENAI_MODEL} for openai.")
    ap.add_argument("--domain", default="none",
                    choices=["none", "memory-safe", "framework-migration"],
                    help="Wedge-specific schema preset. 'memory-safe' adds "
                         "ownership_decisions, lifetime_annotations, unsafe_"
                         "justifications for C/C++ \u2192 Rust work. 'framework-"
                         "migration' adds api_contract, state_management_model, "
                         "routing_model, dependency_upgrade_path for framework "
                         "transitions. See docs/markets/ for per-wedge context.")
    args = ap.parse_args()

    input_dir = Path(args.input)
    bodies, line_counts = gather_sources(input_dir, args.glob)

    user = (
        f"Decompose the following {args.source_language} source into an ADR by "
        f"calling emit_adr. Target ADR id: {args.adr_id}. Source files and line "
        f"counts: {json.dumps(line_counts)}. Cite evidence as `filename:start-end`.\n\n"
        f"{bodies}"
    )

    # When --no-signatures is set, strip the signature/attributes fields from the
    # Key Identifiers schema so the model doesn't waste tokens on them and the
    # ADR markdown stays in 3-column compat mode.
    tool = copy.deepcopy(ADR_TOOL)
    if args.no_signatures:
        ki = tool["input_schema"]["properties"]["key_identifiers"]["items"]
        ki["properties"].pop("signature", None)
        ki["properties"].pop("attributes", None)
        # Trim the verbose schema description back to its pre-2026-04-19 shape.
        tool["input_schema"]["properties"]["key_identifiers"]["description"] = (
            "Core symbols a reimplementation must preserve. 'kind' is a short "
            "language-appropriate label: class, function, constant, enum, "
            "dataclass (Python); function, variable, command, sourced-file "
            "(bash); struct, trait, fn, const (Rust); etc."
        )

    # Domain-specific schema extensions (2026-04-19 reframe: wedge-aligned
    # schema fields. See docs/markets/ for per-wedge context.).
    if args.domain == "memory-safe":
        tool["input_schema"]["properties"]["ownership_decisions"] = {
            "type": "array",
            "description": (
                "For C/C++ \u2192 Rust: for each resource/value the source manages "
                "(heap allocation, pointer, reference, string), the ownership "
                "model in the target. This is LOAD-BEARING: the reimplementation "
                "MUST honor each decision. If a source uses `char*` as a "
                "borrowed view, the decision is 'borrowed (&str)'; if it owns "
                "a heap string, 'owned (String)'."
            ),
            "items": {
                "type": "object",
                "required": ["resource", "ownership", "evidence"],
                "properties": {
                    "resource": {"type": "string",
                                 "description": "The source symbol or pattern, e.g. 'buffer in cJSON_Parse'"},
                    "ownership": {"type": "string",
                                  "description": "Target model: 'owned (T)', 'borrowed (&T)', "
                                                 "'mutably borrowed (&mut T)', 'shared (Arc<T>)', "
                                                 "'interior mutable (RefCell<T>)', etc."},
                    "evidence": {"type": "string",
                                 "description": "file.c:line_range showing the usage pattern"}
                }
            }
        }
        tool["input_schema"]["properties"]["lifetime_annotations"] = {
            "type": "array",
            "description": (
                "For borrowed resources: lifetime bounds inferred from source "
                "usage. Empty array is fine if all references are scoped."
            ),
            "items": {
                "type": "object",
                "required": ["symbol", "lifetime"],
                "properties": {
                    "symbol": {"type": "string"},
                    "lifetime": {"type": "string",
                                 "description": "e.g. \"'a tied to input buffer\", "
                                                "\"'static for global constants\""}
                }
            }
        }
        tool["input_schema"]["properties"]["unsafe_justifications"] = {
            "type": "array",
            "description": (
                "Any `unsafe` blocks the reimplementation must retain, with "
                "evidence and justification. Empty array is fine and preferable."
            ),
            "items": {
                "type": "object",
                "required": ["block", "justification", "evidence"],
                "properties": {
                    "block": {"type": "string",
                              "description": "Short name for the unsafe section"},
                    "justification": {"type": "string",
                                      "description": "Why safe Rust cannot express this"},
                    "evidence": {"type": "string"}
                }
            }
        }
    elif args.domain == "framework-migration":
        tool["input_schema"]["properties"]["api_contract"] = {
            "type": "array",
            "description": (
                "For framework migrations: public API surface that MUST survive "
                "the transition exactly. Each row is one user-facing contract "
                "(HTTP route, exported function, event name, CLI flag)."
            ),
            "items": {
                "type": "object",
                "required": ["contract", "shape", "evidence"],
                "properties": {
                    "contract": {"type": "string",
                                 "description": "Name of the contract, e.g. 'GET /api/users'"},
                    "shape": {"type": "string",
                              "description": "Signature / response shape / event payload — exact"},
                    "evidence": {"type": "string"}
                }
            }
        }
        tool["input_schema"]["properties"]["state_management_model"] = {
            "type": "object",
            "description": (
                "How the source manages state, and the target equivalent. "
                "AngularJS: services/$scope \u2192 Angular: services/signals/NgRx store. "
                ".NET Framework: static/HttpContext \u2192 .NET 8: DI/scoped services."
            ),
            "properties": {
                "source": {"type": "string",
                           "description": "e.g. 'AngularJS services ($scope + $rootScope)'"},
                "target": {"type": "string",
                           "description": "e.g. 'Angular signals + injectable service classes'"},
                "evidence": {"type": "string"}
            }
        }
        tool["input_schema"]["properties"]["routing_model"] = {
            "type": "object",
            "description": "How routing is defined in source and target.",
            "properties": {
                "source": {"type": "string",
                           "description": "e.g. 'Angular 1 $routeProvider config'"},
                "target": {"type": "string",
                           "description": "e.g. 'Angular Router module with lazy-loaded routes'"},
                "evidence": {"type": "string"}
            }
        }
        tool["input_schema"]["properties"]["dependency_upgrade_path"] = {
            "type": "array",
            "description": (
                "Per third-party dependency: upgrade-in-place, replace-with, "
                "or remove. Each row is one package with a migration decision."
            ),
            "items": {
                "type": "object",
                "required": ["dependency", "decision"],
                "properties": {
                    "dependency": {"type": "string",
                                   "description": "Source package name + version"},
                    "decision": {"type": "string",
                                 "description": "'upgrade to X.Y.Z', 'replace with <pkg>', or 'remove (unused)'"},
                    "evidence": {"type": "string"}
                }
            }
        }

    # Compose the system prompt — base + optional domain addendum.
    system_prompt = SYSTEM
    if args.domain == "memory-safe":
        system_prompt = SYSTEM + SYSTEM_MEMORY_SAFE_ADDENDUM
    elif args.domain == "framework-migration":
        system_prompt = SYSTEM + SYSTEM_FRAMEWORK_MIGRATION_ADDENDUM

    t0 = time.time()
    if args.provider == "openai":
        from openai import OpenAI
        oclient = OpenAI()
        model_name = args.model or DEFAULT_OPENAI_MODEL
        call_result = _call_openai(
            oclient, tool=tool, system=system_prompt, user=user,
            temperature=args.temperature, model=model_name,
        )
    else:
        aclient = anthropic.Anthropic()
        call_result = _call_anthropic(
            aclient, tool=tool, system=system_prompt, user=user,
            temperature=args.temperature,
        )
    dt = time.time() - t0

    data = call_result["data"]
    if not data:
        print(f"ERROR: model ({args.provider}) did not fill emit_adr tool "
              f"(stop_reason={call_result.get('stop_reason')})", file=sys.stderr)
        return 2

    md = render_markdown(args.adr_id, data)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    (out.with_suffix(".structured.json")).write_text(
        json.dumps(data, indent=2), encoding="utf-8")

    model_used = (args.model if args.provider == "openai"
                  else MODEL) or (DEFAULT_OPENAI_MODEL if args.provider == "openai" else MODEL)
    meta = {
        "provider": args.provider,
        "model": model_used,
        "input_tokens": call_result["input_tokens"],
        "output_tokens": call_result["output_tokens"],
        "stop_reason": call_result.get("stop_reason"),
        "temperature": args.temperature,
        "domain": args.domain,
        "wall_seconds": round(dt, 2),
        "n_decisions": len(data.get("decision_claims", [])),
        "n_identifiers": len(data.get("key_identifiers", [])),
        "n_consequences": sum(len(data.get("consequences", {}).get(k, []) or [])
                              for k in ("positive", "negative", "neutral")),
        "n_ownership_decisions": len(data.get("ownership_decisions", []) or []),
        "n_api_contracts": len(data.get("api_contract", []) or []),
    }
    (out.with_suffix(".meta.json")).write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
