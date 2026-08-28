# Long-running work

`goal`, `schedule` and `autonomous` — and an honest account of which of them can
actually act on their own.

## The limit that shapes all three

**We do not own your agent's turn loop.** open-primeagent is an MCP server; it
runs when your agent calls it and is otherwise inert. So a goal cannot re-prompt
you, and a schedule cannot wake you up.

What we can do is *persist*, and hand things over when you next look. Due items
are **collected on your next turn**, a pull rather than a push.

The exception is `autonomous`, where opa drives child processes itself. There it
really does act without you — because the children are ours, not the host's.

## Goal

An objective that outlives the context that created it.

```python
await goal.create("get the integration suite green", token_budget=200_000)
await goal.get()
await goal.complete()
```

It shows up in `opa_status()` until something explicitly ends it, which is the
whole point: an agent that lost its context to a compaction still finds out what
it was doing.

Rules kept from upstream, and enforced here:

- Only `complete()` ends a goal. Saying "done" does not.
- Running out of budget is **not** completion. The status becomes
  `budget_exhausted` and `completed_at` stays empty. `abandon()` exists for
  stopping without claiming success.
- One active goal at a time; starting a second is refused with the first one's
  objective in the error.

Token budgets are charged wherever tokens are actually burned — an autonomous
run bills its children against the active goal.

## Schedule

A durable queue of prompts that become due at a time.

```python
await schedule.create("check whether the deploy finished", in_seconds=600)
await schedule.create("re-run the benchmark", at="2026-08-21T09:00:00Z")
await schedule.create("summarise what changed", every_seconds=3600)   # heartbeat

await schedule.due()                  # what has come due, and consume it
await schedule.due(collect=False)     # look without consuming
```

Interval entries are the heartbeat form: firing reschedules them, one-offs
deactivate. Missed ticks coalesce — an interval that came due five times while
you were away fires once, not five times.

A host-owning harness offers two deliveries for these: *steer*, which interrupts
a running turn, and *follow-up*, which waits for the turn to end. **We can only
ever do the second.** Interrupting a turn means being inside the host's loop, and
we are not. If you need something to actually interrupt, that is `autonomous`,
where opa drives the children itself.

`source` separates what you asked for from what the agent set up on its own
(upstream keeps `/heartbeat` and `rlm_heartbeat` apart for the same reason). An
agent scheduling its own reminders is fine; an agent scheduling things you
cannot find is not.

```python
await schedule.list(source="agent")   # what has it set up for itself?
```

`opa_status()` reports how many entries exist and how many are due, and looking
does not consume them.

## Autonomous

Re-task a child until a quality gate passes.

```python
await autonomous.start(
    "make the failing integration tests pass",
    child_name="fixer",
    gate="uv run pytest -q tests/integration",
    max_turns=6,
    token_budget=300_000,
)
```

The loop:

1. give the child the objective
2. wait for its turn to finish
3. run the gate
4. if it exits 0, stop; otherwise **feed the gate's own output back in as the
   next prompt** and go again

Step 4 is the whole difference between this and a cron job that reruns a script.
The child does not just retry — it retries *knowing what failed*.

It stops on `max_turns`, `token_budget` or `wall_clock_seconds`, whichever comes
first, and the `outcome` field says which:

| outcome | meaning |
|---|---|
| `gate_passed` | the gate exited 0 |
| `max_turns` | ran out of turns, gate still failing |
| `token_budget` | budget exhausted |
| `timeout` | wall clock exceeded |
| `error` | the child itself failed; `detail` carries its error |

Three implementation details that matter:

- The gate runs **off the event loop**. A gate is usually a test suite, and
  running it inline would freeze the bridge and every other child callback for
  its whole duration.
- Gate output is truncated head-and-tail before being fed back, so a noisy suite
  cannot blow out the child's context.
- **A turn that changed nothing is told so.** The workspace is fingerprinted
  before and after each turn (tracked changes plus untracked file contents). If
  the tree is identical, re-running the gate cannot give a different answer, so
  repeating the same failure would just invite the same no-op. Instead the child
  is told it edited nothing and asked either to change something or to explain
  why it believes the code is already correct. `turns[].changed_files` records
  this, and it is `null` outside a git repository, where there is nothing to
  compare.

### ⚠️ Before you use this

An autonomous run **edits files and executes your gate command unsupervised**.
That is not a side effect, it is the feature. Two runs cannot overlap, and
budgets are enforced, but nothing here contains what the child does with its
tools.

Run it inside a devcontainer or VM. See [security.md](../security.md).

## What is deliberately missing

No cron expressions. `at`, `in_seconds` and `every_seconds` cover what a coding
session needs, and a cron parser is a dependency and a class of bug for
something nobody asked for yet.

No "wake the agent" push. It cannot be built honestly from where we sit, and
pretending otherwise would fail the first time someone left a terminal idle.
