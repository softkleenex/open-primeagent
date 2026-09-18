"""What the kernel sees when the host is unreachable, slow, or wrong.

These are the messages an agent actually reads when something breaks mid-session,
so they are worth asserting on rather than leaving to coverage. Every one of them
should name the request that failed: a bare parser error tells the caller nothing
about which call broke or which side misbehaved.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

import pytest

from opa_runtime import client
from opa_runtime.client import host_request


@pytest.fixture(autouse=True)
def _token():
    client.set_token("a-token")
    yield
    client.set_token(None)


@pytest.fixture
def sock_dir():
    """A short directory: AF_UNIX paths cap near 100 bytes.

    pytest's own tmp_path is far too long on macOS, which is the same limit
    `KernelManager` already works around when it picks a transport.
    """
    with tempfile.TemporaryDirectory(prefix="opa-", dir="/tmp") as name:
        yield Path(name)


async def _server(sock_dir, handler, name="host.sock"):
    path = sock_dir / name
    server = await asyncio.start_unix_server(handler, path=str(path))
    return server, path


@pytest.mark.parametrize(
    ("bad", "match"),
    [("", "non-empty"), (123, "non-empty")],
)
async def test_a_bad_request_type_is_refused_before_connecting(bad, match):
    with pytest.raises(TypeError, match=match):
        await host_request(bad)


async def test_a_non_dict_payload_is_refused():
    with pytest.raises(TypeError, match="payload must be a dict"):
        await host_request("rlm.run", ["not", "a", "dict"])


async def test_a_missing_socket_says_the_bridge_is_gone(sock_dir, monkeypatch):
    monkeypatch.setenv("OPA_HOST_SOCKET", str(sock_dir / "nothing-here.sock"))
    with pytest.raises(RuntimeError, match="socket is gone"):
        await host_request("rlm.run")


async def test_a_host_that_hangs_up_says_so_and_names_the_request(sock_dir, monkeypatch):
    async def hangup(reader, writer):
        writer.close()

    server, path = await _server(sock_dir, hangup)
    monkeypatch.setenv("OPA_HOST_SOCKET", str(path))
    try:
        with pytest.raises(RuntimeError, match="closed the connection without replying to rlm.run"):
            await host_request("rlm.run")
    finally:
        server.close()


async def test_a_silent_host_times_out_and_names_the_request(sock_dir, monkeypatch):
    async def silent(reader, writer):
        await asyncio.sleep(30)

    server, path = await _server(sock_dir, silent)
    monkeypatch.setenv("OPA_HOST_SOCKET", str(path))
    try:
        with pytest.raises(RuntimeError, match="rlm.run timed out"):
            await host_request("rlm.run", timeout=0.2)
    finally:
        server.close()


@pytest.mark.parametrize("body", [b"this is not json\n", b'{"status": "ok"\n'])
async def test_a_reply_that_is_not_json_names_the_request(sock_dir, monkeypatch, body):
    """It used to escape as `Expecting value: line 1 column 1` and nothing else."""

    async def garbage(reader, writer):
        await reader.readline()
        writer.write(body)
        await writer.drain()
        writer.close()

    server, path = await _server(sock_dir, garbage)
    monkeypatch.setenv("OPA_HOST_SOCKET", str(path))
    try:
        with pytest.raises(RuntimeError, match="reply to rlm.run that is not JSON"):
            await host_request("rlm.run")
    finally:
        server.close()


async def test_a_reply_that_is_not_an_object_names_the_request(sock_dir, monkeypatch):
    async def a_list(reader, writer):
        await reader.readline()
        writer.write(b'["not", "an", "object"]\n')
        await writer.drain()
        writer.close()

    server, path = await _server(sock_dir, a_list)
    monkeypatch.setenv("OPA_HOST_SOCKET", str(path))
    try:
        with pytest.raises(RuntimeError, match="not an object"):
            await host_request("rlm.run")
    finally:
        server.close()


async def test_an_unexpected_status_is_reported_verbatim(sock_dir, monkeypatch):
    async def odd(reader, writer):
        await reader.readline()
        writer.write(json.dumps({"status": "maybe"}).encode() + b"\n")
        await writer.drain()
        writer.close()

    server, path = await _server(sock_dir, odd)
    monkeypatch.setenv("OPA_HOST_SOCKET", str(path))
    try:
        with pytest.raises(RuntimeError, match="unexpected status: 'maybe'"):
            await host_request("rlm.run")
    finally:
        server.close()


async def test_a_handler_error_reaches_the_caller_intact(sock_dir, monkeypatch):
    async def failing(reader, writer):
        await reader.readline()
        writer.write(json.dumps({"status": "error", "error": "no such child"}).encode() + b"\n")
        await writer.drain()
        writer.close()

    server, path = await _server(sock_dir, failing)
    monkeypatch.setenv("OPA_HOST_SOCKET", str(path))
    try:
        with pytest.raises(RuntimeError, match="no such child"):
            await host_request("rlm.run")
    finally:
        server.close()
