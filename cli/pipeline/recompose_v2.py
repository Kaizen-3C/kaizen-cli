"""Recompose v2: direct-API Recompose. The symmetric counterpart to decompose_v2.

Design principle: the ADR is the scaffold. The Key Identifiers table lists the
symbols a faithful reimplementation must preserve. This pass does NOT add
abstractions the ADR does not name; it does NOT rename symbols.

Kaizen's orchestrator has a template prior (signals-as-dataclasses, weights-as-
separate-module) that overrides the spec. This skips the orchestrator.
"""
import argparse
import ast
import json
import re
import sys
import time
from pathlib import Path

import anthropic
import httpx

MODEL = "claude-sonnet-4-5"
DEFAULT_OPENAI_MODEL = "gpt-4.1"

CODE_TOOL = {
    "name": "emit_code",
    "description": (
        "Emit a Python implementation of the ADR. Every symbol in the ADR's "
        "'Key Identifiers' table MUST appear in the output with its exact name "
        "and kind. Do NOT introduce abstractions not named in the ADR."
    ),
    "input_schema": {
        "type": "object",
        "required": ["files", "preserved_identifiers", "notes"],
        "properties": {
            "files": {
                "type": "array",
                "description": "Output files. Produce the minimum file count that satisfies the ADR — do not split arbitrarily.",
                "items": {
                    "type": "object",
                    "required": ["path", "content"],
                    "properties": {
                        "path": {"type": "string",
                                 "description": "Relative path, e.g. 'composite.py' or 'tests/test_composite.py'"},
                        "content": {"type": "string",
                                    "description": "Full Python file content. No markdown fences."}
                    }
                }
            },
            "preserved_identifiers": {
                "type": "array",
                "description": "Echo back the list of Key Identifiers from the ADR; the runtime verifies each one appears verbatim in the output.",
                "items": {"type": "string"}
            },
            "notes": {
                "type": "string",
                "description": "≤3 sentences: any decisions made where the ADR was silent."
            }
        }
    }
}

SYSTEM_SAME_LANGUAGE = """You translate an ADR into {target} implementation. You
are a faithful transcriber, not an architect. Rules:

1. Every symbol in the ADR's 'Key Identifiers' table MUST appear with its exact
   name (class name, constant name, function name) in the output.
2. Do NOT rename symbols. If the ADR says `CompositeScorer`, output
   `CompositeScorer` — never `CompositeConfidenceScorer`.
3. Do NOT introduce abstractions the ADR does not name. If the ADR describes a
   `DEFAULT_WEIGHTS` dict, output a dict — not a `WeightConfig` dataclass.
4. Produce the MINIMUM file count needed. A single-module ADR -> one file.
5. If the ADR explicitly asks for tests, emit tests. Otherwise, do not.
6. If the ADR is silent on an implementation detail, make the simplest choice
   that honors the stated decisions. Note these in 'notes'.
7. Do not include docstring blocks that exceed the explanations in the ADR.
8. When a Key Identifier row has a 'Signature / Attributes' cell (4-column
   table), the signature is LOAD-BEARING and must match exactly:
   - For functions/methods: argument names, argument order, default values,
     annotations, and return type must match byte-for-byte. If the ADR
     signature is `def valid_pypi_name(package_spec: str) -> Optional[str]:`,
     output a function returning Optional[str], not bool, not None-on-miss.
   - For classes: every listed class-level attribute must appear on the class
     at module-scope, with the exact name. Missing `YesNoPrompt.yes_choices`
     is a hard error, not a stylistic choice.
   - If the ADR's 'Load-bearing signatures / attributes' subsection is
     present, treat each bullet as a test assertion the output must satisfy.

Failure to preserve a Key Identifier, its signature, or a listed class
attribute is a hard error — the runtime checks.
"""

