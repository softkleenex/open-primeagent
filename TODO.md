# TODO

> Working notes for continuity across sessions. Start here.

## Where things stand (2026-08-19)

**Phase 0 ✅ / Phase 1 ✅ / Phase 2 ✅ / Phase 3 ✅.**
L0–L3 all work. Verified against a real Claude Code child: `rlm()` returns a
handle without blocking, the result lands in the mailbox, the child survives a
parent kernel restart, and re-tasking it via `agent_message.send` gets an answer
that remembers the pre-restart turn. Harness CRUD, projection and rollback are
verified end to end through the kernel. 99 tests pass (plus 1 child test run
explicitly with `-m child`).

Settled decisions:

- Python + uv. One MCP server serves every host agent.
- Kernel ↔ host bridge: **Unix socket JSONL RPC**, results inside a `result`
  envelope (a flat merge let a handler key shadow a protocol key — it broke).
- Line limit 8 MB on both ends (asyncio's default is 64 KiB and silently breaks).
- Tool ceiling of 4 (`server.MAX_TOOLS`, enforced by a test). All four exist now.
- Kernel transport: IPC socket, TCP fallback when the path is too long.
- Child adapters: `claude-code` (default) and `codex`, both verified to resume.
- One turn at a time per child (`asyncio.Lock`); children still run in parallel.
- Children are deleted only when asked. Residency is the default.
- Harness never decides *what* to change — no MCP `sampling` from the host.

## Next — finish Phase 3, then Phase 4

1. **child → parent push**: a thin `opa-child` MCP entry point that talks to
   `$OPA_HOST_SOCKET` with `OPA_ROLE=child`, so a child can message the parent
   mid-run instead of only at the end. Needs `agent_message.send` to accept
   `receiver_role="parent"`.
2. `longrun/goal.py` — create / get / complete + budget accounting.
3. `longrun/heartbeat.py`, `schedule.py`.
4. `longrun/autonomous.py` — gate loop.

Phase 5 (evolution) depends on Phase 3 and is already scoped in
`docs/concepts/evolution.md`.

## To investigate

- [ ] **opencode** headless / resume interface (`opencode run`? how does it resume?)
- [ ] Recursion depth limit when opa is attached to a child via `--mcp-config`
- [ ] `global` scope conflicts when several projects share `~/.opa`

## Reference files

| path | why |
|---|---|
| `_ref/prime-agent/prime-agent-runtime/src/rlm/__init__.py` | the whole rlm API surface (348 lines) |
| `_ref/prime-agent/prime-agent-runtime/src/rlm/harness.py` | harness store schema (820 lines) |
| `_ref/prime-agent/packages/coding-agent/skills/` | upstream's 13 skills |
| `_ref/prime-agent/AGENTS.md` | what upstream tells its own agents |

## Incident log

### 2026-08-19 — code review turned up five defects (all reproduced, then fixed)

1. **The bridge broke at 64 KB.** `MAX_LINE_BYTES = 4MB` was dead code; asyncio's
   64 KiB `StreamReader` default was the real limit. A 70 KB request raised
   `RuntimeError`, 200 KB raised `BrokenPipeError`. Replies had the same ceiling,
   so an inbox holding a few child reports would blow up.
   → `limit=` passed to both `start_unix_server` and `open_unix_connection`.
2. **Concurrent resume on one child.** Three simultaneous messages spawned three
   CLI processes against the same session id (session-file race → context
   corruption). → per-child `asyncio.Lock`; messages queue instead of being
   dropped, and different children still run in parallel.
3. **Deleting a running child killed its task** with `KeyError`, and the parent
   received neither a result nor a failure. → `_safe_update` plus a `[dropped]`
   notice; exceptions are now retrieved in the done callback.
4. **Unknown arguments were silently ignored.** `rlm(prompt, name='x',
   moodel='opus')` passed and ran on the default model. → whitelist rejection.
5. **The cwd guard misfired on symlinks.** Only one side was resolved, so valid
   paths inside a symlinked workspace (`/tmp` on macOS) were rejected.
   → resolve both sides.

### 2026-08-19 — protocol key shadowing in the bridge

`rlm.run`'s `status: "running"` was merged flat into the reply and overwrote the
protocol's `status: "ok"`; the client died with `unexpected status: 'running'`.
Fixed by wrapping handler results in a `result` envelope. A reserved-word naming
rule would have broken again later, so this is enforced structurally.
`tests/test_bridge.py` guards the regression.

### 2026-08-19 — codex hung waiting on stdin

`codex exec ... --json` through a pipe sat at `Reading additional input from
stdin...` forever, because a non-TTY stdin is treated as extra input.
→ `stdin=DEVNULL` in the adapter; applied to the claude adapter for the same
reason. Separately, codex refuses to run outside a git repository without
`--skip-git-repo-check`.

### 2026-08-19 — IPC transport failed to boot the kernel

`AsyncKernelManager(transport="ipc", ip="")` timed out after 60s.
`jupyter_client` uses `ip` as the **socket path prefix** for IPC
(`<ip>-1` … `<ip>-5`), so an empty string cannot create sockets. Fixed by passing
a short temp-dir prefix, with a TCP fallback when macOS's 104-byte `sun_path`
limit would be exceeded.

### 2026-08-19 — non-ASCII titles collapsed onto one id

`slug()` stripped everything outside `[a-z0-9]`, so every Korean title became the
same fallback id and collided. Now keeps Unicode word characters.
