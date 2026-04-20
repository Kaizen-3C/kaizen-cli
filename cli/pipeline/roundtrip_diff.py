"""Round-trip fidelity metric.

Given original source + reconstructed source (both directories of .py files),
compute a scalar similarity score in [0, 1]. Components:

  - identifier_jaccard   — overlap of class/function/constant names (AST-based)
  - file_count_ratio      — how close are the file counts (bounded [0,1])
  - loc_ratio             — how close are total line counts (bounded [0,1])
  - symbol_preservation   — what fraction of original key symbols appear in reconstruction

Composite: weighted sum with emphasis on identifier overlap (the most
information-dense signal). The ADR-0008 spirit is reused: weighted ground-truth.
"""
import argparse
import ast
import json
import sys
from pathlib import Path


def extract_symbols(py_file: Path) -> set[str]:
    """Return all top-level identifier names (classes, functions, constants)."""
    try:
        tree = ast.parse(py_file.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return set()
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    out.add(target.id)
    return out


def collect(dir_: Path) -> tuple[set[str], int, int]:
    """Return (all_symbols, file_count, total_lines) for a directory tree."""
    files = [p for p in dir_.rglob("*.py")
             if "__pycache__" not in str(p) and "test" not in p.name.lower()]
    syms: set[str] = set()
    total_lines = 0
    for f in files:
        syms |= extract_symbols(f)
        total_lines += f.read_text(encoding="utf-8", errors="replace").count("\n") + 1
    return syms, len(files), total_lines


def clamp_ratio(a: int, b: int) -> float:
    """min(a,b)/max(a,b) with defense against divide-by-zero. 1.0 = identical."""
    if a == 0 and b == 0:
        return 1.0
    if a == 0 or b == 0:
        return 0.0
    return min(a, b) / max(a, b)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--original", required=True, help="Original source dir")
    ap.add_argument("--reconstructed", required=True, help="Reconstructed source dir")
    ap.add_argument("--label", default="roundtrip", help="Label for output")
    ap.add_argument("--output", help="Optional JSON report path")
    args = ap.parse_args()

    orig_dir = Path(args.original)
    rec_dir = Path(args.reconstructed)

    orig_syms, orig_files, orig_loc = collect(orig_dir)
    rec_syms, rec_files, rec_loc = collect(rec_dir)

    # Component metrics
    intersection = orig_syms & rec_syms
    union = orig_syms | rec_syms
    identifier_jaccard = len(intersection) / len(union) if union else 0.0
    symbol_preservation = len(intersection) / len(orig_syms) if orig_syms else 0.0
    file_count_ratio = clamp_ratio(orig_files, rec_files)
    loc_ratio = clamp_ratio(orig_loc, rec_loc)

    # Composite — identifier-centric per ADR-0008 spirit
    # (test_pass got 0.30 as the strongest signal; identifier overlap gets the same here)
    weights = {
        "identifier_jaccard":   0.40,
        "symbol_preservation":  0.30,
        "loc_ratio":            0.20,
        "file_count_ratio":     0.10,
    }
    components = {
        "identifier_jaccard":   round(identifier_jaccard, 4),
        "symbol_preservation":  round(symbol_preservation, 4),
        "loc_ratio":            round(loc_ratio, 4),
        "file_count_ratio":     round(file_count_ratio, 4),
    }
    composite = sum(weights[k] * components[k] for k in weights)

    report = {
        "label": args.label,
        "original": str(orig_dir),
        "reconstructed": str(rec_dir),
        "orig_files": orig_files, "rec_files": rec_files,
        "orig_loc": orig_loc, "rec_loc": rec_loc,
        "orig_symbols_n": len(orig_syms),
        "rec_symbols_n": len(rec_syms),
        "symbols_preserved": sorted(intersection),
        "symbols_lost": sorted(orig_syms - rec_syms),
        "symbols_new": sorted(rec_syms - orig_syms),
        "components": components,
        "weights": weights,
        "composite_similarity": round(composite, 4),
    }

    print(json.dumps({k: v for k, v in report.items()
                      if k not in ("symbols_preserved", "symbols_lost", "symbols_new")},
                     indent=2))
    print(f"\nsymbols_preserved ({len(intersection)}): {sorted(intersection)}")
    print(f"symbols_lost     ({len(orig_syms - rec_syms)}): {sorted(orig_syms - rec_syms)[:20]}")
    print(f"symbols_new      ({len(rec_syms - orig_syms)}): {sorted(rec_syms - orig_syms)[:20]}")

    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
