"""Red Team specialist review — auto-triggered when round-trip similarity < threshold.

Maps to ADR-0008's `specialist_avg` signal: an LLM-as-judge pass that reads the
derived ADR alongside the original source and flags factual errors, invented
features, and missing decisions. Severity-ranked findings so the top hits can
drive a repair pass.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import anthropic

MODEL = "claude-opus-4-5"

REVIEW_TOOL = {
    "name": "emit_review",
    "description": "Emit a structured specialist review of an ADR against its source.",
    "input_schema": {
        "type": "object",
        "required": ["findings", "overall_assessment", "recommended_action"],
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["severity", "category", "adr_claim", "source_reality", "impact"],
                    "properties": {
                        "severity": {"type": "string",
                                     "enum": ["critical", "high", "medium", "low"]},
                        "category": {"type": "string",
                                     "enum": ["invented_feature", "factual_error",
                                              "missing_decision", "misattribution",
                                              "scope_inflation", "prose_drift"]},
                        "adr_claim": {"type": "string",
                                      "description": "≤20 words: what the ADR says"},
                        "source_reality": {"type": "string",
                                           "description": "≤20 words: what the source actually shows"},
                        "impact": {"type": "string",
                                   "description": "≤25 words: why this finding matters"}
                    }
                }
            },
            "overall_assessment": {
                "type": "string",
                "description": "2-3 sentences: is this ADR fit to drive Recompose?"
            },
            "recommended_action": {
                "type": "string",
                "enum": ["accept", "revise_minor", "revise_major", "reject_regenerate"]
            }
        }
    }
}

SYSTEM = """You are a Red Team specialist reviewer. Your job is to find
factual errors, invented features, and missing decisions in an ADR by comparing
it against the source code the ADR was derived from. You MUST be adversarial:
assume the ADR is wrong until you verify each claim.

Rules:
- Severity 'critical' = claim has no basis in source (invented feature)
- Severity 'high' = claim misrepresents source (factual error, wrong quantity, wrong structure)
- Severity 'medium' = claim is partially true but omits important nuance
- Severity 'low' = claim is correct but stylistic/wording drift
- Quote ≤15 words from source or ADR per field
- Do not invent findings to pad the list — return an empty findings list if the ADR is clean.
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adr", required=True, help="Derived ADR file")
    ap.add_argument("--source-dir", required=True, help="Original source directory")
    ap.add_argument("--roundtrip-report", help="Optional roundtrip_diff.py JSON output")
    ap.add_argument("--output", required=True)
    ap.add_argument("--threshold", type=float, default=0.65,
                    help="Trigger only when roundtrip composite < threshold")
    ap.add_argument("--force", action="store_true",
                    help="Run even if roundtrip similarity is above threshold")
    ap.add_argument("--glob", default="*.py",
                    help="Source file glob (default *.py). Use '*' for extension-less files.")
    args = ap.parse_args()

    # Check trigger condition
    if args.roundtrip_report and not args.force:
        rt = json.loads(Path(args.roundtrip_report).read_text())
        sim = rt.get("composite_similarity", 0.0)
        if sim >= args.threshold:
            print(json.dumps({
                "triggered": False,
                "composite_similarity": sim,
                "threshold": args.threshold,
                "message": f"similarity {sim:.3f} >= threshold {args.threshold}; review skipped",
            }, indent=2))
            return 0

    adr_md = Path(args.adr).read_text(encoding="utf-8", errors="replace")
    src_dir = Path(args.source_dir)
    if args.glob == "*":
        src_files = sorted(p for p in src_dir.iterdir() if p.is_file())
    else:
        src_files = sorted(src_dir.glob(args.glob))
    src_bodies = "\n\n".join(
        f"=== FILE: {p.name} ===\n{p.read_text(encoding='utf-8', errors='replace')}"
        for p in src_files if p.stat().st_size > 0
    )

    user = (
        f"# Derived ADR under review\n\n```markdown\n{adr_md}\n```\n\n"
        f"# Original source\n\n```python\n{src_bodies}\n```\n\n"
        "Call emit_review with findings ranked by severity."
    )

    client = anthropic.Anthropic()
    t0 = time.time()
    resp = client.messages.create(
        model=MODEL, max_tokens=8000, system=SYSTEM,
        tools=[REVIEW_TOOL], tool_choice={"type": "tool", "name": "emit_review"},
        messages=[{"role": "user", "content": user}],
    )
    dt = time.time() - t0
    tool_use = next((b for b in resp.content if b.type == "tool_use"), None)
    if not tool_use:
        print("ERROR: model did not call emit_review", file=sys.stderr)
        return 2
    review = tool_use.input

    # Score the review by severity counts (a specialist_avg proxy)
    sev_weights = {"critical": 0.0, "high": 0.3, "medium": 0.6, "low": 0.9}
    findings = review.get("findings", []) or []
    if findings:
        specialist_score = sum(sev_weights.get(f["severity"], 0.5) for f in findings) / len(findings)
    else:
        specialist_score = 1.0

    out = {
        "triggered": True,
        "review": review,
        "specialist_score": round(specialist_score, 4),
        "n_findings": len(findings),
        "severity_counts": {s: sum(1 for f in findings if f["severity"] == s)
                            for s in ("critical", "high", "medium", "low")},
        "meta": {
            "model": MODEL,
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
            "wall_seconds": round(dt, 2),
        }
    }
    Path(args.output).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "review"}, indent=2))
    print("\n--- findings (preview) ---")
    for f in findings[:8]:
        print(f"  [{f['severity']:<8}] {f['category']:<18} | {f['adr_claim'][:70]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
