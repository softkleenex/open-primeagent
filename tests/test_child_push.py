"""child -> parent messaging: the channel that lets a long child stop going dark."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opa.child_server import build_server
from opa.rlm.adapters.base import TurnRequest
from opa.rlm.adapters.claude_code import (
    CHILD_PUSH_TOOL,
    ClaudeCodeAdapter,
    write_child_mcp_config,
)
from opa.rlm.registry import ChildRecord
from opa.runtime_state import Runtime
from opa_runtime.client import host_request

# ---------- the child-side server ----------

async def test_the_child_server_exposes_exactly_one_tool():
    """A child must not be able to spawn grandchildren, so it gets no rlm."""
    tools = await build_server().list_tools()
    assert [t.name for t in tools] == ["opa_notify_parent"]


def test_child_config_never_attaches_the_full_server(tmp_path):
    config = json.loads(write_child_mcp_config(tmp_path).read_text(encoding="utf-8"))
    servers = config["mcpServers"]
    assert list(servers) == ["opa_child"]
    assert servers["opa_child"]["args"] == ["-m", "opa.child_server"]


# ---------- the adapter side ----------

def request(tmp_path, **kw):
    return TurnRequest(prompt="p", cwd=tmp_path, session_dir=tmp_path / "child", **kw)


def test_push_is_off_unless_asked_for(tmp_path):
    cmd = ClaudeCodeAdapter().build_command(request(tmp_path, session_id="s"))
    assert "--mcp-config" not in cmd


def test_push_attaches_the_server_and_allows_only_its_tool(tmp_path):
    cmd = ClaudeCodeAdapter().build_command(
        request(tmp_path, session_id="s", can_message_parent=True)
    )
    assert "--mcp-config" in cmd
    assert cmd[cmd.index("--allowedTools") + 1] == CHILD_PUSH_TOOL


def test_the_child_learns_its_own_name(tmp_path):
    env = ClaudeCodeAdapter()._env(request(tmp_path, child_name="api-reviewer"))
    assert env["OPA_CHILD_NAME"] == "api-reviewer"
    assert env["OPA_ROLE"] == "child"


# ---------- the bridge side ----------

@pytest.fixture
async def runtime(config, monkeypatch):
    rt = Runtime(config)
    await rt.start_bridge()
    monkeypatch.setenv("OPA_HOST_SOCKET", str(rt.socket_path))
    yield rt
    await rt.shutdown()


async def test_a_registered_child_can_push_to_the_parent(runtime):
    runtime.rlm.registry.add(
        ChildRecord.new("api-reviewer", "claude-code", Path(runtime.config.workspace))
    )
    reply = await host_request(
        "agent_message.send",
        {"message": "found a hardcoded key", "receiver_role": "parent",
         "sender": "api-reviewer"},
    )
    assert reply == {"delivered_to": "parent", "sender": "api-reviewer"}

    inbox = runtime.rlm.mailbox.read()
    assert inbox[0]["message"] == "found a hardcoded key"
    assert inbox[0]["mid_run"] is True      # tells a final answer from a progress note


async def test_an_unregistered_sender_is_refused(runtime):
    """The socket is 0600, but a name is still not proof of identity."""
    with pytest.raises(RuntimeError, match="unknown sender"):
        await host_request(
            "agent_message.send",
            {"message": "hi", "receiver_role": "parent", "sender": "not-a-child"},
        )
    assert runtime.rlm.mailbox.count() == 0


async def test_an_empty_sender_is_refused(runtime):
    with pytest.raises(RuntimeError, match="unknown sender"):
        await host_request(
            "agent_message.send", {"message": "hi", "receiver_role": "parent"}
        )


async def test_parent_to_child_still_works(runtime):
    """The new branch must not have broken the original direction."""
    with pytest.raises(RuntimeError, match="no sub-agent named"):
        await host_request(
            "agent_message.send", {"message": "hi", "receiver_name": "ghost"}
        )


def test_the_child_is_given_the_host_socket(tmp_path):
    """The socket lives on the kernel's environment, not the server's, so it has
    to be passed in explicitly. Without it a child simply cannot answer back."""
    env = ClaudeCodeAdapter()._env(request(tmp_path, host_socket="/tmp/opa-x.sock"))
    assert env["OPA_HOST_SOCKET"] == "/tmp/opa-x.sock"


async def test_the_service_hands_the_socket_to_the_adapter(config):
    from opa.runtime_state import Runtime

    runtime = Runtime(config)
    assert runtime.rlm.host_socket == str(runtime.socket_path)


def test_codex_attaches_the_child_server_through_config_overrides(tmp_path):
    """codex has no --mcp-config; servers are config keys and `-c` parses TOML."""
    from opa.rlm.adapters.codex import CodexAdapter

    cmd = CodexAdapter().build_command(
        request(tmp_path, can_message_parent=True, allow_dangerous=True)
    )
    overrides = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-c"]
    assert any(o.startswith("mcp_servers.opa_child.command=") for o in overrides)
    assert any("opa.child_server" in o for o in overrides)


def test_codex_leaves_the_server_off_by_default(tmp_path):
    from opa.rlm.adapters.codex import CodexAdapter

    assert "-c" not in CodexAdapter().build_command(request(tmp_path))


def test_codex_child_also_gets_the_socket(tmp_path):
    from opa.rlm.adapters.codex import CodexAdapter

    env = CodexAdapter()._env(request(tmp_path, child_name="c", host_socket="/tmp/s.sock"))
    assert env["OPA_HOST_SOCKET"] == "/tmp/s.sock"
    assert env["OPA_CHILD_NAME"] == "c"


def test_codex_does_not_attach_a_tool_that_would_always_be_cancelled(tmp_path):
    """Headless codex cancels MCP tool calls unless the sandbox is bypassed.
    Attaching the server anyway would bill schema tokens for a tool that fails."""
    from opa.rlm.adapters.codex import CodexAdapter

    sandboxed = request(tmp_path, can_message_parent=True)
    assert CodexAdapter.push_available(sandboxed) is False
    assert "-c" not in CodexAdapter().build_command(sandboxed)


def test_codex_attaches_it_when_the_sandbox_is_already_given_up(tmp_path):
    from opa.rlm.adapters.codex import CodexAdapter

    dangerous = request(tmp_path, can_message_parent=True, allow_dangerous=True)
    assert CodexAdapter.push_available(dangerous) is True
    assert "-c" in CodexAdapter().build_command(dangerous)


async def test_a_child_cannot_bury_the_mailbox(runtime):
    """The push channel is reachable by a prompt-injected child, so it is bounded.
    One child must not be able to bury what the others said."""
    from opa.rlm.message import MAX_PENDING_PER_SENDER

    runtime.rlm.registry.add(
        ChildRecord.new("noisy", "claude-code", Path(runtime.config.workspace))
    )
    for i in range(MAX_PENDING_PER_SENDER):
        await host_request(
            "agent_message.send",
            {"message": f"note {i}", "receiver_role": "parent", "sender": "noisy"},
        )
    with pytest.raises(RuntimeError, match="already has 20 unread"):
        await host_request(
            "agent_message.send",
            {"message": "one too many", "receiver_role": "parent", "sender": "noisy"},
        )


def test_an_enormous_message_is_truncated_not_dropped(tmp_path):
    from opa.rlm.message import MAX_MESSAGE_CHARS, Mailbox

    box = Mailbox(tmp_path / "mailbox")
    record = box.deliver(to="parent", sender="c", message="x" * 100_000)
    assert len(record["message"]) <= MAX_MESSAGE_CHARS + 80
    assert "truncated" in record["message"]
