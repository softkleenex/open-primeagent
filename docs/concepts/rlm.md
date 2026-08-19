# RLM — sub-agents that are not disposable

The usual pattern is fan-out and forget:

```
manager
 ├─ agent A → done, gone
 ├─ agent B → done, gone
 └─ agent C → done, gone
```

What RLM is after:

```
manager
 ├─ backend specialist  ──┐
 ├─ frontend specialist ──┤  long-lived
 ├─ test specialist     ──┤
 └─ security specialist ──┘
            ↑
       re-tasked when needed
```

`rlm(...)` is not an LLM API call. Each call creates an **independent agent
session** with its own context, session directory and model — and that session
stays.

## It does not block

```python
api  = await rlm("audit the API layer", name="api-reviewer")
test = await rlm("map test coverage gaps", name="test-reviewer")
```

Both return in well under a second, with handles. The children keep working.
Results arrive in the parent mailbox:

```python
await agent_message.inbox()
# [{'sender': 'api-reviewer', 'message': '...', 'ok': True, 'tokens': 4211}, ...]
```

Collection is a **pull**. We do not own your host's turn loop, so we cannot wake
you — you collect on your next turn.

## It survives restarts

The registry is on disk, not in kernel memory. After a kernel restart, a context
compaction, or restarting the host entirely:

```python
await rlm.list_subagents()
# [<subagent 'api-reviewer' (claude-code) completed turns=1 tokens=4211>]
```

And re-tasking picks up the earlier context:

```python
await agent_message.send("re-check it now that I've fixed the code",
                         receiver_role="child", receiver_name="api-reviewer")
```

The child answers knowing what it said before. This is verified end to end in
`tests/test_rlm_integration.py` against a real child agent, across a parent
kernel restart.

**Look for an existing child before creating one.** An agent that already has
the area loaded is always a better target for follow-up than a fresh one, and
duplicate names are rejected with exactly that advice.

## How it can possibly work

We do not implement sessions. The host CLIs already have them:

| adapter | spawn | resume |
|---|---|---|
| `claude-code` | `claude -p P --session-id <UUID>` | `claude -p P --resume <UUID>` |
| `codex` | `codex exec P --json` | `codex exec resume <TID> P` |

Resume-by-session-id is the entire mechanism. It also means model choice is
delegated to the CLI, so mixed setups are free:

```python
await rlm("refactor this module", name="refactorer", adapter="codex")
```

## Rules that are enforced, not suggested

- **One turn at a time per child.** Two concurrent `--resume` calls on one
  session id race over the same session file and corrupt its context. Messages
  queue instead. Different children still run fully in parallel.
- **Nothing is reaped automatically.** `delete_subagent` runs only when you ask.
  Residency is the default; that is the point.
- **A child's `cwd` cannot escape the workspace.**
- **Unknown arguments raise.** `rlm(prompt, name="x", moodel="opus")` fails
  loudly rather than silently running on the default model.

## Not yet

Child → parent messaging currently happens when the child finishes: the adapter
captures its final output into the parent mailbox. Pushing *mid-run* requires
attaching the opa server to the child with `OPA_ROLE=child` — the reason the
host bridge is a socket rather than a Jupyter comm. See the
[roadmap](../roadmap.md).
