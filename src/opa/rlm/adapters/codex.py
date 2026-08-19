"""Codex 어댑터.

    spawn :  codex exec <PROMPT> --json --skip-git-repo-check [-m MODEL]
    resume:  codex exec resume <THREAD_ID> <PROMPT> --json

claude와 달리 세션 id를 우리가 정할 수 없다 — 첫 실행의 `thread.started`
이벤트에서 파싱해 registry에 저장한다.

실측으로 확인한 제약 두 가지 (2026-08-19):
  1. **stdin을 닫아야 한다.** 파이프로 열려 있으면 codex가
     "Reading additional input from stdin..." 상태로 무한 대기한다.
  2. git 저장소 밖에서는 `--skip-git-repo-check` 없이는 거부한다.

JSONL 이벤트 스키마:
    {"type":"thread.started","thread_id":"..."}
    {"type":"item.completed","item":{"type":"agent_message","text":"..."}}
    {"type":"turn.completed","usage":{"input_tokens":N,"output_tokens":N,...}}
"""

from __future__ import annotations

import asyncio
import json
import shutil
import time

from .base import TurnRequest, TurnResult

CLI = "codex"

# 기본 샌드박스. workspace 밖 쓰기와 네트워크를 막는다 (docs/security.md).
DEFAULT_SANDBOX = "workspace-write"


class CodexAdapter:
    name = "codex"

    def available(self) -> bool:
        return shutil.which(CLI) is not None

    def preassign_session_id(self) -> str | None:
        return None  # codex가 발급한다

    def build_command(self, request: TurnRequest) -> list[str]:
        if request.resume:
            if not request.session_id:
                raise ValueError("cannot resume a codex session without a thread id")
            cmd = [CLI, "exec", "resume", request.session_id, request.prompt]
        else:
            cmd = [CLI, "exec", request.prompt]
        cmd += ["--json", "--skip-git-repo-check"]
        if request.model:
            cmd += ["-m", request.model]
        if request.allow_dangerous:
            cmd += ["--dangerously-bypass-approvals-and-sandbox"]
        else:
            cmd += ["--sandbox", DEFAULT_SANDBOX]
        return cmd

    async def run(self, request: TurnRequest) -> TurnResult:
        started = time.monotonic()
        cmd = self.build_command(request)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(request.cwd),
            # stdin을 반드시 닫는다 — 열려 있으면 codex가 stdin을 기다리며 멈춘다.
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=request.timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return TurnResult(
                ok=False,
                text="",
                session_id=request.session_id,
                error=f"child timed out after {request.timeout}s",
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        duration_ms = int((time.monotonic() - started) * 1000)
        raw_path = request.session_dir / f"turn-{int(time.time() * 1000)}.jsonl"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(stdout or b"")

        result = self.parse_stream(stdout, request, raw_path, duration_ms)
        if not result.text and proc.returncode != 0:
            return TurnResult(
                ok=False,
                text="",
                session_id=result.session_id,
                error=(stderr or b"").decode(errors="replace").strip()[:2000]
                or f"{CLI} exited with {proc.returncode}",
                raw_path=raw_path,
                duration_ms=duration_ms,
            )
        return result

    def parse_stream(self, stdout, request, raw_path, duration_ms) -> TurnResult:
        session_id = request.session_id
        text = ""
        tokens = None
        for line in (stdout or b"").decode(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = event.get("type")
            if kind == "thread.started":
                session_id = event.get("thread_id") or session_id
            elif kind == "item.completed":
                item = event.get("item") or {}
                if item.get("type") == "agent_message" and item.get("text"):
                    text = item["text"]  # 마지막 agent_message가 최종 응답
            elif kind == "turn.completed":
                usage = event.get("usage") or {}
                if usage:
                    tokens = int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
        return TurnResult(
            ok=bool(text),
            text=text,
            session_id=session_id,
            tokens=tokens,
            raw_path=raw_path,
            error=None if text else "codex produced no agent_message",
            duration_ms=duration_ms,
        )
