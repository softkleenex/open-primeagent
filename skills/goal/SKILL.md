---
name: goal
description: Read the persistent goal that survives across turns, start one when the user explicitly asks, and complete it only once the objective is genuinely achieved.
---

# Goal

```python
await goal.get()
await goal.create("improve service-wide performance and get the tests green",
                  token_budget=200000)
await goal.complete()
```

## Rules

- Only `create` when the user **explicitly** asks for a long-running goal. An
  ordinary task is not a goal.
- Only `complete` when the objective is **actually achieved**. Running low on
  budget is not a reason to complete.
- Saying "it's done" does not end it. The harness keeps re-prompting until
  `complete()` is called.
