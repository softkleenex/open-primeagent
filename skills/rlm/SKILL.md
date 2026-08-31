---
name: rlm
description: Create long-lived specialist sub-agents from the persistent Python kernel and re-task them later. Use for parallel investigation, standing expert teams, and follow-up work for an agent that already has the context.
---

# RLM

Used inside the `opa_python` tool. `rlm(...)` is not an LLM API call — it creates
an **independent agent session**.

```python
api  = await rlm("audit the API layer for security problems", name="api-reviewer")
test = await rlm("map the gaps in our test coverage",         name="test-reviewer")
```

`rlm(...)` **does not wait.** It returns a handle and the child keeps working in
the background.

Results arrive in the parent mailbox. Collection is a pull, because we do not own
the host's turn loop:

```python
for m in await agent_message.inbox():
    print(m["sender"], m["message"][:200])
```

**Keep any wait short.** Your host caps how long a single tool call may run —
Claude Code cuts it at about two minutes — and that cap governs, not the
`timeout` you pass to `opa_python`. A cell that polls until a child finishes will
be backgrounded mid-wait. Poll briefly and come back:

```python
import asyncio
for _ in range(10):                       # ~50s, comfortably inside the cap
    inbox = await agent_message.inbox()
    if inbox:
        break
    await asyncio.sleep(5)
len(inbox)
```

There is nothing to lose by returning empty-handed: the mailbox is durable, so
the next call picks up whatever arrived meanwhile.

## A child is not disposable

```python
children = await rlm.list_subagents()      # still there after a kernel restart

await agent_message.send(
    "re-check it now that I've fixed the code",
    receiver_role="child", receiver_name="api-reviewer",
)   # continues with its earlier context intact
```

**Before creating a child, call `list_subagents()` and look for an existing one.**
An agent that already knows the area is always a better target for follow-up work
than a fresh one.

## Sub-agents are expensive — measure before you fan out

Each child is a full coding-agent session that pays for its own system prompt
and tool schemas first: about **36k tokens before it reads any of your code**.

In our benchmark, reviewing an entire 12-file service cost a plain agent 34k
tokens, while fanning out to four specialists produced the same findings for
**8.8x the cost and 3.4x the wall clock**. One child cost more than the whole
job.

> Hand work to a sub-agent only when that work would cost you more than ~36k
> tokens of your own context.

Don't spawn a child for something you could grep, or one per file. Do use one
per *subsystem* when the material genuinely will not fit — and above all,
**re-task an existing child** rather than creating a new one.

## Rules

- Name a child for its role (`backend`, `security`, `flutter`). It is meant to stay.
- Do not delete it because a task finished. `delete_subagent` is for when you
  genuinely mean it.
- Mixed backends are fine: `adapter="codex"`, `model=...`.
- Keep large intermediate data in Python variables, not in your context.
