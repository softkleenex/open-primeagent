# TODO

> Working notes for continuity across sessions. Start here.

## Where things stand (2026-08-19)

**Phase 0 ✅ / 1 ✅ / 2 ✅ / 3 ✅.** L0–L3 all work, verified against a real
child agent. 138 tests, 90% coverage, benchmarks published (including two we
lost).

Settled decisions:

- Python + uv. One MCP server serves every host agent.
- Kernel ↔ host bridge: Unix socket JSONL RPC, results inside a `result`
  envelope, 8 MB line limit on both ends.
- Tool ceiling of 4, enforced by a test. All four exist.
- Kernel transport: IPC socket, TCP fallback when the path is too long.
- Child adapters: `claude-code` (default) and `codex`, both verified to resume.
- One turn at a time per child; children still run in parallel.
- Harness never decides *what* to change — the host lends us no model.
- Harness entry ids must equal their slug (path-traversal guard), and projection
  re-checks at the write.

## Next

Phases 0-4 are done. What is left:

1. **Phase 5 remainder**: candidate children carrying a variant harness plus a
   promotion gate, and the human-approval path through MCP `elicitation`. The
   core (`ToolSurface` + `harness.evolve()`) is done.
2. **Distribution**: publish to PyPI so `uvx open-primeagent` works, and a
   Claude Code plugin for the slash commands.

## What the benchmarks changed about our understanding

Measured value so far is concentrated in **the harness**, not in RLM:

| claim | measured |
|---|---|
| harness entry, knowledge expensive to rediscover | ✅ -34% turns, -35% cost, -57% wall clock |
| harness entry, knowledge one glance away | ❌ +26% turns |
| persistent kernel on shell-friendly work | ❌ +42% turns, +33% cost |
| sub-agent fan-out on a small codebase | ❌ +454% tokens, +777% cost |
| sub-agent fan-out on a 444-file codebase | ❌ +259% tokens, **+127% wall clock** |
| warm child re-tasking vs a cold child | ✅ -91% tokens, -81% cost |

Two mechanisms explain all of it:

1. **A child costs ~36k tokens of session startup.** Spawning is expensive,
   keeping one is nearly free. That is fan-out losing and reuse winning, from
   the same fact.
2. **A competent agent greps; it does not read.** On a 135k-token repository the
   single reviewer answered using 42k tokens. Fan-out is meant to relieve a
   context bottleneck that never forms, which is why scaling the codebase up did
   not rescue it.

So **fan-out has no measured case where it wins**, and reuse does. The registry
is where the value is, not the parallelism. That matches the project's own
thesis ("a child is not disposable") better than fan-out ever did.

Open question: should `rlm()` warn when it is about to spawn a second child for
work that looks small? The guidance currently lives only in the tool description
and docs, where a model may or may not weigh it.

## What building Phase 5 changed

A tool description can remind an agent of what **it** recorded while running; it
cannot give standing to anything else. Claude Code read our promoted rule back
verbatim and then declined to act on it, because it had no record of creating
the note. No wording fixes that — any provenance we assert is more
server-authored text.

So: the live surface carries an *index* of the current session's own notes, and
authority comes from the project file. **L1 reminds, L0 authorises.** That also
settled where the harness should live — per **project**, not per session, since
it is what the codebase taught us rather than what one conversation did.

## Testing gaps worth closing

From a coverage audit (90% overall):

- [ ] `opa_runtime` shim wrappers (53–83%) are only exercised through the bridge
      handlers, not directly. Low risk, but the `harness.*` wrappers have no
      direct test.
- [ ] `server.py` `main()` and the stdio path (67%) — only covered manually.
- [ ] No test runs across a **context compaction**, which is the case the
      persistent kernel exists for. Hard to trigger headlessly; worth trying with
      a long synthetic session.
- [x] Sub-agent benchmarks now exist (`bench/subagents.py`): fan-out measured,
      warm-vs-cold re-running.
- [ ] No benchmark on a codebase large enough that the parent *cannot* hold the
      material — the only case where fan-out should win. This is the missing
      experiment that would settle whether sub-agents earn their cost.
- [ ] `codex` has no `child`-marked integration test; only `claude` does.
- [ ] The push channel is only wired into the claude adapter; codex needs the
      same `--mcp-config` treatment.
- [ ] Concurrency: nothing tests two `opa_python` calls racing to boot the kernel,
      although `Runtime.kernel()` locks for exactly that.

## To investigate

- [ ] **opencode** headless / resume interface (`opencode run`? how does it resume?)
- [ ] `global` scope conflicts when several projects share `~/.opa`

## Reference files

| path | why |
|---|---|
| `_ref/prime-agent/prime-agent-runtime/src/rlm/__init__.py` | the whole rlm API surface (348 lines) |
| `_ref/prime-agent/prime-agent-runtime/src/rlm/harness.py` | harness store schema (820 lines) |
| `_ref/prime-agent/packages/coding-agent/skills/` | upstream's 13 skills |
| `_ref/prime-agent/AGENTS.md` | what upstream tells its own agents |

## Incident log

### 2026-08-19 — path traversal through harness entry ids

`harness.create(..., id="../../CLAUDE")` was accepted verbatim, and projection
turns ids into file names (`.opa/memory/<id>.md`, `.claude/skills/<id>/`). Proved
it wrote outside the memory directory. Reachable from any code running in the
kernel, which means reachable by prompt injection.
Fixed in two layers: ids must equal their slug (`validate_id`), and projection
resolves every path and refuses to leave its directory. `tests/test_security.py`
covers both.

Audited the same class of bug elsewhere and found it clean: mailbox names are
already sanitised, child directory names are generated (`opa-<hex>`), output
files are index-named, and session ids are uuid4.

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
