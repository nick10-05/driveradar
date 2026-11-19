"""app.scripts.export_openapi: the frontend's API contract (no DB needed)."""

import json
from pathlib import Path

import pytest

from app.scripts.export_openapi import main, render_schema


def test_schema_lists_the_endpoints_the_frontend_uses() -> None:
    schema = json.loads(render_schema())
    for path in ("/auth/login", "/auth/register", "/auth/logout", "/me", "/me/profile"):
        assert path in schema["paths"]
    assert "/drives" in schema["paths"]
    assert "/branches" in schema["paths"]


def test_output_is_deterministic() -> None:
    # Otherwise the CI drift check would fail at random.
    assert render_schema() == render_schema()


def test_ignores_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # A developer's real (or broken) env must not change or break the export.
    monkeypatch.setenv("DATABASE_URL", "not a url")
    monkeypatch.setenv("ALLOWED_ORIGINS", "nope")
    assert "/me" in json.loads(render_schema())["paths"]


def test_writes_then_check_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "openapi.json"
    assert main([str(out)]) == 0
    assert out.read_text(encoding="utf-8") == render_schema()
    assert main([str(out), "--check"]) == 0


def test_check_fails_when_stale_or_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "openapi.json"
    assert main([str(out), "--check"]) == 1  # missing
    out.write_text("{}\n", encoding="utf-8")
    assert main([str(out), "--check"]) == 1  # stale
    assert "out of date" in capsys.readouterr().err
    assert out.read_text(encoding="utf-8") == "{}\n"  # --check never writes
