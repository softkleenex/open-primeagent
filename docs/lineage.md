# Lineage: what this actually inherits from Prime Agent

This project claims to bring [Prime Agent](https://github.com/PrimeIntellect-ai/prime-agent)'s
RLM to the coding agent you already run. That is a claim about a *contract*, and
a claim like that is worth nothing unless you can check it. This page is the
check.

It is written for a skeptical reader: every row points at the upstream file and
line it came from, and at the test that fails if we drift.

**Not a fork.** No upstream code is copied. The reference checkout lives in
`_ref/`, is git-ignored, and is read only to learn the contract. What is
reproduced is field names, key names and closed value sets — the interface, not
the implementation.

## Why "inheriting the concept" is a small job

Upstream is a complete agent harness. Measured on the reference checkout:

| package | LOC | what it is |
|---|---:|---|
| `packages/coding-agent` | 117,690 | host harness, sessions, TUI, CLI |
| `packages/ai` | 35,332 | providers, OAuth, MCP |
| `packages/tui` | 14,635 | terminal UI |
| **`prime-agent-runtime`** | **1,536** | **the `rlm` kernel shim — all of it** |

`rlm/__init__.py` is 348 lines, and most of them are one-line
`await host_request("rlm.run", ...)` RPC wrappers. **RLM is a protocol, not an
engine.** The other 167k lines are one particular host for it.

So the interesting question is not "can this be reimplemented in 3k lines" — it
is "does the reimplementation actually speak the same protocol". Below.

## Inherited exactly

Verified by [`tests/test_upstream_compat.py`](../tests/test_upstream_compat.py),
which runs in CI. Because `_ref/` is not committed, that file carries upstream's
contract transcribed as data with `file:line` citations; if upstream changes, it
is the thing to re-check by hand.

| what | upstream | status |
|---|---|---|
| request names | `rlm.run`, `rlm.list_subagents`, `rlm.delete_subagent` | identical on the wire |
| `RLMSubagent` fields | `rlm/__init__.py:44` | all 6 present |
| `RLMSpawnHandle` fields | `rlm/__init__.py:28` | all 4 present |
| child status vocabulary | `rlm/__init__.py:200` | exactly `{running, completed, error}` |
| `HarnessEntry` fields | `rlm/harness.py` | **13/13, field for field** |
| `RefinementEvent` fields | `rlm/harness.py:114` | all 6 present |
| state file schema | `harness_state.json`, `"schema": 1` | entries-by-kind + refinements |
| entry kinds / scopes | `prompt·memory·skill·subagent` / `local·global` | same |

The strongest single check is not a field list. Upstream validates every
sub-agent payload through `_subagent_from_payload` (`rlm/__init__.py:181`) and
**raises** on anything malformed. Our test reproduces those acceptance rules and
runs our own wire payloads through them, so "upstream-written code can read our
host" is asserted rather than asserted-in-prose.

That check has already earned its keep. It found two breaks in code that had
been shipping and passing its own tests:

- `rlm.delete_subagent` returned `{"deleted": {id, name}}`. Upstream reads
  `payload["subagent"]` and validates a whole record — so an identically named
  request answered in a shape upstream cannot parse at all.
- `RLMSubagent` was missing `session_name`, `session_id` and
  `active_session_id`.

Both fixed in `6f6f5e0`. Compatibility that nobody tests is compatibility that
is already broken.

## Do upstream's skills run here?

A sharper question than "do the type names match", because upstream ships 13
skills and a user may paste one in verbatim. Extracting every documented
`await x.y(...)` call from `packages/coding-agent/skills/*/SKILL.md`:

| upstream skill calls | here |
|---|---|
| `goal.get` · `goal.create` · `goal.complete` | ✅ same names, same arguments |
| `rlm.list_subagents` · `rlm.delete_subagent` | ✅ |
| `agent_message.send` · `agent_message.list_agents` | ✅ — `list_agents` was **missing until this check found it** |
| `rlm_heartbeat.create/list/update/delete` | ⚠️ same concept, different name: ours is `schedule` |
| `compact` · `refine` · `agent_observe` · `linear` · `notion` | ❌ host-harness features we delegate on purpose |

This is how `agent_message.list_agents` was found. It is documented as the call
to make *before* sending, so a pasted agent-message skill would have failed at
its first step. Matching a module's exported names does not catch that; matching
what the documentation tells a model to call does. Pinned now in
[`tests/test_upstream_compat.py`](../tests/test_upstream_compat.py).

Two notes on the ⚠️ and ❌ rows. `rlm_heartbeat` and our `schedule` are the same
idea — recurring prompts the session collects later — and the naming gap is a
real incompatibility we have not closed. The last row is not a gap at all: those
are the 167k lines we delegate, and reimplementing them would break the premise.

## Diverged on purpose

Each of these is a decision with a cost, not an oversight.

| | upstream | here | why |
|---|---|---|---|
| transport | Jupyter `comm` on the control channel | Unix domain socket, one JSON line per request | the host is a separate process we do not own, so we cannot ride its kernel's comm |
| who runs a child | in-process, inside its own harness | shells out to your `claude` / `codex` | so we never have to own your sessions, auth or model choice — **this is what buys "don't switch agents", and it costs ~36k tokens of cold CLI boot per child** ([measured](../bench/README.md)) |
| authority | one trusted kernel | per-caller tokens with `parent` / `child` roles | a child process holds the socket and can speak the protocol directly, whatever its MCP tool list says ([security](security.md)) |
| harness scope | global store | project-scoped, with a `before` snapshot on every refinement | so a refinement is reversible; the snapshot is the extra field below |
| child addressing | `rlm_child_id` | `rlm_child_id`, plus a human `name` for re-tasking | a child you re-task across a week needs an address you can type |
| who a child may message | parent, siblings, children | parent only | a child that can address a sibling can re-task work it does not own. `list_agents` shows a child only the parent, so the address book matches the authority the bridge will actually grant |

We also add fields upstream has no equivalent for: per-child `turns`, `tokens`,
`cost_usd`, `adapter`, `last_error`, and `before` / `rollback_of` on refinements.
These are what `attention()`, the goal budget and `harness.rollback()` are
computed from.

### One interop limit you should know

Upstream filters unknown keys when it loads state
(`rlm/harness.py:225` and `:261`) rather than failing — so our extra fields
degrade instead of breaking. But the consequence is concrete:

> Upstream can read a state file we wrote. If upstream then **writes it back**,
> our extra refinement fields — including the `before` snapshots
> `harness.rollback()` needs — are dropped.

Read-only interop is safe in both directions. Alternating writers is not, and no
amount of schema compatibility fixes that. This is also why our `HarnessEntry`
is asserted to match upstream *exactly* rather than as a superset: an extra
entry field would be silently discarded on any upstream round-trip, so writing
one would be a quiet way to lose data.

## What we do not inherit, and do not intend to

Sessions, providers, OAuth, model selection, permission prompts, the TUI. That
is the 167k lines, and it is exactly what your existing agent already does well.
Rebuilding it would contradict the premise — see the four rules in
[CONTRIBUTING.md](../CONTRIBUTING.md).

## What we cannot claim

**We have never benchmarked against Prime Agent.** Every number in
[bench/](../bench/README.md) compares *opa + Claude Code* against *bare Claude
Code*. So nothing here supports "as fast as Prime Agent" or "as good as Prime
Agent", and this repository does not say it.

A head-to-head is the obvious missing experiment, and the honest reason it has
not run is worth stating: upstream's own docs note that third-party harness use
of an Anthropic subscription
[draws on extra usage and is billed per token](https://github.com/PrimeIntellect-ai/prime-agent)
rather than against plan limits, and it needs an interactive `/login`. So it
costs real money and a human at a keyboard. Until someone runs it, the claim
this repo makes is the narrower one:

> The protocol is the same, and that is checked by a test. The performance
> comparison is open.

If you run it, the methodology in [bench/](../bench/README.md) is designed to be
copied — including its record of the four attempts it took before one of those
benchmarks measured anything real.
