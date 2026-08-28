# Quickstart

## Install

```bash
claude mcp add opa -- uvx open-primeagent
```

Check it registered:

```
/mcp        # opa, with four tools
```

Other hosts: [install/](install/).

## 1. The kernel remembers between calls

```python
opa_python("files = [f'f{i}.py' for i in range(500)]")
opa_python("len(files)")          # -> 500, in a separate call
```

Keep large intermediate results in variables and print only what you need to
decide the next step. Output is truncated on the way back; the full text is
written to a file whose path you get.

## 2. Sub-agents that stay

```python
await rlm("audit the API layer for security problems", name="api-reviewer")
```

That returns immediately — the child keeps working. Collect results when you
want them:

```python
await agent_message.inbox()
```

Days and kernel restarts later, the child is still there:

```python
await rlm.list_subagents()
await agent_message.send("re-check it now that I've fixed the code",
                         receiver_role="child", receiver_name="api-reviewer")
```

It answers with its earlier context intact. Look for an existing child before
creating a new one — an agent that already knows the area is always the better
target.

## 3. Teach the project something

When you learn a rule the code does not state:

```python
await harness.create(
    "prompt", "regenerate after schema edits",
    "After editing schema.py, run tools/sync_models.py before the tests.",
)
```

Then project it into the files your agent already reads:

```
opa_bootstrap()
```

This writes inside a delimiter block in `CLAUDE.md` / `AGENTS.md`. Nothing
outside the block changes, and `opa_bootstrap(remove=True)` restores the file
exactly.

Promote sparingly. [Benchmarks](../bench/README.md) show an entry pays for
itself in proportion to how expensive the knowledge is to rediscover — promote
something the model can re-derive at a glance and you make things *worse*.

## Lost your context?

```
opa_status()
```

It leads with what is waiting for you — unread reports from sub-agents, failures
that have recurred and are worth promoting, scheduled prompts that have come
due, the goal you were pursuing — and each item says which call to make next.
Reading it consumes nothing.

## Where things live

```
.opa/
└── sessions/<id>/
    ├── trajectory.jsonl      every event, the input to refinement
    ├── outputs/              full text of truncated output
    ├── harness/              prompts, memory, skills, sub-agent specs
    ├── mailbox/              agent-to-agent messages
    └── children/             the sub-agent registry
```

## Next

- [Concepts](README.md#concepts) — why any of this is shaped the way it is
- [Security](security.md) — this is **not** a sandbox
