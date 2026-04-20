"""One-shot baseline: the LLM-only control for the symmetric pipeline.

Purpose: isolate the architecture's contribution by removing it. Given the same
source file(s), ask the model to emit a Python reimplementation in a single
call — no decompose, no ADR, no Key Identifiers table, no signature schema,
no load-bearing rules. Just:

  System: "You are a faithful code transcriber."
  User:   "Here is the source. Emit a Python reimplementation."

The output goes through the same roundtrip_diff and parity harness as the
symmetric-pipeline runs, so the comparison is apples-to-apples at the
measurement layer.

Usage:
  python -m cli.pipeline.oneshot_baseline \\
    --input DIR --output-dir DIR [--glob '*.py'] [--source-language Python] \\
    [--target-language Python] [--provider anthropic|openai] [--model NAME] \\
    [--max-tokens 16000] [--temperature 0.0]
"""
import argparse
import ast
import json
import re
import sys
import time
from pathlib import Path

import anthropic

MODEL = "claude-sonnet-4-5"
DEFAULT_OPENAI_MODEL = "gpt-4.1"

CODE_TOOL = {
    "name": "emit_code",
    "description": (
        "Emit a faithful reimplementation of the given source. Preserve the "
        "public API surface (function names, class names, module-level "
        "constants). Do NOT add features the source does not have. "
        "Do NOT introduce abstractions the source does not have."
    ),
    "input_schema": {
        "type": "object",
        "required": ["files"],
        "properties": {
            "files": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["path", "content"],
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                },
            },
            "notes": {"type": "string"},
        },
    },
}

SYSTEM = """You are a faithful code transcriber. Given source files in one
language, you emit a reimplementation in the requested target language. Rules:

1. Preserve every public name (functions, classes, module-level constants) with
   its exact spelling and casing. If the source says `parse_specifier_for_install`,
   the output says `parse_specifier_for_install`.
2. Preserve function signatures exactly: argument names, order, defaults,
   annotations, return type.
3. Preserve class attributes exactly. If a class has a `yes_choices` class-level
   attribute, the reimplementation's class also has `yes_choices`.
4. Do NOT add features the source does not have.
5. Do NOT introduce abstractions (wrapper classes, config dataclasses) the
   source does not use.
6. Produce the MINIMUM file count needed. A single-module source → one file.
7. If the source is Python, target Python 3.9 unless told otherwise: use
   `typing.Optional[X]` / `typing.Union[X,Y]` / `typing.List[T]` / `typing.Dict`
   rather than PEP 604 (`X | None`) or builtin generics (`list[T]`).
8. Call emit_code with the result.
"""


def gather_sources(input_dir: Path, glob_pat: str) -> str:
    if glob_pat == "*":
        files = sorted(p for p in input_dir.iterdir()
                       if p.is_file() and p.stat().st_size > 0)
    else:
        files = sorted(p for p in input_dir.glob(glob_pat) if p.stat().st_size > 0)
    parts = []
    for p in files:
        body = p.read_text(encoding="utf-8", errors="replace")
        numbered = "\n".join(f"{i+1:4d}: {line}" for i, line in enumerate(body.splitlines()))
        parts.append(f"### {p.name}\n\n```\n{numbered}\n```")
    return "\n\n".join(parts)


def validate_python_syntax(files):
    errors = []
    for f in files:
        if not f["path"].endswith(".py"):
            continue
        try:
            ast.parse(f["content"])
        except SyntaxError as e:
            errors.append({"path": f["path"], "lineno": e.lineno, "msg": e.msg})
    return errors


def _call_anthropic(system, user, max_tokens, temperature):
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=MODEL, max_tokens=max_tokens, system=system, temperature=temperature,
        tools=[CODE_TOOL], tool_choice={"type": "tool", "name": "emit_code"},
        messages=[{"role": "user", "content": user}],
    )
    tu = next((b for b in resp.content if b.type == "tool_use"), None)
    return {
        "data": tu.input if tu else None,
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
    }


def _call_openai(system, user, max_tokens, temperature, model):
    from openai import OpenAI
    client = OpenAI()
    openai_tool = {
        "type": "function",
        "function": {
            "name": CODE_TOOL["name"],
            "description": CODE_TOOL["description"],
            "parameters": CODE_TOOL["input_schema"],
        },
    }
    is_reasoning = model.lower().startswith(("o1", "o3", "o4", "gpt-5"))
    kwargs = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "tools": [openai_tool],
        "tool_choice": {"type": "function", "function": {"name": CODE_TOOL["name"]}},
    }
    if is_reasoning:
        kwargs["max_completion_tokens"] = max(max_tokens, 16000)
    else:
        kwargs["max_tokens"] = max_tokens
        kwargs["temperature"] = temperature
    resp = client.chat.completions.create(**kwargs)
    call = (resp.choices[0].message.tool_calls or [None])[0]
    data = None
    if call and call.function and call.function.arguments:
        try:
            data = json.loads(call.function.arguments)
        except json.JSONDecodeError:
            pass
    return {
        "data": data,
        "input_tokens": resp.usage.prompt_tokens,
        "output_tokens": resp.usage.completion_tokens,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--glob", default="*.py")
    ap.add_argument("--source-language", default="Python")
    ap.add_argument("--target-language", default="Python")
    ap.add_argument("--max-tokens", type=int, default=16000)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--provider", default="anthropic", choices=["anthropic", "openai"])
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    input_dir = Path(args.input)
    sources = gather_sources(input_dir, args.glob)
    user = (
        f"# Source ({args.source_language})\n\n{sources}\n\n"
        f"# Task\n"
        f"Reimplement in {args.target_language}. Preserve every public name "
        f"and every function signature exactly. Emit code via emit_code."
    )

    t0 = time.time()
    if args.provider == "openai":
        model_name = args.model or DEFAULT_OPENAI_MODEL
        result = _call_openai(SYSTEM, user, args.max_tokens, args.temperature, model_name)
    else:
        model_name = MODEL
        result = _call_anthropic(SYSTEM, user, args.max_tokens, args.temperature)
    dt = time.time() - t0

    data = result["data"]
    if not data or not data.get("files"):
        print("ERROR: model did not return any files", file=sys.stderr)
        return 2

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    files = data["files"]
    for f in files:
        p = out_dir / f["path"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f["content"], encoding="utf-8")

    syntax_errors = (validate_python_syntax(files)
                     if args.target_language.lower() == "python" else [])

    meta = {
        "provider": args.provider,
        "model": model_name,
        "pipeline": "oneshot-baseline",
        "input_tokens": result["input_tokens"],
        "output_tokens": result["output_tokens"],
        "temperature": args.temperature,
        "wall_seconds": round(dt, 2),
        "files_emitted": [f["path"] for f in files],
        "total_loc": sum(f["content"].count("\n") + 1 for f in files),
        "syntax_errors": len(syntax_errors),
        "notes": data.get("notes", ""),
    }
    (out_dir / "oneshot_meta.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