SYSTEM_CROSS_LANGUAGE = """You translate an ADR into {target} implementation. The
ADR was derived from a DIFFERENT source language, so symbol names in the Key
Identifiers table use the source language's conventions. Rules:

1. For each Key Identifier, emit a {target}-idiomatic equivalent AND include
   either the original name OR its {target}-conventional transliteration as a
   recognizable substring in the output (e.g. bash `adr-init` -> Python
   `adr_init` or `AdrInit`; bash `VISUAL` -> `VISUAL`; bash `.adr-dir` ->
   `ADR_DIR_FILE`). Put the mapping in 'notes'.
2. Preserve the DECISIONS — what the code DOES — not the syntax.
3. Do NOT introduce abstractions the ADR does not name.
4. Produce the MINIMUM file count needed.
5. If the ADR explicitly asks for tests, emit tests. Otherwise, do not.
6. If the ADR is silent on an implementation detail, make the simplest choice.
7. When the ADR contains an 'Output Contracts' section, it is LOAD-BEARING:
   every listed command's stdout, stderr, exit codes, and side effects MUST
   match the contract exactly. For CLI tools, downstream pipes and tests
   depend on byte-level format. No adding extra columns, no prepending paths,
   no rephrasing messages. Quote the contract in a comment above each
   command's implementation to prove you read it.
8. For cross-language invocations (e.g. one CLI subcommand spawning another):
   use `sys.executable` + absolute paths, never hardcoded interpreter names
   or relative paths. Windows does not have `python3`.
"""


_ESCAPED_PIPE = "\x00PIPE\x00"  # sentinel for round-trip of escaped pipes


def extract_key_identifiers(adr_md: str) -> list[dict]:
    """Parse the 'Key Identifiers' markdown table.

    Supports both the 3-column (name|kind|file) and 4-column
    (name|kind|file|signature_or_attrs) formats. Older ADRs use 3-col; ADRs
    produced after 2026-04-19 use 4-col with signatures/attrs.

    Handles escaped pipes (`\\|`) inside signature cells so type unions like
    `bool \\| None` or `Parameter \\| None` don't fake extra columns.
    """
    m = re.search(r"##\s*Key Identifiers\s*\n(.*?)(?=\n##|\Z)", adr_md, re.DOTALL)
    if not m:
        return []
    rows = []
    for line in m.group(1).splitlines():
        if "|" not in line:
            continue
        # Preserve escaped pipes during split, then restore.
        tmp = line.replace(r"\|", _ESCAPED_PIPE)
        parts = [p.strip().strip("`").replace(_ESCAPED_PIPE, "|")
                 for p in tmp.strip().strip("|").split("|")]
        if len(parts) < 3:
            continue
        if parts[0] in ("Name", "") or parts[0].startswith("-"):
            continue
        row = {"name": parts[0], "kind": parts[1], "file": parts[2]}
        if len(parts) >= 4 and parts[3]:
            row["signature_or_attrs"] = parts[3]
        rows.append(row)
    return rows


def _normalize_for_match(name: str) -> list[str]:
    """Return candidate transliterations of a symbol across language conventions."""
    cands = {name}
    cands.add(name.replace("-", "_"))
    cands.add(name.replace(".", "_").lstrip("_"))
    cands.add(name.upper())
    cands.add(name.lower())
    # PascalCase from kebab-case: "adr-init" -> "AdrInit"
    parts = re.split(r"[-_.]", name)
    if len(parts) > 1:
        cands.add("".join(p.capitalize() for p in parts if p))
    return [c for c in cands if c]


def verify_preservation(files: list[dict], required: list[str],
                        cross_language: bool = False) -> tuple[list[str], list[str]]:
    """Return (preserved, missing). In cross_language mode, accept transliterations."""
    all_content = "\n".join(f["content"] for f in files)
    preserved = []
    for n in required:
        candidates = _normalize_for_match(n) if cross_language else [n]
        if any(re.search(rf"\b{re.escape(c)}\b", all_content) for c in candidates):
            preserved.append(n)
    missing = [n for n in required if n not in preserved]
    return preserved, missing


