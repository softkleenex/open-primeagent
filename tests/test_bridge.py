"""HostBridge - verified standalone, with no kernel. One reason we chose a socket."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import uuid
from pathlib import Path

import pytest

from opa.bridge import HostBridge
from opa_runtime.client import host_request


@pytest.fixture
async def bridge(monkeypatch):
    # unix socket paths are capped at 104 bytes on macOS, so keep it short
    path = Path(tempfile.gettempdir()) / f"opa-t-{uuid.uuid4().hex[:8]}.sock"
    br = HostBridge(path)
    await br.serve()
    monkeypatch.setenv("OPA_HOST_SOCKET", str(path))
    yield br
    await br.close()


async def test_roundtrip(bridge):
    async def echo(payload):
        return {"echo": payload.get("value")}

    bridge.register("test.echo", echo)
    reply = await host_request("test.echo", {"value": "한글 ok"})
    assert reply == {"echo": "한글 ok"}


async def test_unknown_type_names_the_known_ones(bridge):
    bridge.register("test.a", lambda p: asyncio.sleep(0, {"ok": True}))
    with pytest.raises(RuntimeError, match="no handler registered.*known types: test.a"):
        await host_request("test.nope")


async def test_handler_exception_does_not_kill_the_bridge(bridge):
    async def boom(payload):
        raise ValueError("kaboom")

    async def fine(payload):
        return {"ok": True}

    bridge.register("test.boom", boom)
    bridge.register("test.fine", fine)

    with pytest.raises(RuntimeError, match="ValueError: kaboom"):
        await host_request("test.boom")
    # the bridge must still be alive
    assert await host_request("test.fine") == {"ok": True}


async def test_missing_socket_env_is_explained(monkeypatch):
    monkeypatch.delenv("OPA_HOST_SOCKET", raising=False)
    with pytest.raises(RuntimeError, match="OPA_HOST_SOCKET is unset"):
        await host_request("rlm.run")


async def test_socket_is_owner_only(bridge):
    """Another local user must not be able to push commands into the kernel."""
    mode = os.stat(bridge.socket_path).st_mode & 0o777
    assert mode == 0o600


async def test_malformed_request_gets_an_error_reply(bridge):
    reader, writer = await asyncio.open_unix_connection(str(bridge.socket_path))
    writer.write(b"{not json\n")
    await writer.drain()
    reply = json.loads(await reader.readline())
    writer.close()
    assert reply["status"] == "error"
    assert "invalid JSON" in reply["error"]


async def test_duplicate_registration_is_rejected(bridge):
    async def h(payload):
        return {}

    bridge.register("test.dup", h)
    with pytest.raises(ValueError, match="already registered"):
        bridge.register("test.dup", h)


async def test_handler_result_cannot_shadow_protocol_fields(bridge):
    """A handler returning 'status'/'error'/'id' must not break the protocol.

    It did break once: rlm.run's status="running" overwrote the protocol's
    status="ok" and killed the client. Hence the `result` envelope.
    """

    async def sneaky(payload):
        return {"status": "running", "error": "not really", "id": "999", "ok": True}

    bridge.register("test.sneaky", sneaky)
    reply = await host_request("test.sneaky")
    assert reply == {"status": "running", "error": "not really", "id": "999", "ok": True}

    reader, writer = await asyncio.open_unix_connection(str(bridge.socket_path))
    writer.write(json.dumps({"id": "1", "type": "test.sneaky"}).encode() + b"\n")
    await writer.drain()
    wire = json.loads(await reader.readline())
    writer.close()
    assert wire["status"] == "ok"
    assert wire["id"] == "1"
    assert wire["result"]["status"] == "running"


@pytest.mark.parametrize("size", [70_000, 500_000])
async def test_large_requests_and_replies_survive(bridge, size):
    """asyncio's StreamReader defaults to 64 KiB. Without raising it, large
    prompts and inboxes full of child reports simply break - and did."""

    async def big(payload):
        return {"blob": "y" * len(payload["blob"])}

    bridge.register(f"test.big{size}", big)
    reply = await host_request(f"test.big{size}", {"blob": "x" * size})
    assert len(reply["blob"]) == size
