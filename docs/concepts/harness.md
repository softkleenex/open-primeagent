# The continual harness

> "Self-improving" here means the **harness** improves. Not the weights.

```
H = (ρ prompts, G sub-agent specs, K skills, M memory)
```

Four kinds of entry, two scopes (`local` to the project, `global` across
projects), full CRUD, and exact rollback. The file schema is kept compatible
with upstream Prime Agent so sessions can move between the two.

The usual loop looks like this, and the human is the bottleneck:

```
you notice a mistake → you edit CLAUDE.md → next session is better
```

The harness moves part of that loop to the agent — carefully, and with the
brakes described below.

## Projection: the problem unique to this project

Upstream owns its system prompt and can inject the harness directly. We cannot —
we are a guest in your agent. So we **project into the files your host already
reads**:

| kind | goes to |
|---|---|
| `prompt` | a delimiter block in `CLAUDE.md` / `AGENTS.md` |
| `skill` | `.claude/skills/<id>/SKILL.md`, marked `.opa-managed` |
| `memory` | `.opa/memory/*.md` — only an **index** enters the prompt block |
| `subagent` | the registry's default spec, applied at spawn |

```markdown
<!-- opa:begin — generated. Nothing outside this block is touched. -->
...
<!-- opa:end -->
```

The invariant: **we write only inside the delimiters.** Content outside is
preserved byte for byte, skill directories without our marker are never touched,
and `opa_bootstrap(remove=True)` restores everything exactly.

`agent="auto"` writes only to prompt files that **already exist**. Creating a
`CLAUDE.md` you never had would itself be changing your environment.

This is the promise the whole project rests on, so it lives in
`tests/test_projection.py` and `tests/test_bootstrap.py` rather than in prose.

Memory bodies deliberately stay out of the block. "Context is for deciding, not
for storage" applies to the projection too.

## Who decides what to change

Not us. Claude Code advertises no MCP `sampling` capability
([measured](evolution.md#11-what-the-host-declares)), so the host does not lend
us its model. The split is:

```python
evidence = await harness.evidence()     # we gather grounds
# you (or a refiner child) decide the delta
await harness.apply(changes, trigger="refine", evidence=str(evidence))
await harness.rollback(event_id)        # exact revert, any time
```

`evidence()` returns `repeated_errors` — signals seen **more than once**. A
one-off is not a pattern.

## Promote less than you want to

This is not taste; it is measured. From the
[benchmarks](../../bench/README.md):

- when the knowledge is expensive to rediscover (a generator hidden among 16
  scripts), one harness entry cut turns **-34%**, cost **-35%**, wall clock
  **-57%**, and worst-case turns **-54%**
- when the same knowledge sits one glance away, the same entry made things
  **+26% worse**

A harness entry pays in proportion to how expensive the knowledge is to
rediscover. Promoting what the model can re-derive at a glance is a net loss.

## Brakes

- The base system prompt is never modified.
- Every change is one event with a `before` snapshot, so rollback is exact —
  including deletes.
- If any operation in a delta fails, the whole delta reverts. A half-applied
  harness is the worst outcome.
- Prefer the smallest change. One or two CRUD operations, not a rewrite.

## Where entries live

```
.opa/sessions/<id>/harness/harness_state.json    # local scope
~/.opa/harness/harness_state.json                # global scope
```

```json
{"schema": 1,
 "entries": {"prompt": {...}, "memory": {...}, "skill": {...}, "subagent": {...}},
 "refinements": [{"id": "ref-1a2b", "trigger": "...", "changes": [...], "before": [...]}]}
```

`before` is our addition. Upstream records changes as strings, which cannot be
reverted precisely; extra fields are ignored by its loader, so compatibility
holds both ways.
