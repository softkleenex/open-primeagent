"""서버 프로세스가 들고 있는 상태 — 세션, 브릿지, RLM 서비스, 커널.

커널은 **지연 부팅**한다. 호스트가 MCP 서버를 띄웠다는 이유만으로 커널을
올릴 필요는 없다. 첫 `opa_python` 호출에서 올린다.
브릿지는 커널보다 **먼저** 떠 있어야 한다 (커널이 소켓을 물고 시작하므로).
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
from .rlm.message import PARENT
from .rlm.spawn import RLMService
from .session import jsonl
from .session.paths import SessionPaths

# unix 소켓 경로는 macOS에서 104바이트 제한이 있다. 세션 디렉터리는 workspace
# 아래라 쉽게 넘어가므로, 소켓만 짧은 tempdir에 두고 경로를 세션에 기록한다.
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
        self.harness = HarnessService(
            self.paths.harness_state.parent, config.global_root / "harness"
        )
        self._register_bridge_handlers()

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
        """타입 이름은 원본 Prime Agent와 맞춘다 (문서/스킬 재사용)."""

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
            receiver_name = payload.get("receiver_name")
            if not isinstance(message, str) or not message.strip():
                raise ValueError("message must be a non-empty string")
            if not isinstance(receiver_name, str) or not receiver_name.strip():
                raise ValueError("receiver_name is required")
            return await self.rlm.send(message, receiver_name=receiver_name.strip())

        async def message_inbox(payload: dict) -> dict:
            since = int(payload.get("since") or 0)
            name = payload.get("name") or PARENT
            return {"messages": self.rlm.mailbox.read(name, since=since)}

        # ---- harness (L3) ----

        def _entry_dict(entry) -> dict:
            from dataclasses import asdict

            return asdict(entry)

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
            return {"entry": _entry_dict(entry)}

        async def harness_update(payload: dict) -> dict:
            data = dict(payload)
            entry_id = data.pop("id", None)
            if not entry_id:
                raise ValueError("id is required")
            return {"entry": _entry_dict(self.harness.update(str(entry_id), **data))}

        async def harness_delete(payload: dict) -> dict:
            return {"entry": _entry_dict(self.harness.delete(str(payload.get("id") or "")))}

        async def harness_evidence(payload: dict) -> dict:
            return self.harness.evidence(self.paths.trajectory)

        async def harness_apply(payload: dict) -> dict:
            event = self.harness.apply(
                payload.get("changes") or [],
                trigger=str(payload.get("trigger") or "agent"),
                evidence=str(payload.get("evidence") or ""),
            )
            self.record("harness.apply", {"event": event.id, "changes": event.changes})
            return {"event": _entry_dict(event)}

        async def harness_rollback(payload: dict) -> dict:
            event = self.harness.rollback(str(payload.get("event_id") or ""))
            self.record("harness.rollback", {"event": event.id})
            return {"event": _entry_dict(event)}

        async def harness_refinements(payload: dict) -> dict:
            events = self.harness.local.refinements + self.harness.global_.refinements
            return {"events": [_entry_dict(e) for e in events]}

        async def harness_project(payload: dict) -> dict:
            return self.bootstrap(
                agent=str(payload.get("agent") or "auto"), remove=bool(payload.get("remove"))
            )

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

        self.bridge.register("rlm.run", rlm_run)
        self.bridge.register("rlm.list_subagents", rlm_list)
        self.bridge.register("rlm.delete_subagent", rlm_delete)
        self.bridge.register("agent_message.send", message_send)
        self.bridge.register("agent_message.inbox", message_inbox)

    def bootstrap(self, *, agent: str = "auto", remove: bool = False) -> dict:
        """harness를 호스트가 읽는 파일로 투영한다. 델리미터 블록 안에만 쓴다."""
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
        """첫 호출에서 브릿지와 커널을 부팅한다. 동시 호출은 한 번만 부팅되게 잠근다."""
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
        """trajectory 기록. /refine의 입력이 된다."""
        jsonl.append(self.paths.trajectory, {"at": _now(), "event": event, **data})

    async def shutdown(self) -> None:
        await self.rlm.shutdown()
        if self._kernel is not None:
            await self._kernel.stop()
            self._kernel = None
        if self._bridge_started:
            await self.bridge.close()
            self._bridge_started = False
