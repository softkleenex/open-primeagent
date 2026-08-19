"""어댑터 — CLI를 실제로 부르지 않고 커맨드 조립과 파싱만 검증한다."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opa.rlm.adapters.base import TurnRequest
from opa.rlm.adapters.claude_code import ClaudeCodeAdapter
from opa.rlm.adapters.codex import CodexAdapter


def request(tmp_path, **kw):
    return TurnRequest(prompt="do it", cwd=tmp_path, session_dir=tmp_path, **kw)


# ---------- claude ----------

def test_claude_preassigns_a_uuid():
    """세션 id를 우리가 정할 수 있어 registry id와 1:1로 묶인다."""
    sid = ClaudeCodeAdapter().preassign_session_id()
    assert sid and len(sid) == 36


def test_claude_spawn_uses_session_id_and_resume_uses_resume(tmp_path):
    adapter = ClaudeCodeAdapter()
    spawn = adapter.build_command(request(tmp_path, session_id="abc"))
    assert "--session-id" in spawn and "--resume" not in spawn
    resume = adapter.build_command(request(tmp_path, session_id="abc", resume=True))
    assert resume[resume.index("--resume") + 1] == "abc"


def test_claude_defaults_to_a_conservative_permission_mode(tmp_path):
    cmd = ClaudeCodeAdapter().build_command(request(tmp_path, session_id="a"))
    assert "--dangerously-skip-permissions" not in cmd
    assert cmd[cmd.index("--permission-mode") + 1] == "acceptEdits"


def test_claude_dangerous_mode_is_opt_in(tmp_path):
    cmd = ClaudeCodeAdapter().build_command(request(tmp_path, session_id="a", allow_dangerous=True))
    assert "--dangerously-skip-permissions" in cmd
    assert "--permission-mode" not in cmd


def test_claude_parses_result_and_usage(tmp_path):
    payload = {
        "result": "HELLO-1",
        "session_id": "sid-9",
        "usage": {"input_tokens": 2, "output_tokens": 8},
        "total_cost_usd": 0.1,
        "subtype": "success",
    }
    result = ClaudeCodeAdapter().parse_result(
        json.dumps(payload).encode(), request(tmp_path), Path("/tmp/x"), 10
    )
    assert (result.ok, result.text, result.session_id, result.tokens) == (True, "HELLO-1", "sid-9", 10)


def test_claude_flags_errors(tmp_path):
    result = ClaudeCodeAdapter().parse_result(
        json.dumps({"is_error": True, "result": "", "subtype": "error"}).encode(),
        request(tmp_path), Path("/tmp/x"), 10,
    )
    assert result.ok is False


# ---------- codex ----------

def test_codex_cannot_preassign_a_session_id():
    assert CodexAdapter().preassign_session_id() is None


def test_codex_always_skips_the_git_repo_check(tmp_path):
    """git 저장소 밖에서는 이 플래그 없이 거부한다 (실측)."""
    assert "--skip-git-repo-check" in CodexAdapter().build_command(request(tmp_path))


def test_codex_resume_uses_the_thread_id(tmp_path):
    cmd = CodexAdapter().build_command(request(tmp_path, session_id="t-1", resume=True))
    assert cmd[:5] == ["codex", "exec", "resume", "t-1", "do it"]


def test_codex_resume_without_a_thread_id_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="without a thread id"):
        CodexAdapter().build_command(request(tmp_path, resume=True))


def test_codex_defaults_to_a_sandbox(tmp_path):
    cmd = CodexAdapter().build_command(request(tmp_path))
    assert cmd[cmd.index("--sandbox") + 1] == "workspace-write"
    assert "--dangerously-bypass-approvals-and-sandbox" not in cmd


def test_codex_parses_thread_id_message_and_usage(tmp_path):
    stream = "\n".join(
        json.dumps(e)
        for e in [
            {"type": "thread.started", "thread_id": "01a-xyz"},
            {"type": "item.completed", "item": {"type": "reasoning", "text": "ignore me"}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "BETA-9"}},
            {"type": "turn.completed", "usage": {"input_tokens": 20, "output_tokens": 8}},
        ]
    ).encode()
    result = CodexAdapter().parse_stream(stream, request(tmp_path), Path("/tmp/x"), 5)
    assert (result.ok, result.text, result.session_id, result.tokens) == (True, "BETA-9", "01a-xyz", 28)


def test_codex_without_an_agent_message_is_an_error(tmp_path):
    stream = json.dumps({"type": "thread.started", "thread_id": "t"}).encode()
    result = CodexAdapter().parse_stream(stream, request(tmp_path), Path("/tmp/x"), 5)
    assert result.ok is False
    assert "no agent_message" in result.error
