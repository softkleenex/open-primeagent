"""RLM service - contract verified with a fake adapter, no real CLI calls."""

from __future__ import annotations

import asyncio

import pytest

from opa.rlm import spawn as spawn_module
from opa.rlm.adapters.base import TurnRequest, TurnResult
from opa.rlm.spawn import RLMService


class FakeAdapter:
    """A fake backend that records its calls."""

    name = "fake"

    def __init__(self) -> None:
        self.calls: list[TurnRequest] = []
        self.reply = "done"
        self.ok = True

    def available(self) -> bool:
        return True

    def preassign_session_id(self) -> str | None:
        return "fake-session-1"

    async def run(self, request: TurnRequest) -> TurnResult:
        self.calls.append(request)
        await asyncio.sleep(0)
        return TurnResult(
            ok=self.ok,
            text=self.reply,
            session_id=request.session_id or "fake-session-1",
            tokens=10,
            cost_usd=0.001,
        )


@pytest.fixture
def service(config, monkeypatch):
    fake = FakeAdapter()
    monkeypatch.setitem(spawn_module.ADAPTERS, "fake", lambda: fake)
    svc = RLMService(config, config.root / "children", config.root / "mailbox")
    svc.config = config.__class__(**{**config.__dict__, "default_adapter": "fake"})
    svc.fake = fake
    return svc


async def drain(service):
    """Wait for the background child tasks to finish."""
    for _ in range(200):
        if not service._tasks:
            return
        await asyncio.gather(*list(service._tasks), return_exceptions=True)
    raise AssertionError("child tasks did not finish")


async def test_run_returns_immediately_with_a_handle(service):
    handle = await service.run("review the API", name="api-reviewer")
    assert handle["name"] == "api-reviewer"
    assert handle["status"] == "running"
    # we did not wait for a result; the adapter may still be running
    await drain(service)


async def test_result_lands_in_the_parent_mailbox(service):
    await service.run("review", name="api-reviewer")
    await drain(service)
    inbox = service.mailbox.read()
    assert len(inbox) == 1
    assert inbox[0]["sender"] == "api-reviewer"
    assert inbox[0]["message"] == "done"


async def test_send_resumes_instead_of_creating_a_new_session(service):
    """How "a child is not disposable" is implemented: resume=True continues one session."""
    await service.run("first", name="security")
    await drain(service)
    await service.send("now check the payment module", receiver_name="security")
    await drain(service)

    calls = service.fake.calls
    assert [c.resume for c in calls] == [False, True]
    assert calls[1].session_id == "fake-session-1"
    assert service.registry.get("security").turns == 2


async def test_send_to_unknown_child_lists_the_known_ones(service):
    await service.run("x", name="backend")
    await drain(service)
    with pytest.raises(KeyError, match="known: backend"):
        await service.send("hi", receiver_name="frontend")


async def test_duplicate_name_is_rejected(service):
    await service.run("x", name="dup")
    with pytest.raises(ValueError, match="Send it a message instead"):
        await service.run("y", name="dup")
    await drain(service)


async def test_usage_is_accumulated_across_turns(service):
    await service.run("a", name="acct")
    await drain(service)
    await service.send("b", receiver_name="acct")
    await drain(service)
    record = service.registry.get("acct")
    assert record.tokens == 20
    assert record.cost_usd == pytest.approx(0.002)


async def test_child_failure_is_reported_not_raised(service):
    service.fake.ok = False
    service.fake.reply = "boom"
    await service.run("x", name="flaky")
    await drain(service)
    assert service.registry.get("flaky").status == "error"
    assert service.mailbox.read()[0]["ok"] is False


async def test_cwd_cannot_escape_the_workspace(service):
    with pytest.raises(ValueError, match="outside the workspace"):
        await service.run("x", name="escape", cwd="/etc")


async def test_unknown_adapter_names_the_available_ones(service):
    with pytest.raises(ValueError, match="unknown adapter"):
        await service.run("x", name="y", adapter="nope")


async def test_registry_survives_a_restart(service, config):
    await service.run("x", name="persistent")
    await drain(service)
    revived = RLMService(config, config.root / "children", config.root / "mailbox")
    assert [r.name for r in revived.registry.list()] == ["persistent"]
    assert revived.registry.get("persistent").native_session_id == "fake-session-1"


class SerialFake(FakeAdapter):
    """An adapter that detects concurrent execution."""

    def __init__(self) -> None:
        super().__init__()
        self.live = 0
        self.max_live = 0

    async def run(self, request: TurnRequest) -> TurnResult:
        self.live += 1
        self.max_live = max(self.max_live, self.live)
        await asyncio.sleep(0.05)
        self.live -= 1
        return await super().run(request)


@pytest.fixture
def serial_service(config, monkeypatch):
    fake = SerialFake()
    monkeypatch.setitem(spawn_module.ADAPTERS, "fake", lambda: fake)
    svc = RLMService(config, config.root / "children", config.root / "mailbox")
    svc.config = config.__class__(**{**config.__dict__, "default_adapter": "fake"})
    svc.fake = fake
    return svc


async def test_turns_for_one_child_never_overlap(serial_service):
    """Concurrent resumes on one session id race over the session file and corrupt it."""
    await serial_service.run("first", name="worker")
    await drain(serial_service)
    await asyncio.gather(*[serial_service.send(f"m{i}", receiver_name="worker") for i in range(3)])
    await drain(serial_service)

    assert serial_service.fake.max_live == 1, "same child ran concurrent turns"
    assert serial_service.registry.get("worker").turns == 4


async def test_different_children_still_run_in_parallel(serial_service):
    """Serialization must be per child. Serializing everything would defeat RLM."""
    await asyncio.gather(*[serial_service.run("go", name=f"w{i}") for i in range(3)])
    await drain(serial_service)
    assert serial_service.fake.max_live == 3


async def test_deleting_a_running_child_does_not_kill_the_task(serial_service):
    await serial_service.run("x", name="doomed")
    await asyncio.sleep(0)
    serial_service.registry.delete("doomed")
    tasks = list(serial_service._tasks)
    await drain(serial_service)
    assert all(t.exception() is None for t in tasks if not t.cancelled())


async def test_unknown_kwarg_is_rejected_not_ignored(service):
    """If rlm(moodel='opus') passed silently, nobody would know the model never changed."""
    with pytest.raises(TypeError, match="unexpected argument.*moodel"):
        await service.run("p", name="typo", moodel="opus")


async def test_cwd_check_survives_symlinked_workspaces(config, tmp_path):
    """When the workspace path contains a symlink (macOS /tmp -> /private/tmp),
    resolving only one side rejects valid paths inside the workspace."""
    real = tmp_path / "real"
    (real / "sub").mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)

    linked_config = config.__class__(**{**config.__dict__, "workspace": link})
    svc = RLMService(linked_config, config.root / "children", config.root / "mailbox")

    assert svc._resolve_cwd("sub") == (real / "sub").resolve()
    with pytest.raises(ValueError, match="outside the workspace"):
        svc._resolve_cwd(str(tmp_path / "elsewhere"))
