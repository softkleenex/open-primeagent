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
`evidence()["repeated_errors"]` is the candidate list.

| what you learned | where it goes |
|---|---|
| a procedure this project always requires | `prompt` |
| a specific fact (port, path, owner, why a decision was made) | `memory` |
| a procedure you keep re-executing | `skill` |
| context a particular role always needs | `subagent` spec |

## Rules

- **Smallest change.** One or two CRUD operations, not a rewrite.
- Never modify the base system prompt.
- Everything must be reversible.
- Run `opa_bootstrap()` afterwards so the next session actually reads it.
