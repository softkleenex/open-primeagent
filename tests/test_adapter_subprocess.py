"""Adapter subprocess handling, driven by fake CLIs on PATH.

`build_command` and the parsers are covered in test_adapters.py. This covers the
part that actually spawns a process: exit codes, timeouts, raw-output capture,
and the stdin behaviour that cost us a hang when we first ran the real codex.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from opa.rlm.adapters.base import TurnRequest
from opa.rlm.adapters.claude_code import ClaudeCodeAdapter
from opa.rlm.adapters.codex import CodexAdapter


def fake_cli(directory: Path, name: str, script: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text("#!/usr/bin/env python3\n" + script, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture
def bin_dir(tmp_path, monkeypatch):
    directory = tmp_path / "bin"
    directory.mkdir()
    monkeypatch.setenv("PATH", f"{directory}{os.pathsep}{os.environ['PATH']}")
    return directory


def request(tmp_path, **kw):
    return TurnRequest(prompt="do it", cwd=tmp_path, session_dir=tmp_path / "child", **kw)


# ---------- claude ----------

async def test_claude_parses_a_successful_turn(bin_dir, tmp_path):
    payload = {
        "result": "ALL DONE",
        "session_id": "sid-1",
        "usage": {"input_tokens": 5, "output_tokens": 7,
                  "cache_creation_input_tokens": 100},
        "total_cost_usd": 0.02,
        "subtype": "success",
    }
    fake_cli(bin_dir, "claude", f"import json; print(json.dumps({payload!r}))\n")

    result = await ClaudeCodeAdapter().run(request(tmp_path, session_id="sid-1"))
    assert (result.ok, result.text, result.tokens) == (True, "ALL DONE", 112)
    assert result.cost_usd == 0.02
    assert result.raw_path.exists(), "the raw backend output must be kept"


async def test_claude_reports_a_crash_instead_of_pretending(bin_dir, tmp_path):
    fake_cli(bin_dir, "claude", "import sys; sys.stderr.write('boom\\n'); sys.exit(3)\n")
    result = await ClaudeCodeAdapter().run(request(tmp_path, session_id="s"))
    assert result.ok is False
    assert "boom" in result.error


async def test_claude_unparseable_output_is_surfaced(bin_dir, tmp_path):
    fake_cli(bin_dir, "claude", "print('not json at all')\n")
    result = await ClaudeCodeAdapter().run(request(tmp_path, session_id="s"))
    assert result.ok is False
    assert "could not parse" in result.error


async def test_claude_timeout_kills_the_child(bin_dir, tmp_path):
    fake_cli(bin_dir, "claude", "import time; time.sleep(30)\n")
    result = await ClaudeCodeAdapter().run(request(tmp_path, session_id="s", timeout=1))
    assert result.ok is False
    assert "timed out" in result.error


async def test_stdin_is_closed_for_the_child(bin_dir, tmp_path):
    """Left open as a pipe, a real CLI reads it as extra input; codex blocks forever."""
    fake_cli(
        bin_dir,
        "claude",
        "import json, sys\n"
        "data = sys.stdin.read()\n"
        "print(json.dumps({'result': f'stdin={data!r}', 'session_id': 's',\n"
        "                  'subtype': 'success', 'usage': {}}))\n",
    )
    result = await ClaudeCodeAdapter().run(request(tmp_path, session_id="s"))
    assert result.text == "stdin=''"


async def test_adapter_reports_when_the_cli_is_missing(bin_dir, monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert ClaudeCodeAdapter().available() is False
    assert CodexAdapter().available() is False


# ---------- codex ----------

async def test_codex_reads_the_thread_id_from_the_stream(bin_dir, tmp_path):
    events = [
        {"type": "thread.started", "thread_id": "01a-xyz"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "BETA-9"}},
        {"type": "turn.completed", "usage": {"input_tokens": 20, "output_tokens": 8}},
    ]
    body = "\n".join(f"print({json.dumps(json.dumps(e))})" for e in events) + "\n"
    fake_cli(bin_dir, "codex", body)

    result = await CodexAdapter().run(request(tmp_path))
    assert (result.ok, result.text, result.session_id, result.tokens) == (
        True, "BETA-9", "01a-xyz", 28,
    )


async def test_codex_without_an_agent_message_is_an_error(bin_dir, tmp_path):
    fake_cli(bin_dir, "codex", 'print(\'{"type": "thread.started", "thread_id": "t"}\')\n')
    result = await CodexAdapter().run(request(tmp_path))
    assert result.ok is False
    assert "no agent_message" in result.error


async def test_codex_garbage_lines_do_not_break_parsing(bin_dir, tmp_path):
    fake_cli(
        bin_dir,
        "codex",
        "print('warning: not json')\n"
        'print(\'{"type": "item.completed", "item": {"type": "agent_message", "text": "ok"}}\')\n',
    )
    result = await CodexAdapter().run(request(tmp_path))
    assert result.text == "ok"
