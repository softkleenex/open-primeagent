# TODO

> Where things stand and what is next. Start here. The reasoning behind past
> decisions - benchmarks, dogfooding, incidents - is in
> [docs/journal.md](docs/journal.md).

## Where things stand (2026-11-25)

**Phases 0-4 ✅, Phase 5 core ✅.** L1-L5 work and are verified against a real
child agent. 375+ tests, ten-plus safety guards each proven defended by
`scripts/mutate_guards.py`, six benchmarks published including the ones we
lost. On PyPI as `open-primeagent`.

Settled decisions:

- Python + uv. One MCP server serves every host agent.
- Kernel ↔ host bridge: Unix socket JSONL RPC, results inside a `result`
  envelope, 8 MB line limit on both ends, per-caller tokens.
- Tool ceiling of 4, enforced by a test. All four exist.
- Child adapters: `claude-code` (default, continuously verified) and `codex`
  (verified once by hand). The prompt always goes last, after `--`.
- One turn at a time per child, one cell at a time per kernel; children still
  run in parallel.
- Harness never decides *what* to change — the host lends us no model.
- Projection edits only a whole-line-delimited block and refuses ambiguity.
- Measured value is concentrated in the harness and in warm child reuse;
  fan-out has no measured win, and the kernel's value is unmeasured.

## Next

1. **Phase 5 remainder**: candidate children carrying a variant harness plus a
   promotion gate, and the human-approval path through MCP `elicitation`.
2. **Claude Code plugin**: package the server and skills for `/plugin install`.
3. **The kernel benchmark that can actually measure it**: state that cannot be
   streamed out of a file (a loaded model, a live connection).

## Testing gaps worth closing

From a coverage audit (90% overall):

- [~] `opa_runtime` shim wrappers. `client.py` — the only path between kernel and
      host — went 85% to 97% by testing its failure messages rather than its
      coverage: a missing socket, a host that hangs up, one that never answers,
      one that replies with garbage. The remaining two lines are the ignored
      close on an already-broken connection. The thinner wrappers (harness,
      longrun, message) are still only exercised through the bridge.
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
      Now disclosed in the README rather than papered over (2026-09-08).
- [ ] The user's codex auth is currently expired (`token_expired` on every run),
      so codex-backed measurements are unreliable until they sign in again.
- [x] The push channel is wired into codex too, via `-c mcp_servers.*` overrides.
      It only works when the sandbox is bypassed — headless codex cancels MCP
      tool calls otherwise — so the adapter gates it behind dangerous mode.
- [x] Concurrency: two `opa_python` calls racing to boot the kernel. Tested
      2026-09-15 and the lock was already correct — 12 concurrent callers, one
      `start()`, one object handed to all of them. A failed boot is also not
      cached, so the slot stays retryable. No bug; a guarantee that was simply
      unverified.

## To investigate

- [ ] **opencode** headless / resume interface (`opencode run`? how does it resume?)
- [ ] Whether an instruction in the projected block would change the agent's
      choice of kernel over shell, and whether it *should*.

## Reference files

| path | why |
|---|---|
| `_ref/prime-agent/prime-agent-runtime/src/rlm/__init__.py` | the whole rlm API surface (348 lines) |
| `_ref/prime-agent/prime-agent-runtime/src/rlm/harness.py` | harness store schema (820 lines) |
| `_ref/prime-agent/packages/coding-agent/skills/` | upstream's 13 skills |
| `_ref/prime-agent/AGENTS.md` | what upstream tells its own agents |

