from __future__ import annotations

from pathlib import Path

import pytest

from opa.config import Config


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(
        root=tmp_path / ".opa",
        workspace=tmp_path,
        max_output_chars=300,
        default_adapter="claude-code",
        child_permission_mode="acceptEdits",
        allow_dangerous_child=False,
    )


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path, monkeypatch):
    monkeypatch.setenv("OPA_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("OPA_ROOT", str(tmp_path / ".opa"))
    monkeypatch.delenv("OPA_HOST_SOCKET", raising=False)
    yield