def validate_python_syntax(files: list[dict]) -> list[dict]:
    """Return list of {path, lineno, msg, context} for each .py file with a syntax error."""
    errors = []
    for f in files:
        if not f["path"].endswith(".py"):
            continue
        try:
            ast.parse(f["content"])
        except SyntaxError as e:
            lines = f["content"].splitlines()
            ctx_start = max(0, (e.lineno or 1) - 3)
            ctx_end = min(len(lines), (e.lineno or 1) + 2)
            context = "\n".join(
                f"{i+1:4d}: {lines[i]}"
                for i in range(ctx_start, ctx_end)
            )
            errors.append({
                "path": f["path"],
                "lineno": e.lineno,
                "msg": e.msg,
                "context": context,
            })
    return errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adr", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--emit-tests", action="store_true",
                    help="Hint the model that tests are welcome")
    ap.add_argument("--target-language", default="Python",
                    help="Implementation language (default Python)")
    ap.add_argument("--cross-language", action="store_true",
                    help="Enable translation mode: accept transliterated identifier names")
    ap.add_argument("--max-tokens", type=int, default=8000,
                    help="Max output tokens (default 8000). Bump for larger sources; "
                         "Sonnet 4.5 supports up to 64000.")
    ap.add_argument("--temperature", type=float, default=0.0,
                    help="Sampling temperature (default 0.0, nearly deterministic). "
                         "Pass 1.0 to reproduce pre-2026-04-19 pipeline behavior.")
    ap.add_argument("--no-repair-syntax", action="store_true",
                    help="Skip the one-shot repair retry when the recomposed Python has syntax errors.")
    ap.add_argument("--target-python-version", default="3.9",
                    help="Target Python version for generated code (default 3.9). "
                         "Set to 3.10 or higher to permit PEP 604 union syntax "
                         "(`str | None`); 3.9 or lower forces typing.Optional / Union.")
    ap.add_argument("--provider", default="anthropic", choices=["anthropic", "openai"],
                    help="LLM provider (default anthropic). 'openai' uses the "
                         "OpenAI chat.completions + function-calling API.")
    ap.add_argument("--model", default=None,
                    help="Model name. Default: claude-sonnet-4-5 for anthropic, "
                         f"{DEFAULT_OPENAI_MODEL} for openai.")
    ap.add_argument("--domain", default="none",
                    choices=["none", "memory-safe", "framework-migration"],
                    help="Wedge-specific prompt rules that treat the domain "
                         "sections in the ADR (Ownership Decisions, API "
                         "Contract, etc.) as LOAD-BEARING. Should match the "
                         "--domain used at decompose time.")
    args = ap.parse_args()

    adr_md = Path(args.adr).read_text(encoding="utf-8", errors="replace")
    key_ids = extract_key_identifiers(adr_md)
    required = [k["name"] for k in key_ids]

    user = (
        f"# ADR to implement\n\n```markdown\n{adr_md}\n```\n\n"
        f"Required identifiers (from the Key Identifiers table): "
        f"{json.dumps(required)}\n\n"
        f"{'Emit tests alongside the implementation.' if args.emit_tests else 'Do not emit tests unless the ADR explicitly requires them.'}\n\n"
        "Call emit_code."
    )

    system = (SYSTEM_CROSS_LANGUAGE if args.cross_language
              else SYSTEM_SAME_LANGUAGE).format(target=args.target_language)

    # Domain-specific prompt addenda (2026-04-19 reframe). When the ADR carries
    # an "Ownership Decisions" / "API Contract" / etc. section, the recompose
    # must honor it byte-for-byte. See docs/markets/ for wedge context.
    if args.domain == "memory-safe":
        system += (
            "\n\nDOMAIN: memory-safe (C/C++ \u2192 Rust).\n"
            "When the ADR contains an 'Ownership Decisions' table, each row is "
            "LOAD-BEARING: the Rust output MUST use the exact ownership model "
            "listed (owned T / &T / &mut T / Arc<T> / RefCell<T>). Do not "
            "substitute a 'safer' or 'more idiomatic' choice that differs from "
            "the ADR decision.\n"
            "When the ADR contains a 'Retained `unsafe` Blocks' section, those "
            "and only those may remain `unsafe`. All other code must be safe "
            "Rust. Do not introduce new `unsafe` blocks beyond those listed.\n"
            "When the ADR contains 'Lifetime Annotations', use the specified "
            "lifetime names and bounds; do not invent new ones.\n"
        )
    elif args.domain == "framework-migration":
        system += (
            "\n\nDOMAIN: framework-migration.\n"
            "When the ADR contains an 'API Contract' table, every row is "
            "LOAD-BEARING: the target implementation MUST preserve the exact "
            "contract (route / function signature / event payload) byte-for-"
            "byte. Customer-facing API shape does not change across the "
            "migration even if internal structure does.\n"
            "When the ADR specifies 'State Management Model' and 'Routing "
            "Model', use the target approach listed; do not silently substitute "
            "a different framework idiom.\n"
            "When the ADR lists 'Dependency Upgrade Path' decisions, honor "
            "each 'upgrade', 'replace', or 'remove' decision; do not add new "
            "dependencies not listed.\n"
        )

    # When targeting Python <= 3.9, add an explicit compat note. Rationale: if the
    # source used PEP 604 union syntax (`str | None`), the model will carry it
    # into the recompose by default, which fails at import time on 3.9. This
    # surfaced as Issue E during the 2026-04-19 signature-schema experiment.
    if args.target_language.lower() == "python":
        try:
            major_s, minor_s = args.target_python_version.split(".")[:2]
            ver = (int(major_s), int(minor_s))
        except (ValueError, IndexError):
            ver = (3, 9)  # treat malformed version as conservative default
        if ver < (3, 10):
            system += (
                f"\n\nPYTHON VERSION TARGET: {args.target_python_version}. Do NOT "
                f"use PEP 604 union syntax (e.g. `str | None`, `int | float`) — "
                f"it is a SyntaxError before 3.10 at runtime. Use "
                f"`typing.Optional[X]` or `typing.Union[X, Y]` instead. Do not "
                f"emit `from __future__ import annotations` as a workaround — "
                f"runtime-evaluated annotations (dataclass field types, pydantic "
                f"models, typing.get_type_hints) still fail with it.\n"
                f"Also prefer `typing.List[T]`, `typing.Dict[K, V]`, `typing.Tuple[...]`, "
                f"`typing.Set[T]` instead of the builtin generics (`list[T]`, "
                f"`dict[K, V]`, ...) which only parse as types from 3.9+ and "
                f"only evaluate from 3.9+."
            )

    t0 = time.time()

    if args.provider == "openai":
        from openai import OpenAI
        _openai_client = OpenAI()
        _openai_model = args.model or DEFAULT_OPENAI_MODEL

    def _call_anthropic(messages):
        """Anthropic stream call with 4-attempt retry on transient disconnects."""
        client = anthropic.Anthropic()
        last_err = None
        for attempt in range(4):
            try:
                with client.messages.stream(
                    model=MODEL, max_tokens=args.max_tokens, system=system,
                    temperature=args.temperature,
                    tools=[CODE_TOOL], tool_choice={"type": "tool", "name": "emit_code"},
                    messages=messages,
                ) as stream:
                    resp = stream.get_final_message()
                tu = next((b for b in resp.content if b.type == "tool_use"), None)
                return {
                    "data": tu.input if tu else None,
                    "input_tokens": resp.usage.input_tokens,
                    "output_tokens": resp.usage.output_tokens,
                    "stop_reason": getattr(resp, "stop_reason", None),
                }
            except (anthropic.APIConnectionError, anthropic.APIStatusError,
                    httpx.ReadError, httpx.RemoteProtocolError, httpx.TimeoutException) as e:
                last_err = e
                print(f"  [attempt {attempt+1}/4] {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
                time.sleep(2 ** attempt)
        print(f"ERROR: all 4 attempts failed: {last_err}", file=sys.stderr)
        return None

    def _call_openai_rc(messages):
        """OpenAI chat.completions call. Reasoning models (o*, gpt-5*) reject
        temperature and need max_completion_tokens. OpenAI tool_use arguments
        are a JSON *string*, not a dict."""
        openai_tool = {
            "type": "function",
            "function": {
                "name": CODE_TOOL["name"],
                "description": CODE_TOOL["description"],
                "parameters": CODE_TOOL["input_schema"],
            },
        }
        is_reasoning = _openai_model.lower().startswith(("o1", "o3", "o4", "gpt-5"))
        oai_messages = [{"role": "system", "content": system}] + messages
        kwargs = {
            "model": _openai_model,
            "messages": oai_messages,
            "tools": [openai_tool],
            "tool_choice": {"type": "function", "function": {"name": CODE_TOOL["name"]}},
        }
        if is_reasoning:
            kwargs["max_completion_tokens"] = max(args.max_tokens, 16000)
        else:
            kwargs["max_tokens"] = args.max_tokens
            kwargs["temperature"] = args.temperature
        try:
            resp = _openai_client.chat.completions.create(**kwargs)
        except Exception as e:
            print(f"ERROR (openai): {type(e).__name__}: {str(e)[:300]}", file=sys.stderr)
            return None
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

    def _call(messages):
        return (_call_openai_rc(messages) if args.provider == "openai"
                else _call_anthropic(messages))

    result = _call([{"role": "user", "content": user}])
    if result is None:
        return 4
    dt = time.time() - t0

    def _extract_files(call_result: dict) -> tuple[list[dict], object, str]:
        """Pull (files, tool_use_data, stop_reason) out of a normalized call result."""
        sr = call_result.get("stop_reason")
        d = call_result.get("data")
        if d is None:
            return [], None, sr
        raw = d.get("files", [])
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                raw = []
        out = []
        for entry in raw:
            if isinstance(entry, dict) and "path" in entry and "content" in entry:
                out.append(entry)
            elif isinstance(entry, str):
                try:
                    parsed = json.loads(entry)
                    if isinstance(parsed, dict) and "path" in parsed and "content" in parsed:
                        out.append(parsed)
                except json.JSONDecodeError:
                    pass
        return out, d, sr

    files, data, stop_reason = _extract_files(result)
    if not files:
        print(f"ERROR: no usable file entries (stop_reason={stop_reason}); see raw_tool_input.json", file=sys.stderr)
        out_dir = Path(args.output_dir); out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "raw_tool_input.json").write_text(
            json.dumps(data, indent=2, default=str) if data else "{}", encoding="utf-8")
        return 2 if data is None else 6
    if stop_reason == "max_tokens":
        print(f"WARNING: response hit max_tokens={args.max_tokens}; output likely truncated. "
              f"Re-run with --max-tokens={args.max_tokens * 2}.", file=sys.stderr)

    # Syntax repair: if any .py file fails to parse, ask the model to fix it once.
    syntax_errors = validate_python_syntax(files) if args.target_language.lower() == "python" else []
    repair_attempted = False
    repair_succeeded = None
    if syntax_errors and not args.no_repair_syntax:
        repair_attempted = True
        err_summary = "\n\n".join(
            f"File `{e['path']}` has a SyntaxError at line {e['lineno']}: {e['msg']}\n\n"
            f"Context:\n```\n{e['context']}\n```"
            for e in syntax_errors
        )
        repair_user = (
            f"# Earlier attempt (for context)\n"
            f"You previously emitted these files via emit_code. Some have Python syntax errors:\n\n"
            f"{err_summary}\n\n"
            f"# Task\n"
            f"Re-emit ALL files from the original ADR via emit_code, with the syntax errors fixed. "
            f"Preserve every Key Identifier. Do not rename anything. "
            f"The ADR is unchanged:\n\n```markdown\n{adr_md}\n```\n\n"
            f"Required identifiers: {json.dumps(required)}\n\nCall emit_code."
        )
        print(f"  [syntax-repair] {len(syntax_errors)} file(s) have syntax errors; retrying once", file=sys.stderr)
        result2 = _call([{"role": "user", "content": repair_user}])
        if result2 is not None:
            files2, data2, stop_reason2 = _extract_files(result2)
            errs2 = validate_python_syntax(files2) if files2 else [{"msg": "no files"}]
            if files2 and not errs2:
                files, data, stop_reason = files2, data2, stop_reason2
                result = result2  # use repaired response for token accounting
                repair_succeeded = True
                print("  [syntax-repair] clean on retry", file=sys.stderr)
            else:
                repair_succeeded = False
                print(f"  [syntax-repair] still broken after retry ({len(errs2)} errors); keeping original", file=sys.stderr)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "raw_tool_input.json").write_text(
        json.dumps(data, indent=2, default=str), encoding="utf-8")
    for f in files:
        p = out_dir / f["path"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f["content"], encoding="utf-8")

    preserved, missing = verify_preservation(files, required,
                                             cross_language=args.cross_language)

    model_used = (args.model if args.provider == "openai"
                  else MODEL) or (DEFAULT_OPENAI_MODEL if args.provider == "openai" else MODEL)
    meta = {
        "provider": args.provider,
        "model": model_used,
        "input_tokens": result["input_tokens"],
        "output_tokens": result["output_tokens"],
        "stop_reason": stop_reason,
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
        "wall_seconds": round(dt, 2),
        "files_emitted": [f["path"] for f in files],
        "total_loc": sum(f["content"].count("\n") + 1 for f in files),
        "required_identifiers": required,
        "preserved_identifiers": preserved,
        "missing_identifiers": missing,
        "preservation_rate": (len(preserved) / len(required)) if required else None,
        "syntax_repair": {
            "attempted": repair_attempted,
            "succeeded": repair_succeeded,
            "initial_errors": len(syntax_errors),
        } if args.target_language.lower() == "python" else None,
        "notes": data.get("notes", ""),
    }
    (out_dir / "recompose_meta.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))
    if missing:
        print(f"\nWARNING: {len(missing)} required identifier(s) MISSING from output:", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
    return 0 if not missing else 3  # soft fail on missing identifiers


if __name__ == "__main__":
    sys.exit(main())
