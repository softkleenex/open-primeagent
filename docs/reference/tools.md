# MCP tools

open-primeagent exposes exactly **four** tools, and `server.MAX_TOOLS = 4` with a
test enforcing the ceiling.

The reason is the thesis this project inherits: *give the model a computer, not
twenty tools.* Your host agent's tool list is a shared, finite resource — every
tool we add costs you schema tokens on every request and competes for the
model's attention with tools you actually chose. New capability is therefore
exposed as a [kernel symbol](kernel-api.md), never as another tool.

---

## `opa_python(code, timeout=120.0)`

Execute Python in the persistent IPython kernel. This is where almost all work
happens.

State survives across calls and across your own context compaction: variables,
imports, function definitions, open handles. The kernel boots lazily on the
first call.

Preloaded symbols: [`rlm`, `agent_message`, `harness`](kernel-api.md).

**Return value** is `[<status> · <ms>]` followed by stdout, the cell result, and
any traceback (ANSI stripped). If the combined text exceeds
`OPA_MAX_OUTPUT_CHARS` it is truncated **keeping head and tail** — the real
cause of a Python traceback is on the last line — and the full text is written
to `<session>/outputs/<n>.txt`, whose path appears in the truncation marker.

```python
opa_python("files = [p for p in Path('.').rglob('*.py')]")
opa_python("len(files)")                    # separate call, still there
opa_python("[f.name for f in files[:5]]")   # print only what you need
```

`timeout` is per cell. On expiry the cell is interrupted and the call returns a
`TimeoutError` line rather than hanging.

## `opa_status()`

Leads with **`attention`**: what is waiting for you and what looks worth
promoting, so an agent that lost its context does not have to know which
question to ask. Each item carries a `kind`, a `detail` and the `next` call to
make.

| kind | raised when |
|---|---|
| `mailbox` | sub-agents have reported and nobody has read it |
| `subagents_running` | children are still working |
| `repeated_failure` | the same cell has failed more than once — a promotion candidate |
| `schedule_due` | scheduled prompts have come due |
| `goal_active` | a goal is still being pursued, with its remaining budget |

Then the details: session id and directory, kernel liveness and restart count,
every sub-agent with status/turns/tokens/cost, goal, schedule counts, harness
entry counts.

This is the recovery call. A harness that owns its host can promote knowledge at
the moment a compaction is about to discard it; we cannot see a compaction
happen, so the recovery call carries that job instead.

Reading it consumes nothing — due items stay due, mail stays unread — and it does
**not** boot the kernel.

## `opa_kernel(action="info")`

| action | effect |
|---|---|
| `restart` | new kernel. Python variables are gone; sub-agents, harness and goal live on disk and survive |
| `interrupt` | interrupt a hung cell |
| `info` | pid, uptime, restart count, whether the `rlm` runtime loaded |

## `opa_bootstrap(agent="auto", remove=False)`

Project the harness into the files your host already reads.

| | |
|---|---|
| prompt entries | a delimiter block in `CLAUDE.md` / `AGENTS.md` |
| skills | `.claude/skills/<id>/SKILL.md`, marked `.opa-managed` |
| memory | `.opa/memory/*.md`; only an **index** enters the prompt block |

`agent="auto"` writes only to prompt files that **already exist** — creating
files you never had would itself be changing your environment. If none exist it
creates the single most portable one, `AGENTS.md`. Pass `claude-code`, `codex`
or `opencode` to target one explicitly.

Everything outside the delimiter block is preserved byte for byte, skill
directories without our marker are never touched, and `remove=True` restores
every file exactly. This is enforced by `tests/test_projection.py` and
`tests/test_bootstrap.py`, not by this document.
