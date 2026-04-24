# SPDX-License-Identifier: Apache-2.0
"""Tests for `kaizen bench` subcommand suite (cli.commands.bench)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from cli.commands.bench import (
    add_bench_parser,
    bench_command,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REAL_RESULTS = _REPO_ROOT / "benchmarks" / "commit0" / "results"


def _parse(argv: list[str]) -> argparse.Namespace:
    """Build a minimal top-level parser and parse *argv* through bench."""
    root = argparse.ArgumentParser()
    subs = root.add_subparsers(dest="command")
    add_bench_parser(subs)
    return root.parse_args(argv)


# ---------------------------------------------------------------------------
# 1. Subcommand registration / imports
# ---------------------------------------------------------------------------


class TestBenchSubcommandExists:
    def test_public_functions_importable(self) -> None:
        """add_bench_parser and bench_command must be importable and callable."""
        assert callable(add_bench_parser)
        assert callable(bench_command)

    def test_fingerprint_vendor_importable(self) -> None:
        """The vendored module must be importable without side-effects."""
        from cli.bench.value_add_fingerprint import main as fp_main  # noqa: F401

        assert callable(fp_main)

    def test_bench_package_init_importable(self) -> None:
        import cli.bench  # noqa: F401

    def test_parser_registers_bench(self) -> None:
        root = argparse.ArgumentParser()
        subs = root.add_subparsers(dest="command")
        p = add_bench_parser(subs)
        assert p is not None

    def test_fingerprint_flag_required(self) -> None:
        with pytest.raises(SystemExit):
            _parse(["bench", "fingerprint"])  # missing --results

    def test_compare_flags_required(self) -> None:
        with pytest.raises(SystemExit):
            _parse(["bench", "compare"])  # missing --a and --b

    def test_fingerprint_parses(self) -> None:
        ns = _parse(["bench", "fingerprint", "--results", "/tmp/results"])
        assert ns.bench_subcommand == "fingerprint"
        assert ns.results == "/tmp/results"

    def test_compare_parses(self) -> None:
        ns = _parse(["bench", "compare", "--a", "/tmp/a", "--b", "/tmp/b"])
        assert ns.bench_subcommand == "compare"
        assert ns.dir_a == "/tmp/a"
        assert ns.dir_b == "/tmp/b"

    def test_commit0_parses(self) -> None:
        ns = _parse(["bench", "commit0"])
        assert ns.bench_subcommand == "commit0"


# ---------------------------------------------------------------------------
# 2. fingerprint against real results
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _REAL_RESULTS.exists(),
    reason="benchmarks/commit0/results/ not present; skipping live fingerprint test",
)
class TestBenchFingerprintRealResults:
    def test_runs_exit_code_zero(self, capsys: pytest.CaptureFixture) -> None:
        ns = _parse(["bench", "fingerprint", "--results", str(_REAL_RESULTS)])
        rc = bench_command(ns)
        assert rc == 0

    def test_output_contains_value_add_header(self, capsys: pytest.CaptureFixture) -> None:
        ns = _parse(["bench", "fingerprint", "--results", str(_REAL_RESULTS)])
        bench_command(ns)
        captured = capsys.readouterr()
        assert "VALUE-ADD FINGERPRINT" in captured.out

    def test_output_contains_known_library(self, capsys: pytest.CaptureFixture) -> None:
        ns = _parse(["bench", "fingerprint", "--results", str(_REAL_RESULTS)])
        bench_command(ns)
        captured = capsys.readouterr()
        # At least one canonical library name must appear in the table
        known_libs = ["wcwidth", "cachetools", "chardet", "babel", "jinja"]
        assert any(lib in captured.out for lib in known_libs)

    def test_output_contains_weakness_signatures(self, capsys: pytest.CaptureFixture) -> None:
        ns = _parse(["bench", "fingerprint", "--results", str(_REAL_RESULTS)])
        bench_command(ns)
        captured = capsys.readouterr()
        assert "ARCHITECTURAL-WEAKNESS SIGNATURES" in captured.out

    def test_missing_results_dir_returns_nonzero(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist"
        ns = _parse(["bench", "fingerprint", "--results", str(missing)])
        rc = bench_command(ns)
        assert rc != 0


# ---------------------------------------------------------------------------
# 3. compare with dummy directories
# ---------------------------------------------------------------------------


def _make_aggregate(tmp_dir: Path, arch: str, model: str, libs: list[str]) -> None:
    """Write a minimal aggregate_lite_<arch>.json into *tmp_dir*."""
    per_lib = {}
    for lib in libs:
        per_lib[lib] = {
            "repo": lib,
            "model": model,
            "input_tokens": 10000,
            "output_tokens": 1000,
            "counts": {"passed": 10, "failed": 2, "errors": 0},
        }
    payload = {
        "model": model,
        "split": "lite",
        "completed": libs,
        "per_library": per_lib,
    }
    (tmp_dir / f"aggregate_lite_{arch}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


class TestBenchCompare:
    def test_compare_two_dirs_produces_table(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        dir_a = tmp_path / "dir_a"
        dir_b = tmp_path / "dir_b"
        dir_a.mkdir()
        dir_b.mkdir()

        _make_aggregate(dir_a, "single_shot_sonnet", "claude-sonnet-4-6",
                        ["wcwidth", "cachetools", "pyjwt"])
        _make_aggregate(dir_b, "kaizen_delta_anthropic", "claude-sonnet-4-6",
                        ["wcwidth", "cachetools", "pyjwt", "chardet"])

        ns = _parse(["bench", "compare", "--a", str(dir_a), "--b", str(dir_b)])
        rc = bench_command(ns)
        captured = capsys.readouterr()

        assert rc == 0
        assert "single_shot_sonnet" in captured.out
        assert "kaizen_delta_anthropic" in captured.out

    def test_compare_table_contains_pipe_separators(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        _make_aggregate(dir_a, "arch_x", "model-a", ["wcwidth"])
        _make_aggregate(dir_b, "arch_y", "model-b", ["wcwidth"])

        ns = _parse(["bench", "compare", "--a", str(dir_a), "--b", str(dir_b)])
        bench_command(ns)
        captured = capsys.readouterr()
        # Markdown table rows contain pipe characters
        table_lines = [ln for ln in captured.out.splitlines() if "|" in ln]
        assert len(table_lines) >= 2  # at least header + separator

    def test_compare_shows_both_architectures(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        _make_aggregate(dir_a, "reflexion_sonnet", "claude-sonnet-4-6", ["babel"])
        _make_aggregate(dir_b, "reflexion_openai", "gpt-4.1", ["babel"])

        ns = _parse(["bench", "compare", "--a", str(dir_a), "--b", str(dir_b)])
        bench_command(ns)
        captured = capsys.readouterr()
        assert "reflexion_sonnet" in captured.out
        assert "reflexion_openai" in captured.out

    def test_compare_missing_dir_a_returns_error(
        self, tmp_path: Path
    ) -> None:
        dir_b = tmp_path / "b"
        dir_b.mkdir()
        _make_aggregate(dir_b, "arch_y", "model-b", ["wcwidth"])

        ns = _parse(["bench", "compare", "--a", str(tmp_path / "missing"), "--b", str(dir_b)])
        rc = bench_command(ns)
        assert rc != 0

    def test_compare_empty_dirs_exits_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Two dirs with no aggregate files should still exit 0 (just warn)."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        ns = _parse(["bench", "compare", "--a", str(dir_a), "--b", str(dir_b)])
        rc = bench_command(ns)
        assert rc == 0


# ---------------------------------------------------------------------------
# 4. commit0 stub
# ---------------------------------------------------------------------------


class TestBenchCommit0Stub:
    def test_exit_code_zero(self, capsys: pytest.CaptureFixture) -> None:
        ns = _parse(["bench", "commit0"])
        rc = bench_command(ns)
        assert rc == 0

    def test_mentions_benchmarks_repo_url(self, capsys: pytest.CaptureFixture) -> None:
        ns = _parse(["bench", "commit0"])
        bench_command(ns)
        captured = capsys.readouterr()
        assert "github.com/Kaizen-3C/benchmarks" in captured.out

    def test_mentions_reproduction_steps(self, capsys: pytest.CaptureFixture) -> None:
        ns = _parse(["bench", "commit0"])
        bench_command(ns)
        captured = capsys.readouterr()
        assert "run_lite_kaizen_delta.py" in captured.out

    def test_mentions_fingerprint_and_compare(self, capsys: pytest.CaptureFixture) -> None:
        ns = _parse(["bench", "commit0"])
        bench_command(ns)
        captured = capsys.readouterr()
        assert "kaizen bench fingerprint" in captured.out
        assert "kaizen bench compare" in captured.out
