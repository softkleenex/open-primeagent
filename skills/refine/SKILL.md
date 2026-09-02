---
name: refine
description: Turn what this session taught you into the smallest possible harness change (prompt notes, memory, skills, sub-agent specs), so the next task starts better. Reversible.
---

# Refine

"Self-improving" means the **harness** improves, not the model's weights.

```python
evidence = await harness.evidence()     # grounds, gathered from this session
await harness.apply([...], trigger="refine", evidence=str(evidence))
await harness.rollback(event_id)        # exact revert
```

`harness` does not decide what to change — **you do**. The host does not lend us
its model, so the judgement is yours (or a refiner child's).

## What to promote

Do not promote something you saw once. Promote only what **recurred** —
`evidence()` counts the repetitions and names the kind each one argues for:

| signal | argues for |
|---|---|
| `repeated_errors` | a `prompt` policy, or a `memory` fact |
| `repeated_commands` | a `skill` — you keep running the same procedure |
| `retasked_subagents` | a `subagent` spec — the same delegation role keeps coming back |

**It will miss the best lessons.** Those signals see repetition, not wrongness:
a call that succeeded and returned something stale or misleading leaves no trace
at all. If you noticed something the trajectory cannot show, that is exactly the
thing worth writing down — pass it in the `evidence` argument yourself.

## Rules

- **Smallest change.** One or two CRUD operations, not a rewrite.
- Never modify the base system prompt.
- Everything must be reversible.
- Run `opa_bootstrap()` afterwards so the next session actually reads it.
