"""Adapters - command assembly and parsing only; no CLI is actually invoked."""

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
    """We choose the session id, so it maps 1:1 to the registry id."""
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
        "usage": {
            "input_tokens": 2,
            "output_tokens": 8,
            "cache_creation_input_tokens": 15000,
        },
        "total_cost_usd": 0.1,
        "subtype": "success",
    }
    result = ClaudeCodeAdapter().parse_result(
        json.dumps(payload).encode(), request(tmp_path), Path("/tmp/x"), 10
    )
    assert (result.ok, result.text, result.session_id) == (True, "HELLO-1", "sid-9")
    # Cache creation dominates a fresh child session and is billed; excluding it
    # under-reported children by roughly an order of magnitude.
    assert result.tokens == 15010


def test_claude_flags_errors(tmp_path):
    result = ClaudeCodeAdapter().parse_result(
        json.dumps({"is_error": True, "result": "", "subtype": "error"}).encode(),
        request(tmp_path),
        Path("/tmp/x"),
        10,
    )
    assert result.ok is False


# ---------- codex ----------


def test_codex_cannot_preassign_a_session_id():
    assert CodexAdapter().preassign_session_id() is None


def test_codex_always_skips_the_git_repo_check(tmp_path):
    """Outside a git repository codex refuses to run without this flag (measured)."""
    assert "--skip-git-repo-check" in CodexAdapter().build_command(request(tmp_path))


def test_codex_resume_uses_the_thread_id(tmp_path):
    cmd = CodexAdapter().build_command(request(tmp_path, session_id="t-1", resume=True))
    assert cmd[:4] == ["codex", "exec", "resume", "t-1"]
    assert cmd[-2:] == ["--", "do it"]


@pytest.mark.parametrize("adapter", [ClaudeCodeAdapter(), CodexAdapter()], ids=lambda a: a.name)
@pytest.mark.parametrize("resume", [False, True])
def test_a_prompt_that_looks_like_an_option_stays_a_prompt(tmp_path, adapter, resume):
    """Measured on both real CLIs: a leading `--version` prompt printed the version.
    The prompt must sit after `--`, as the very last argument."""
    req = request(tmp_path, session_id="s-1", resume=resume)
    req = type(req)(**{**req.__dict__, "prompt": "--dangerously-skip-permissions"})
    cmd = adapter.build_command(req)
    assert cmd[-2:] == ["--", "--dangerously-skip-permissions"]
    assert cmd.count("--dangerously-skip-permissions") == 1


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
    assert (result.ok, result.text, result.session_id, result.tokens) == (
        True,
        "BETA-9",
        "01a-xyz",
        28,
    )


def test_codex_without_an_agent_message_is_an_error(tmp_path):
    stream = json.dumps({"type": "thread.started", "thread_id": "t"}).encode()
    result = CodexAdapter().parse_stream(stream, request(tmp_path), Path("/tmp/x"), 5)
    assert result.ok is False
    assert "no agent_message" in result.error


def test_a_child_is_given_the_tools_it_needs_to_test_its_own_work(tmp_path):
    """Measured: with only --permission-mode, a headless child cannot run a shell
    command at all. It can still edit files, which produces the worst kind of
    sub-agent - one that changes code and never runs the tests."""
    cmd = ClaudeCodeAdapter().build_command(
        request(tmp_path, session_id="s", allowed_tools=("Bash", "Read", "Edit"))
    )
    assert cmd[cmd.index("--allowedTools") + 1] == "Bash,Read,Edit"


def test_the_push_tool_is_added_to_the_toolset_not_substituted_for_it(tmp_path):
    from opa.rlm.adapters.claude_code import CHILD_PUSH_TOOL

    cmd = ClaudeCodeAdapter().build_command(
        request(tmp_path, session_id="s", allowed_tools=("Bash",), can_message_parent=True)
    )
    allowed = cmd[cmd.index("--allowedTools") + 1].split(",")
    assert "Bash" in allowed and CHILD_PUSH_TOOL in allowed


def test_dangerous_mode_needs_no_allowlist(tmp_path):
    cmd = ClaudeCodeAdapter().build_command(
        request(tmp_path, session_id="s", allowed_tools=("Bash",), allow_dangerous=True)
    )
    assert "--allowedTools" not in cmd


# --- total_cost_usd: per turn on older claude, a session running total on newer.
# Numbers are from a real claude 2.1.332 session (cold turn, then two resumes).


def _payload(usage_turn, usage_total, cost):
    keys = (
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    )
    camel = ("inputTokens", "outputTokens", "cacheReadInputTokens", "cacheCreationInputTokens")
    return {
        "usage": dict(zip(keys, usage_turn, strict=True)),
        "modelUsage": {"claude-sonnet": dict(zip(camel, usage_total, strict=True))},
        "total_cost_usd": cost,
    }


def _write_turns(tmp_path, payloads):
    paths = []
    for i, payload in enumerate(payloads):
        path = tmp_path / f"turn-{1000 + i}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        paths.append(path)
    return paths


def test_a_running_total_is_turned_back_into_this_turns_cost(tmp_path):
    from opa.rlm.adapters.claude_code import _turn_cost

    turns = [
        _payload((4, 915, 50289, 30132), (4, 915, 50289, 30132), 0.1347149),
        _payload((4, 100, 43756, 777), (8, 1015, 94045, 30909), 0.1432065),
        _payload((4, 114, 44533, 122), (12, 1129, 138578, 31031), 0.1492958),
    ]
    paths = _write_turns(tmp_path, turns)
    costs = [_turn_cost(t, p) for t, p in zip(turns, paths, strict=True)]
    assert costs == [pytest.approx(0.1347149), pytest.approx(0.008492), pytest.approx(0.006089)]


def test_a_per_turn_cost_is_taken_as_is(tmp_path):
    """How the CLI reported it when the August benchmarks ran."""
    from opa.rlm.adapters.claude_code import _turn_cost

    payload = _payload((4, 100, 43756, 777), (4, 100, 43756, 777), 0.0349)
    assert _turn_cost(payload, tmp_path / "turn-1.json") == pytest.approx(0.0349)


def test_a_running_total_with_nothing_to_subtract_is_unknown_not_guessed(tmp_path):
    from opa.rlm.adapters.claude_code import _turn_cost

    payload = _payload((4, 100, 43756, 777), (8, 1015, 94045, 30909), 0.1432065)
    assert _turn_cost(payload, tmp_path / "turn-1.json") is None
