"""The Claude Code plugin pins the server to its own release.

`uvx` caches the first version it resolves and never upgrades on its own, so
the plugin names an exact version. A release that bumps pyproject.toml but not
the plugin would keep installing the old server, silently.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _pyproject_version(path: Path) -> str:
    return tomllib.loads(path.read_text(encoding="utf-8"))["project"]["version"]


def test_every_version_in_the_repo_agrees():
    version = _pyproject_version(ROOT / "pyproject.toml")
    plugin = json.loads((ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    market = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
    (listed,) = [p for p in market["plugins"] if p["name"] == plugin["name"]]

    assert _pyproject_version(ROOT / "runtime/pyproject.toml") == version
    assert plugin["version"] == version
    assert listed["version"] == version
    assert plugin["mcpServers"]["opa"]["args"] == [f"open-primeagent@{version}"]

    # The MCP registry entry names the PyPI release it points at.
    server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    assert server["version"] == version
    assert [p["version"] for p in server["packages"]] == [version]


def test_the_registry_can_verify_we_own_the_pypi_package():
    """registry.modelcontextprotocol.io looks for `mcp-name: <name>` in the PyPI
    description, which is built from README.md. Without it, publishing fails."""
    server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"<!-- mcp-name: {server['name']} -->" in readme
    assert server["packages"][0]["identifier"] == "open-primeagent"


def test_the_plugin_ships_only_our_skills():
    skills = sorted(p.parent.name for p in (ROOT / "skills").glob("*/SKILL.md"))
    assert skills == ["goal", "refine", "rlm"]
