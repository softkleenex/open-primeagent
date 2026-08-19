"""RLM 서비스 — `rlm.run` / `list_subagents` / `delete_subagent` / `agent_message`.

중요: **결과를 기다리지 않는다.** 원본과 동일하게 task가 admit된 시점에
핸들을 반환하고, child는 백그라운드에서 계속 돈다. 결과는 메일박스로 온다.
그래서 아래 두 줄이 순차 대기 없이 진짜로 병렬이다:

    api  = await rlm("...", name="api-reviewer")
    test = await rlm("...", name="test-reviewer")
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from ..config import Config
from .adapters.base import AgentAdapter, TurnRequest
from .adapters.claude_code import ClaudeCodeAdapter
from .adapters.codex import CodexAdapter
from .message import PARENT, Mailbox
from .registry import ChildRecord, ChildRegistry

ADAPTERS: dict[str, type] = {
    ClaudeCodeAdapter.name: ClaudeCodeAdapter,
    CodexAdapter.name: CodexAdapter,
}


class RLMService:
    def __init__(self, config: Config, children_dir: Path, mailbox_dir: Path) -> None:
        self.config = config
        self.registry = ChildRegistry(children_dir).load()
        self.mailbox = Mailbox(mailbox_dir)
        self._tasks: set[asyncio.Task] = set()
        self._adapters: dict[str, AgentAdapter] = {}

    # ---------- 어댑터 ----------

    def adapter(self, name: str | None) -> AgentAdapter:
        name = name or self.config.default_adapter
        if name not in ADAPTERS:
            raise ValueError(f"unknown adapter {name!r}. available: {', '.join(sorted(ADAPTERS))}")
        if name not in self._adapters:
            self._adapters[name] = ADAPTERS[name]()
        adapter = self._adapters[name]
        if not adapter.available():
            raise RuntimeError(
                f"adapter {name!r} is not usable: its CLI is not on PATH. "
                f"Install it, or pass adapter= one of {', '.join(sorted(ADAPTERS))}."
            )
        return adapter

    # ---------- rlm.run ----------

    async def run(self, prompt: str, name: str, **kwargs) -> dict:
        """child를 띄우고 **즉시** 핸들을 반환한다. 결과는 메일박스로 온다."""
        adapter = self.adapter(kwargs.get("adapter"))
        cwd = self._resolve_cwd(kwargs.get("cwd"))

        record = self.registry.add(
            ChildRecord.new(
                name=name,
                adapter=adapter.name,
                cwd=cwd,
                model=kwargs.get("model"),
                spec=kwargs.get("system_prompt"),
                native_session_id=adapter.preassign_session_id(),
            )
        )
        self._launch(record, prompt, adapter, resume=False)
        return {
            "rlm_child_id": record.rlm_child_id,
            "name": record.name,
            "adapter": record.adapter,
            "session_dir": str(self.registry.child_dir(record.rlm_child_id)),
            "model": record.model or "(adapter default)",
            "status": "running",
        }

    # ---------- agent_message ----------

    async def send(self, message: str, *, receiver_name: str, sender: str = PARENT) -> dict:
        """기존 child에게 후속 작업을 준다. child는 이전 컨텍스트를 유지한 채 이어서 일한다."""
        record = self.registry.get(receiver_name)
        if record is None:
            known = ", ".join(r.name for r in self.registry.list()) or "(none)"
            raise KeyError(f"no sub-agent named {receiver_name!r}. known: {known}")
        if record.native_session_id is None:
            raise RuntimeError(
                f"{record.name!r} has no session yet — its first turn has not finished. "
                f"Poll agent_message.inbox() or check opa_status first."
            )
        adapter = self.adapter(record.adapter)
        self.mailbox.deliver(
            to=record.name, sender=sender, message=message, rlm_child_id=record.rlm_child_id
        )
        self.registry.update(record.rlm_child_id, status="running")
        self._launch(record, message, adapter, resume=True)
        return {"delivered_to": record.name, "rlm_child_id": record.rlm_child_id}

    # ---------- 내부 ----------

    def _resolve_cwd(self, raw: str | None) -> Path:
        """child의 cwd는 workspace 밖으로 나가지 못한다 (docs/security.md)."""
        workspace = self.config.workspace
        if raw is None:
            return workspace
        candidate = (workspace / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
        if candidate != workspace and workspace not in candidate.parents:
            raise ValueError(f"cwd {candidate} is outside the workspace {workspace}")
        return candidate

    def _launch(self, record: ChildRecord, prompt: str, adapter: AgentAdapter, *, resume: bool) -> None:
        task = asyncio.create_task(self._run_turn(record, prompt, adapter, resume=resume))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run_turn(
        self, record: ChildRecord, prompt: str, adapter: AgentAdapter, *, resume: bool
    ) -> None:
        request = TurnRequest(
            prompt=prompt,
            cwd=Path(record.cwd),
            session_dir=self.registry.child_dir(record.rlm_child_id),
            session_id=record.native_session_id,
            resume=resume,
            model=record.model,
            system_prompt=record.spec,
            permission_mode=self.config.child_permission_mode,
            allow_dangerous=self.config.allow_dangerous_child,
        )
        try:
            result = await adapter.run(request)
        except Exception as exc:  # noqa: BLE001 — child 실패가 호스트를 죽이면 안 된다
            self.registry.update(
                record.rlm_child_id, status="error", last_error=f"{type(exc).__name__}: {exc}"
            )
            self.mailbox.deliver(
                to=PARENT, sender=record.name, message=f"[error] {type(exc).__name__}: {exc}",
                rlm_child_id=record.rlm_child_id, ok=False,
            )
            return

        self.registry.update(
            record.rlm_child_id,
            status="completed" if result.ok else "error",
            native_session_id=result.session_id or record.native_session_id,
            turns=record.turns + 1,
            tokens=record.tokens + (result.tokens or 0),
            cost_usd=round(record.cost_usd + (result.cost_usd or 0.0), 6),
            last_error=result.error,
        )
        self.registry.record_turn(
            record.rlm_child_id,
            {
                "prompt": prompt,
                "resume": resume,
                "ok": result.ok,
                "tokens": result.tokens,
                "cost_usd": result.cost_usd,
                "duration_ms": result.duration_ms,
                "raw": str(result.raw_path) if result.raw_path else None,
            },
        )
        self.mailbox.deliver(
            to=PARENT,
            sender=record.name,
            message=result.text or (result.error or "(empty response)"),
            rlm_child_id=record.rlm_child_id,
            ok=result.ok,
            tokens=result.tokens,
        )

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
