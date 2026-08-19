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

## Rules

- Name a child for its role (`backend`, `security`, `flutter`). It is meant to stay.
- Do not delete it because a task finished. `delete_subagent` is for when you
  genuinely mean it.
- Mixed backends are fine: `adapter="codex"`, `model=...`.
- Keep large intermediate data in Python variables, not in your context.
