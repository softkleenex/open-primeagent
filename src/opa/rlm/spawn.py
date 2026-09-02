"""RLM service - `rlm.run` / `list_subagents` / `delete_subagent` / `agent_message`.

Important: **it does not wait for results.** Like upstream, it returns a handle
the moment the task is admitted and the child keeps running in the background;
results arrive in the mailbox. So these two lines really do run in parallel:

    api  = await rlm("...", name="api-reviewer")
    test = await rlm("...", name="test-reviewer")
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
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

# Arguments rlm(...) accepts. Unknown ones are **rejected, not silently dropped**.
# If `rlm(prompt, name="x", moodel="opus")` just passed, the run would continue on
# the default model with nobody aware the override never applied.
SPAWN_KWARGS = frozenset(
    {"adapter", "cwd", "model", "system_prompt", "can_message_parent"}
)


class RLMService:
    def __init__(self, config: Config, children_dir: Path, mailbox_dir: Path) -> None:
        self.config = config
        self.registry = ChildRegistry(children_dir).load()
        self.mailbox = Mailbox(mailbox_dir)
        self._tasks: set[asyncio.Task] = set()
        self._adapters: dict[str, AgentAdapter] = {}
        # One turn at a time per child. Two concurrent `--resume` calls on the same
        # session id race over the session file and corrupt its context. Messages
        # are queued, never dropped.
        self._turn_locks: dict[str, asyncio.Lock] = {}
        # Set by Runtime once the bridge is bound; a child needs it to answer back.
        self.host_socket: str | None = None
        # Mints a caller token per turn. Identity has to come from something the
        # child cannot choose, or one child can speak as another.
        #
        # The token is never persisted. child.json lives under `.opa/` inside the
        # workspace the children work in, and they have Read and Glob -- writing
        # the credential there would let any sibling read it and speak as its
        # owner, which is the exact impersonation this is meant to prevent.
        # Minting per turn and revoking afterwards keeps it in memory and short.
        self.issue_token: Callable[[str], str] | None = None
        self.revoke_token: Callable[[str], None] | None = None
        # Set by Runtime. Sub-agent activity used to leave no trace in the
        # trajectory at all, so the session record could not show that work had
        # been delegated -- and refinement reads that record.
        self.on_event: Callable[[str, dict], None] | None = None

    # ---------- adapters ----------

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
        """Spawn a child and return a handle **immediately**. Results go to the mailbox."""
        unknown = sorted(set(kwargs) - SPAWN_KWARGS)
        if unknown:
            raise TypeError(
                f"unexpected argument(s) {', '.join(unknown)}. "
                f"rlm() accepts: name, {', '.join(sorted(SPAWN_KWARGS))}"
            )
        adapter = self.adapter(kwargs.get("adapter"))
        cwd = self._resolve_cwd(kwargs.get("cwd"))

        record = self.registry.add(
            ChildRecord.new(
                name=name,
                adapter=adapter.name,
                cwd=cwd,
                model=kwargs.get("model"),
                spec=kwargs.get("system_prompt"),
                can_message_parent=bool(
                    kwargs.get("can_message_parent", self.config.child_can_message_parent)
                ),
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
        """Re-task an existing child. It continues with its earlier context intact."""
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

    # ---------- internals ----------

    def _resolve_cwd(self, raw: str | None) -> Path:
        """A child's cwd cannot escape the workspace (docs/security.md).

        Both sides are resolved before comparing. If the workspace path contains a
        symlink (macOS /tmp -> /private/tmp), resolving only one side rejects
        perfectly valid paths inside it.
        """
        workspace = self.config.workspace.resolve()
        if raw is None:
            return workspace
        raw_path = Path(raw)
        candidate = (raw_path if raw_path.is_absolute() else workspace / raw_path).resolve()
        if candidate != workspace and workspace not in candidate.parents:
            raise ValueError(f"cwd {candidate} is outside the workspace {workspace}")
        return candidate

    def _record(self, event: str, data: dict) -> None:
        if self.on_event is not None:
            self.on_event(event, data)

    def _launch(self, record: ChildRecord, prompt: str, adapter: AgentAdapter, *, resume: bool) -> None:
        task = asyncio.create_task(self._run_turn(record, prompt, adapter, resume=resume))
        self._tasks.add(task)
        task.add_done_callback(self._on_task_done)

    def _on_task_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if not task.cancelled():
            task.exception()  # unretrieved, it would vanish behind a "never retrieved" warning

    async def _run_turn(
        self, record: ChildRecord, prompt: str, adapter: AgentAdapter, *, resume: bool
    ) -> None:
        lock = self._turn_locks.setdefault(record.rlm_child_id, asyncio.Lock())
        async with lock:
            await self._run_turn_locked(record, prompt, adapter, resume=resume)

    async def _run_turn_locked(
        self, record: ChildRecord, prompt: str, adapter: AgentAdapter, *, resume: bool
    ) -> None:
        if self.registry.get(record.rlm_child_id) is None:
            # Deleted while queued. Do not fail silently; tell the parent.
            self.mailbox.deliver(
                to=PARENT, sender=record.name,
                message=f"[dropped] {record.name!r} was deleted before this turn ran",
                rlm_child_id=record.rlm_child_id, ok=False,
            )
            return
        turn_token = self.issue_token(record.name) if self.issue_token else None
        request = TurnRequest(
            prompt=prompt,
            cwd=Path(record.cwd),
            session_dir=self.registry.child_dir(record.rlm_child_id),
            session_id=record.native_session_id,
            resume=resume,
            model=record.model,
            system_prompt=record.spec,
            permission_mode=self.config.child_permission_mode,
            allowed_tools=self.config.child_allowed_tools,
            allow_dangerous=self.config.allow_dangerous_child,
            child_name=record.name,
            can_message_parent=record.can_message_parent,
            host_socket=self.host_socket,
            token=turn_token,
        )
        try:
            try:
                result = await adapter.run(request)
            finally:
                # The credential outlives nothing: once the turn is over the
                # token stops being accepted at all.
                if turn_token and self.revoke_token:
                    self.revoke_token(turn_token)
        except Exception as exc:  # noqa: BLE001 - a child failure must not kill the host
            self._safe_update(
                record.rlm_child_id, status="error", last_error=f"{type(exc).__name__}: {exc}"
            )
            self.mailbox.deliver(
                to=PARENT, sender=record.name, message=f"[error] {type(exc).__name__}: {exc}",
                rlm_child_id=record.rlm_child_id, ok=False,
            )
            return

        self._safe_update(
            record.rlm_child_id,
            status="completed" if result.ok else "error",
            native_session_id=result.session_id or record.native_session_id,
            turns=record.turns + 1,
            tokens=record.tokens + (result.tokens or 0),
            cost_usd=round(record.cost_usd + (result.cost_usd or 0.0), 6),
            last_error=result.error,
        )
        self._record(
            "rlm.turn",
            {
                "name": record.name,
                "resume": resume,
                "ok": result.ok,
                "turns": record.turns + 1,
                "tokens": result.tokens or 0,
                "prompt": prompt,
            },
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

    def _safe_update(self, rlm_child_id: str, **changes) -> None:
        """The child may be deleted mid-turn; the task must not die when it is."""
        if self.registry.get(rlm_child_id) is not None:
            self.registry.update(rlm_child_id, **changes)

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
