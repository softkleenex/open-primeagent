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

## When not to fan out

Spawning a child is **not** cheap. Every child is a full coding-agent session
that pays for its own system prompt and tool schemas before it reads a single
line of your code. We measured that startup at roughly **36,000 tokens per
child**.

To put that in scale: in [our benchmark](../../bench/README.md#0-sub-agent-fan-out--opa-loses-badly),
reviewing an entire 12-file service cost a plain agent 34k tokens. *One child
cost more than the whole job.* Fanning out to four specialists produced the same
findings for **8.8x the cost and 3.4x the wall clock**.

So the bar a fan-out has to clear:

> Hand work to a sub-agent only when that work would cost the parent more than
> ~36k tokens of its own context.

Practically, that means:

| don't | do |
|---|---|
| four reviewers on a small module | read it yourself |
| a child for something you could grep | grep it |
| a child per file | a child per *subsystem*, if any |
| fan out for speed | fan out because the material does not fit |

Parallelism does not rescue it either — four cold sessions still have to boot,
so the wall clock got worse, not better.

Where children earn their cost is **reuse**, and that is measured too. Asking a
follow-up of a child that had already read the file cost
[**81% less than spawning a fresh one**](../../bench/README.md#0b-warm-child-vs-cold-child--reuse-wins-by-5x)
for the same question — 1,987 tokens against 23,058.

Same fact, both directions: spawning is expensive, keeping is nearly free. So
the registry is not a convenience, it is where the value is.

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
