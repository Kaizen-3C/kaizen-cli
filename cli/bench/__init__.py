# SPDX-License-Identifier: Apache-2.0
"""Vendored benchmark analysis scripts.

These are copied verbatim from `Kaizen-3C/benchmarks/commit0/baselines/`
to keep `kaizen bench` self-contained — no separate clone, no PyPI
dependency. Sync periodically via scripts/sync-bench-vendor.py
(forthcoming) when upstream changes.

Vendored modules:
- value_add_fingerprint: per-cell architectural weakness matrix
- compare_baselines: per-arch aggregate comparisons
- (more to add as they prove useful at the CLI surface)
"""
