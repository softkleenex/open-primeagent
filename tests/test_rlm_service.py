"""RLM 서비스 — 가짜 어댑터로 실제 CLI 호출 없이 규약을 검증한다."""

from __future__ import annotations

import asyncio

import pytest

from opa.rlm import spawn as spawn_module
from opa.rlm.adapters.base import TurnRequest, TurnResult
from opa.rlm.spawn import RLMService


class FakeAdapter:
    """호출 기록을 남기는 가짜 백엔드."""

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
    """백그라운드 child 태스크가 끝날 때까지 기다린다."""
    for _ in range(200):
        if not service._tasks:
            return
        await asyncio.gather(*list(service._tasks), return_exceptions=True)
    raise AssertionError("child tasks did not finish")


async def test_run_returns_immediately_with_a_handle(service):
    handle = await service.run("review the API", name="api-reviewer")
    assert handle["name"] == "api-reviewer"
    assert handle["status"] == "running"
    # 결과를 기다리지 않았다 — 아직 어댑터가 끝나지 않았을 수 있다
    await drain(service)


async def test_result_lands_in_the_parent_mailbox(service):
    await service.run("review", name="api-reviewer")
    await drain(service)
    inbox = service.mailbox.read()
    assert len(inbox) == 1
    assert inbox[0]["sender"] == "api-reviewer"
    assert inbox[0]["message"] == "done"


async def test_send_resumes_instead_of_creating_a_new_session(service):
    """child가 일회용이 아니라는 것의 구현: resume=True 로 같은 세션을 이어간다."""
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
