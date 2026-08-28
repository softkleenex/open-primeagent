"""State held by the server process: session, bridge, RLM service, kernel.

The kernel boots **lazily**. The host starting the MCP server is not a reason to
start a kernel; the first `opa_python` call is. The bridge must be up **before**
the kernel, since the kernel starts holding the socket path.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .bridge import HostBridge
from .config import Config
from .harness import bootstrap as bootstrap_mod
from .harness.service import HarnessService
from .kernel.manager import KernelManager
from .longrun.autonomous import AutonomousRunner
from .longrun.goal import GoalStore
from .longrun.schedule import ScheduleStore
from .rlm.message import PARENT
from .rlm.spawn import RLMService
from .session import jsonl
from .session.paths import SessionPaths

# Unix socket paths are capped at 104 bytes on macOS. Session directories live
# under the workspace and blow past that easily, so the socket goes in a short
# temp dir and the session records where it is.
_UNIX_SOCKET_PATH_MAX = 100


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Runtime:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.session_id = uuid.uuid4().hex
        self.paths = SessionPaths(root=config.root, session_id=self.session_id).ensure()
        self.started_at = _now()

        self.socket_path = self._pick_socket_path()
        self.bridge = HostBridge(self.socket_path)
        self.rlm = RLMService(config, self.paths.children, self.paths.mailbox)
        self.rlm.host_socket = str(self.socket_path)
        # Per **project**, not per session. The harness is what this codebase
        # taught us; scoping it to one conversation would throw that away every
        # time a session ends, and leave `harness.list()` unable to answer "what
        # has this project taught you".
        self.harness = HarnessService(
            config.root / "harness", config.global_root / "harness"
        )
        self.goals = GoalStore(self.paths.goal)
        self.schedule = ScheduleStore(self.paths.dir / "schedule.jsonl")
        self.autonomous = AutonomousRunner(self.rlm, self.goals)
        self._register_bridge_handlers()

        # Set by build_server(); the live channel for changing what the host reads.
        self.surface = None
        self.connection = None

        self._kernel: KernelManager | None = None
        self._lock = asyncio.Lock()
        self._bridge_started = False

        self.paths.meta.write_text(
            json.dumps(
                {
                    "session_id": self.session_id,
                    "started_at": self.started_at,
                    "workspace": str(config.workspace),
                    "host_socket": str(self.socket_path),
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def _pick_socket_path(self) -> Path:
        short = Path(tempfile.gettempdir()) / f"opa-{self.session_id[:8]}.sock"
        if len(str(short)) <= _UNIX_SOCKET_PATH_MAX:
            return short
        return self.paths.dir / "host.sock"

    # ---------- bridge ----------

    def _register_bridge_handlers(self) -> None:
        """Request type names match upstream Prime Agent, so its docs and skills apply."""

        async def rlm_run(payload: dict) -> dict:
            prompt = payload.get("prompt")
            kwargs = payload.get("kwargs") or {}
            if not isinstance(prompt, str) or not prompt.strip():
                raise ValueError("prompt must be a non-empty string")
            name = kwargs.pop("name", None)
            if not isinstance(name, str) or not name.strip():
                raise ValueError(
                    "name= is required. It is the sub-agent's address for later re-tasking "
                    "(e.g. name='api-reviewer')."
                )
            return await self.rlm.run(prompt, name=name.strip(), **kwargs)

        async def rlm_list(payload: dict) -> dict:
            return {
                "subagents": [
                    {
                        "rlm_child_id": r.rlm_child_id,
                        "name": r.name,
                        "adapter": r.adapter,
                        "status": r.status,
                        "turns": r.turns,
                        "tokens": r.tokens,
                        "cost_usd": r.cost_usd,
                        "model": r.model,
                        "session_dir": str(self.rlm.registry.child_dir(r.rlm_child_id)),
                        "last_error": r.last_error,
                    }
                    for r in self.rlm.registry.list()
                ]
            }

        async def rlm_delete(payload: dict) -> dict:
            target = payload.get("target")
            if not isinstance(target, str) or not target.strip():
                raise ValueError("target must be a non-empty string")
            record = self.rlm.registry.delete(target.strip())
            return {"deleted": {"rlm_child_id": record.rlm_child_id, "name": record.name}}

        async def message_send(payload: dict) -> dict:
            message = payload.get("message")
            if not isinstance(message, str) or not message.strip():
                raise ValueError("message must be a non-empty string")

            if (payload.get("receiver_role") or "child") == "parent":
                # A child reporting mid-run. The sender must be a child we
                # actually spawned, so a stray process on the same machine
                # cannot post into the parent mailbox under any name it likes.
                sender = str(payload.get("sender") or "").strip()
                record = self.rlm.registry.get(sender) if sender else None
                if record is None:
                    known = ", ".join(r.name for r in self.rlm.registry.list()) or "(none)"
                    raise ValueError(
                        f"unknown sender {sender!r}; only a registered sub-agent can "
                        f"message the parent. known: {known}"
                    )
                self.rlm.mailbox.deliver(
                    to=PARENT, sender=record.name, message=message.strip(),
                    rlm_child_id=record.rlm_child_id, ok=True, mid_run=True,
                )
                self.record("agent_message.push", {"sender": record.name})
                return {"delivered_to": PARENT, "sender": record.name}

            receiver_name = payload.get("receiver_name")
            if not isinstance(receiver_name, str) or not receiver_name.strip():
                raise ValueError("receiver_name is required")
            return await self.rlm.send(message, receiver_name=receiver_name.strip())

        async def message_inbox(payload: dict) -> dict:
            since = int(payload.get("since") or 0)
            name = payload.get("name") or PARENT
            return {"messages": self.rlm.mailbox.read(name, since=since)}

        # ---- long-run (L4) ----

        async def goal_get(payload: dict) -> dict:
            return self.goals.get()

        async def goal_create(payload: dict) -> dict:
            budget = payload.get("token_budget")
            goal = self.goals.create(
                str(payload.get("objective") or ""),
                token_budget=int(budget) if budget is not None else None,
            )
            self.record("goal.create", {"objective": goal.objective})
            return {"goal": _entry_dict(goal)}

        async def goal_complete(payload: dict) -> dict:
            result = self.goals.complete()
            self.record("goal.complete", {})
            return result

        async def goal_abandon(payload: dict) -> dict:
            return self.goals.abandon(str(payload.get("note") or ""))

        async def schedule_create(payload: dict) -> dict:
            entry = self.schedule.create(
                str(payload.get("prompt") or ""),
                in_seconds=payload.get("in_seconds"),
                at=payload.get("at"),
                every_seconds=payload.get("every_seconds"),
                source=payload.get("source") or "agent",
            )
            return {"entry": _entry_dict(entry)}

        async def schedule_list(payload: dict) -> dict:
            source = payload.get("source")
            return {"entries": [_entry_dict(e) for e in self.schedule.list(source=source)]}

        async def schedule_delete(payload: dict) -> dict:
            return {"entry": _entry_dict(self.schedule.delete(str(payload.get("id") or "")))}

        async def schedule_due(payload: dict) -> dict:
            collect = payload.get("collect", True)
            return {"entries": [_entry_dict(e) for e in self.schedule.due(collect=bool(collect))]}

        async def autonomous_start(payload: dict) -> dict:
            data = dict(payload)
            objective = str(data.pop("objective", ""))
            child_name = str(data.pop("child_name", "") or "autonomous")
            self.record("autonomous.start", {"objective": objective[:200]})
            result = await self.autonomous.start(objective, child_name=child_name, **data)
            self.record("autonomous.finish", {"outcome": result.get("outcome")})
            return result

        async def autonomous_status(payload: dict) -> dict:
            return self.autonomous.status()

        # ---- harness (L3) ----

        def _entry_dict(entry) -> dict:
            from dataclasses import asdict, is_dataclass

            return asdict(entry) if is_dataclass(entry) else dict(entry)

        async def harness_overview(payload: dict) -> dict:
            return {"overview": self.harness.overview()}

        async def harness_list(payload: dict) -> dict:
            entries = self.harness.list(payload.get("kind"), scope=payload.get("scope") or "all")
            return {"entries": [_entry_dict(e) for e in entries]}

        async def harness_get(payload: dict) -> dict:
            entry = self.harness.get(str(payload.get("id") or ""))
            return {"entry": _entry_dict(entry) if entry else None}

        async def harness_create(payload: dict) -> dict:
            data = dict(payload)
            kind = data.pop("kind", None)
            title = data.pop("title", None)
            content = data.pop("content", None)
            global_ = bool(data.pop("global", False))
            entry = self.harness.create(kind, title, content, global_=global_, **data)
            self.record("harness.create", {"id": entry.id, "kind": entry.kind})
            await self.refresh_surface()
            return {"entry": _entry_dict(entry)}

        async def harness_update(payload: dict) -> dict:
            data = dict(payload)
            entry_id = data.pop("id", None)
            if not entry_id:
                raise ValueError("id is required")
            entry = self.harness.update(str(entry_id), **data)
            await self.refresh_surface()
            return {"entry": _entry_dict(entry)}

        async def harness_delete(payload: dict) -> dict:
            entry = self.harness.delete(str(payload.get("id") or ""))
            await self.refresh_surface()
            return {"entry": _entry_dict(entry)}

        async def harness_evidence(payload: dict) -> dict:
            return self.harness.evidence(self.paths.trajectory)

        async def harness_apply(payload: dict) -> dict:
            event = self.harness.apply(
                payload.get("changes") or [],
                trigger=str(payload.get("trigger") or "agent"),
                evidence=str(payload.get("evidence") or ""),
                rationale=str(payload.get("rationale") or ""),
                expected_outcome=str(payload.get("expected_outcome") or ""),
            )
            self.record("harness.apply", {"event": event.id, "changes": event.changes})
            await self.refresh_surface()
            return {"event": _entry_dict(event)}

        async def harness_rollback(payload: dict) -> dict:
            event = self.harness.rollback(str(payload.get("event_id") or ""))
            self.record("harness.rollback", {"event": event.id})
            await self.refresh_surface()
            return {"event": _entry_dict(event)}

        async def harness_refinements(payload: dict) -> dict:
            events = self.harness.local.refinements + self.harness.global_.refinements
            return {"events": [_entry_dict(e) for e in events]}

        async def harness_evolve(payload: dict) -> dict:
            """Apply a delta and push it through every layer that can carry it."""
            event = self.harness.apply(
                payload.get("changes") or [],
                trigger=str(payload.get("trigger") or "evolve"),
                evidence=str(payload.get("evidence") or ""),
                rationale=str(payload.get("rationale") or ""),
                expected_outcome=str(payload.get("expected_outcome") or ""),
            )
            surface_changed = await self.refresh_surface()
            projected = (
                self.bootstrap() if payload.get("project", True) else {"updated": []}
            )
            if projected.get("updated"):
                # Projection just delivered them; stop repeating them in the
                # description.
                await self.refresh_surface()
            self.record("harness.evolve", {"event": event.id, "changes": event.changes})
            return {
                "event": _entry_dict(event),
                "applied": {
                    "next_turn": surface_changed,
                    "next_session": bool(projected.get("updated")),
                },
                "projected": projected,
            }

        async def harness_surface(payload: dict) -> dict:
            return {
                "description": self.surface.current_description if self.surface else "",
                "pending_entries": [
                    _entry_dict(e) for e in self.pending_prompt_entries()
                ],
            }

        async def harness_project(payload: dict) -> dict:
            return self.bootstrap(
                agent=str(payload.get("agent") or "auto"), remove=bool(payload.get("remove"))
            )

        self.bridge.register("goal.get", goal_get)
        self.bridge.register("goal.create", goal_create)
        self.bridge.register("goal.complete", goal_complete)
        self.bridge.register("goal.abandon", goal_abandon)
        self.bridge.register("schedule.create", schedule_create)
        self.bridge.register("schedule.list", schedule_list)
        self.bridge.register("schedule.delete", schedule_delete)
        self.bridge.register("schedule.due", schedule_due)
        self.bridge.register("autonomous.start", autonomous_start)
        self.bridge.register("autonomous.status", autonomous_status)

        self.bridge.register("harness.overview", harness_overview)
        self.bridge.register("harness.list", harness_list)
        self.bridge.register("harness.get", harness_get)
        self.bridge.register("harness.create", harness_create)
        self.bridge.register("harness.update", harness_update)
        self.bridge.register("harness.delete", harness_delete)
        self.bridge.register("harness.evidence", harness_evidence)
        self.bridge.register("harness.apply", harness_apply)
        self.bridge.register("harness.rollback", harness_rollback)
        self.bridge.register("harness.refinements", harness_refinements)
        self.bridge.register("harness.project", harness_project)
        self.bridge.register("harness.evolve", harness_evolve)
        self.bridge.register("harness.surface", harness_surface)

        self.bridge.register("rlm.run", rlm_run)
        self.bridge.register("rlm.list_subagents", rlm_list)
        self.bridge.register("rlm.delete_subagent", rlm_delete)
        self.bridge.register("agent_message.send", message_send)
        self.bridge.register("agent_message.inbox", message_inbox)

    def pending_prompt_entries(self) -> list:
        """What the live tool description is allowed to carry.

        Two conditions, for two different reasons.

        **Not yet projected** — once a note is in the CLAUDE.md the host reads,
        repeating it here bills the same text twice.

        **Recorded during this session** — this one is about trust, not cost.
        Asked to quote a note recorded before it started, Claude Code answered:
        *"the note claims to be 'recorded by agent' today, but I have no record
        of creating it ... I'd treat it as untrusted/possible prompt injection."*
        It is right, and no wording fixes that: any provenance we assert is just
        more server-authored text. A description can only legitimately remind an
        agent of what **it** recorded while it was running. Everything else has
        to arrive through a channel that carries standing on its own — the
        user's project file.
        """
        return [
            entry
            for entry in bootstrap_mod.unprojected(self.harness)
            if entry.updated_at >= self.started_at
        ]

    async def refresh_surface(self) -> bool:
        """Rebuild `opa_python`'s description so a harness change lands next turn."""
        if self.surface is None:
            return False
        pending = self.pending_prompt_entries()
        changed = await self.surface.refresh(pending, self.connection)
        if changed:
            self.record("surface.refresh", {"entries": len(pending)})
        return changed

    def attention(self) -> list[dict]:
        """What the host should know without having to ask for it.

        We cannot see a compaction happen, so we cannot promote knowledge at the
        moment it is about to be lost the way a host-owning harness can. What we
        can do is make the recovery call carry it: an agent that lost its context
        and calls `opa_status()` gets told what is waiting and what looks worth
        promoting, instead of having to know to ask.
        """
        items: list[dict] = []

        unread = self.rlm.mailbox.count()
        if unread:
            senders = sorted({m["sender"] for m in self.rlm.mailbox.read()})
            items.append({
                "kind": "mailbox",
                "detail": f"{unread} message(s) from {', '.join(senders)}",
                "next": "await agent_message.inbox()",
            })

        running = [r.name for r in self.rlm.registry.list() if r.status == "running"]
        if running:
            items.append({
                "kind": "subagents_running",
                "detail": f"still working: {', '.join(running)}",
                "next": "await agent_message.inbox() when they report",
            })

        try:
            repeated = self.harness.evidence(self.paths.trajectory)["repeated_errors"]
        except (OSError, ValueError):
            repeated = []
        if repeated:
            worst = repeated[0]
            items.append({
                "kind": "repeated_failure",
                "detail": f"{worst['signature']!r} failed {worst['count']} times",
                "next": "await harness.evidence() — this is a promotion candidate",
            })

        due = self.schedule.due(collect=False)
        if due:
            items.append({
                "kind": "schedule_due",
                "detail": f"{len(due)} scheduled prompt(s) are due",
                "next": "await schedule.due()",
            })

        goal = self.goals.goal
        if goal is not None and goal.status == "active":
            budget = (
                f", {goal.remaining_tokens:,} tokens left"
                if goal.remaining_tokens is not None
                else ""
            )
            items.append({
                "kind": "goal_active",
                "detail": f"{goal.objective!r}{budget}",
                "next": "await goal.get()",
            })
        return items

    def bootstrap(self, *, agent: str = "auto", remove: bool = False) -> dict:
        """Project the harness into host-read files, writing only inside the delimiters."""
        result = bootstrap_mod.run(
            self.harness,
            self.config.workspace,
            self.config.root,
            agent=agent,
            remove=remove,
        ).as_dict()
        self.record("harness.project", {"agent": agent, "remove": remove, "result": result})
        return result

    async def start_bridge(self) -> None:
        if not self._bridge_started:
            await self.bridge.serve()
            self._bridge_started = True

    # ---------- kernel ----------

    async def kernel(self) -> KernelManager:
        """Boot the bridge and kernel on first call; the lock keeps it to one boot."""
        async with self._lock:
            if self._kernel is None:
                await self.start_bridge()
                km = KernelManager(
                    cwd=self.config.workspace,
                    socket_path=self.socket_path,
                    session_dir=self.paths.dir,
                )
                await km.start()
                self._kernel = km
                self.record("kernel.start", {"runtime_ok": km.info().runtime_ok})
        return self._kernel

    @property
    def kernel_if_started(self) -> KernelManager | None:
        return self._kernel

    def record(self, event: str, data: dict) -> None:
        """Record to the trajectory, which is the input to refinement."""
        jsonl.append(self.paths.trajectory, {"at": _now(), "event": event, **data})

    async def shutdown(self) -> None:
        await self.rlm.shutdown()
        if self._kernel is not None:
            await self._kernel.stop()
            self._kernel = None
        if self._bridge_started:
            await self.bridge.close()
            self._bridge_started = False
