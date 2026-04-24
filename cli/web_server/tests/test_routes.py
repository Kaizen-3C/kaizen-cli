# SPDX-License-Identifier: Apache-2.0
"""Smoke tests for kaizen_web routes.

Uses FastAPI's TestClient so no actual server is started. The wedge routes
are covered in dry-run mode only — real LLM calls live in integration
tests elsewhere.
"""

from __future__ import annotations

from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from cli import __version__  # noqa: E402
from cli.web_server.server import create_app  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_version_matches_cli(client: TestClient) -> None:
    r = client.get("/api/version")
    assert r.status_code == 200
    assert r.json() == {"version": __version__, "name": "kaizen-cli"}


def test_providers_lists_all(client: TestClient) -> None:
    r = client.get("/api/providers")
    assert r.status_code == 200
    names = [p["name"] for p in r.json()["providers"]]
    assert set(names) == {"anthropic", "openai", "ollama", "litellm", "mixed"}


def test_status_on_empty_dir(tmp_path: Path, client: TestClient) -> None:
    r = client.get("/api/status", params={"path": str(tmp_path)})
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is False


def test_status_on_missing_dir(client: TestClient) -> None:
    r = client.get("/api/status", params={"path": "/definitely/does/not/exist/xyzzy"})
    assert r.status_code == 404


def test_runs_scans_case_studies(client: TestClient) -> None:
    case_dir = REPO_ROOT / "docs" / "case-studies"
    if not case_dir.is_dir():
        pytest.skip("repo layout missing docs/case-studies/")
    r = client.get("/api/runs", params={"path": str(case_dir), "limit": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    assert all(p["name"].endswith(".md") for p in body["artifacts"])


def test_adr_reads_markdown(tmp_path: Path, client: TestClient) -> None:
    fixture = tmp_path / "ADR-test.md"
    fixture.write_text("# ADR-0001\n\nhello world\n", encoding="utf-8")
    r = client.get("/api/adr", params={"path": str(fixture)})
    assert r.status_code == 200
    assert "hello world" in r.text
    assert r.headers["content-type"].startswith("text/markdown")


def test_adr_rejects_wrong_suffix(tmp_path: Path, client: TestClient) -> None:
    fixture = tmp_path / "notes.py"
    fixture.write_text("print('nope')", encoding="utf-8")
    r = client.get("/api/adr", params={"path": str(fixture)})
    assert r.status_code == 415


def test_priors_reset_requires_confirm(tmp_path: Path, client: TestClient) -> None:
    fixture = tmp_path / "priors.json"
    fixture.write_text("{}", encoding="utf-8")
    r = client.post("/api/priors/reset", json={"path": str(fixture), "confirm": False})
    assert r.status_code == 400
    assert fixture.exists()  # untouched


def test_priors_reset_deletes_with_confirm(tmp_path: Path, client: TestClient) -> None:
    fixture = tmp_path / "priors.json"
    fixture.write_text("{}", encoding="utf-8")
    r = client.post("/api/priors/reset", json={"path": str(fixture), "confirm": True})
    assert r.status_code == 200
    assert not fixture.exists()


def test_memsafe_dry_run(tmp_path: Path, client: TestClient) -> None:
    """Dry-run path — no LLM call, just exercises route plumbing."""
    # Create a minimal repo dir so the existence check passes.
    (tmp_path / "source.c").write_text("int main() { return 0; }\n", encoding="utf-8")
    r = client.post("/api/memsafe-roadmap", json={
        "repo": str(tmp_path),
        "dry_run": True,
        "plain": True,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["exit_code"] == 0


def test_memsafe_rejects_missing_repo(client: TestClient) -> None:
    r = client.post("/api/memsafe-roadmap", json={
        "repo": "/definitely/missing/xyzzy",
        "dry_run": True,
    })
    assert r.status_code == 400


def test_migrate_dry_run(tmp_path: Path, client: TestClient) -> None:
    (tmp_path / "app.py").write_text("print('py2 code')\n", encoding="utf-8")
    r = client.post("/api/migrate-plan", json={
        "repo": str(tmp_path),
        "from": "python2",
        "to": "python3",
        "dry_run": True,
        "plain": True,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["exit_code"] == 0


def test_decompose_dry_run(tmp_path: Path, client: TestClient) -> None:
    (tmp_path / "module.py").write_text("def f(): pass\n", encoding="utf-8")
    r = client.post("/api/decompose", json={
        "repo": str(tmp_path),
        "source_language": "Python",
        "dry_run": True,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["exit_code"] == 0


def test_decompose_rejects_missing_repo(client: TestClient) -> None:
    r = client.post("/api/decompose", json={
        "repo": "/definitely/missing/xyzzy",
        "dry_run": True,
    })
    assert r.status_code == 400


def test_decompose_rejects_bad_domain(tmp_path: Path, client: TestClient) -> None:
    """Pydantic Literal enforcement for domain field."""
    (tmp_path / "module.py").write_text("x=1\n", encoding="utf-8")
    r = client.post("/api/decompose", json={
        "repo": str(tmp_path),
        "domain": "not-a-domain",
        "dry_run": True,
    })
    assert r.status_code == 422


def test_recompose_dry_run(tmp_path: Path, client: TestClient) -> None:
    adr = tmp_path / "adr.md"
    adr.write_text("# ADR\nstub content\n", encoding="utf-8")
    r = client.post("/api/recompose", json={
        "adr": str(adr),
        "output_dir": str(tmp_path / "out"),
        "target_language": "Python",
        "dry_run": True,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["exit_code"] == 0


def test_recompose_rejects_missing_adr(client: TestClient) -> None:
    r = client.post("/api/recompose", json={
        "adr": "/definitely/missing/adr.md",
        "dry_run": True,
    })
    assert r.status_code == 400
