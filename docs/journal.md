# Journal

What building and measuring open-primeagent taught us, newest last. Each entry
records something we got wrong or did not know, and what changed because of it.
Current status and next steps live in [TODO.md](../TODO.md); this file is the
reasoning behind them.

## What the benchmarks changed about our understanding

Measured value so far is concentrated in **the harness**, not in RLM:

| claim | measured |
|---|---|
| harness entry, knowledge expensive to rediscover | ✅ -34% turns, -35% cost, -57% wall clock |
| harness entry, knowledge one glance away | ❌ +26% turns |
| persistent kernel on shell-friendly work | ❌ +42% turns, +33% cost |
| sub-agent fan-out on a small codebase | ❌ +454% tokens, +777% cost |
| sub-agent fan-out on a 444-file codebase | ❌ +259% tokens, **+127% wall clock** |
| fan-out with a blocking check per subsystem | ⚠️ same fixes, 2.8x tokens, but **4/4 checks verified vs 1-of-3 runs** |
| warm child re-tasking vs a cold child | ✅ -91% tokens, -81% cost |

Two mechanisms explain all of it:

1. **A child costs ~36k tokens of session startup.** Spawning is expensive,
   keeping one is nearly free. That is fan-out losing and reuse winning, from
   the same fact.
2. **A competent agent greps; it does not read.** On a 135k-token repository the
   single reviewer answered using 42k tokens. Fan-out is meant to relieve a
   context bottleneck that never forms, which is why scaling the codebase up did
   not rescue it.

So **fan-out has no measured case where it wins**, and reuse does. The registry
is where the value is, not the parallelism. That matches the project's own
thesis ("a child is not disposable") better than fan-out ever did.

Open question: should `rlm()` warn when it is about to spawn a second child for
work that looks small? The guidance currently lives only in the tool description
and docs, where a model may or may not weigh it.

## What building Phase 5 changed

A tool description can remind an agent of what **it** recorded while running; it
cannot give standing to anything else. Claude Code read our promoted rule back
verbatim and then declined to act on it, because it had no record of creating
the note. No wording fixes that — any provenance we assert is more
server-authored text.

So: the live surface carries an *index* of the current session's own notes, and
authority comes from the project file. **L1 reminds, L0 authorises.** That also
settled where the harness should live — per **project**, not per session, since
it is what the codebase taught us rather than what one conversation did.

## What the deep read of upstream changed

Three parallel readings of `_ref/prime-agent` (compaction/kernel, child lifecycle,
turn loop). No code copied. What it changed here:

**Confirmed our shape.** Even upstream, which owns the whole host, has *no push
signal* for compaction — its kernel finds out by polling `compact.status`. Our
"the recovery call carries the knowledge" design is the same answer arrived at
from a weaker position, not a compromise.

**Filled real gaps.**
- `opa_status` now lists live kernel names. Upstream re-anchors a compacted agent
  with exactly that list, and we were not providing it.
- The mailbox has per-message and per-sender caps. The push channel is reachable
  by a prompt-injected child; one child must not be able to bury the rest.
- Child records are written atomically and persisted *before* being registered.
  A handle for a child whose record never reached disk is unrecoverable.
- Goal carries its rules with it, and budget exhaustion now refuses `complete()`
  outright with a wrap-up instruction instead of a status field nobody reads.
- The projection block is budgeted (6 per kind, 180-char summaries, counts and
  overflow). It is read on every request; unbounded it would cost more than it saves.

**Corrected a claim.** Our 36k-per-child startup is the price of shelling out to
the user's CLI, not a property of sub-agents: upstream's children are in-process
sessions and never pay a cold boot. The benchmarks now say so.

**A methodology lesson worth keeping.** The serial-work benchmark measured the
wrong thing three times before it measured anything: children could not run
shell commands at all; then the task let an agent fix by inspection and skip the
work; then a tightened prompt still did not bind. An agent decides how much
verification to do, so a benchmark cannot impose work through its prompt — the
scoring has to be able to tell whether the work happened. Every failed version
produced a plausible table.

**Known gaps we did not close.** Upstream prunes oversized kernel variables at
compaction and tells the model which ones went; we never prune, which is
arguably better but should be stated. Upstream's suppression of an autonomous rerun on an
unchanged git worktree is adopted. Its child→parent delivery
steers a live turn; ours cannot, and never will from outside the host.

## What dogfooding found (2026-08-31)

First real use of opa on this repository rather than on a benchmark. Four
findings in one sitting, none of which a synthetic experiment would have
produced.

**A stale server is invisible.** The registered MCP server had been alive for
days and was still running Phase 3 code: it answered `goal: {"note": "Phase 4"}`
and had no `attention` field, while the source on disk was current. An MCP
server lives as long as the host session, so it never picks up an upgrade until
the host reconnects — and nothing said so. `opa_status` now reports the running
server's own version and start time.

**The bridge had no trust boundary, and our docstrings claimed it did.** Found
by pointing a reviewer child at `src/opa/bridge.py` and the push path. A child is
a separate process holding `$OPA_HOST_SOCKET`, and since children now get `Bash`
by default it can speak the protocol directly — the one-tool MCP server only
limits what its *model* is offered. It could call `harness.apply` and
`harness.project` and write a persistent instruction into the user's own
`CLAUDE.md`, spawn grandchildren via `rlm.run`, or delete its siblings. Fixed
with per-caller tokens: a child's token authorises `agent_message.send` and
nothing else.

**`sender` was self-asserted.** One child could file forged findings under a
sibling's name and exhaust that sibling's mailbox quota. Identity now comes from
the token.

**Children inherited the whole server environment.** Every secret the server
held travelled to a process the threat model assumes may be prompt-injected,
which only has to run `env`. Children now get a built environment plus
`OPA_CHILD_ENV_PASSTHROUGH`.

Worth recording *how* these were missed: the earlier security pass found a path
traversal because it went looking for path traversal. It never tested the trust
boundary a docstring asserted. A reviewer reading the code with no memory of
having written it did.

Also learned: of the three coding CLIs installed here, only `claude` is usable —
`codex` reports an expired token and `gemini` an ineligible tier. That blocks
adapter work that cannot be verified by running it.

## Continuing to dogfood (2026-09-02)

Two more from using it rather than testing it.

**Sub-agent activity left no trace in the trajectory.** `rlm.run`,
`agent_message.send` and child turns were never recorded, so the session record
— the thing refinement reads — could not show that any work had been delegated.
The most significant thing that happened in the previous session (spawning a
reviewer, re-tasking it, getting two rounds of findings) was invisible to the
tool meant to learn from it. Now recorded, and `evidence()` uses it.

**`evidence()` only counted failed cells.** It answered "nothing to promote"
while the session had just produced its most valuable lesson. It now also counts
procedures that were re-executed (a skill argument) and delegation roles that
recurred (a sub-agent spec argument), and each signal names the kind it argues
for. It also says plainly what it cannot see: these are signals of repetition,
not of wrongness, and the lesson that prompted all this came from a call that
*succeeded* and returned something stale.

## Dogfooding round 3, on a restarted server (2026-09-02)

With the host restarted the server finally ran current code, and `opa_status`
reported its own version — the fix from round 2 working in the situation that
motivated it.

**A child inherited the user's entire MCP ecosystem.** Found by the reviewer
sub-agent, and reported through the push channel *while it was still working* —
the first time that channel has paid for itself. `--mcp-config` is additive, so
without `--strict-mcp-config` a spawned child also loaded every MCP server the
user has registered: measured, a probe child saw arxiv and chrome-devtools among
others. In a workspace where opa itself is registered — such as this one — the
child would get a full opa server with a parent-role token, defeating the
one-tool restriction entirely. Fixed; children now start from nothing.

Verified directly against a live child process rather than in a unit test: its
environment carried exactly `OPA_CHILD_NAME`, `OPA_CHILD_TOKEN`,
`OPA_HOST_SOCKET` and `OPA_ROLE`, no parent token and no credentials.

Still open: a codex child has no per-invocation equivalent of
`--strict-mcp-config`, so it still inherits `$CODEX_HOME/config.toml` servers.
Written up in `docs/install/codex.md` rather than fixed, because
`--ignore-user-config` would also drop the user's model settings and codex auth
here is expired, so the result could not be verified.

**The reviewer was too generous once, and checking mattered.** It dismissed
stealing the kernel's token via same-uid `ps` as out of scope under the "not a
sandbox" framing. But our threat model names a prompt-injected child explicitly,
and that child runs as the same user with a shell. Verified: `ps eww` on the
kernel prints `OPA_HOST_TOKEN` in full. The kernel's token is now handed over
in-process at boot instead of through its environment, which removes the
one-command path — and the docs now say plainly that it does not remove the last
one. Same-uid is not containment, and claiming otherwise would have been the
same mistake as the docstring that started this.

## Phase 4, used for real for the first time (2026-09-07)

Three gaps, all from trying to use goal / schedule / autonomous rather than
testing them.

**A token budget counted one code path.** A child spent 27,541 tokens while the
goal reported its full 400,000 remaining, because only autonomous runs charged
it. Every sub-agent turn is charged now — and the docs say what a budget can and
cannot bound: we never see what the host agent spends on its own reasoning, so
it bounds delegated work.

**`kernel_names` was mostly noise.** It exists to re-orient a caller that lost
context, but half the list was the symbols we preload into every kernel, which
are present regardless and say nothing about the session. Excluded.

**An autonomous run could not be scoped.** The gate and the child always ran in
the server's workspace root, so the advice to keep unsupervised work away from
anything you care about was impossible to follow. `cwd` now scopes both,
resolved through the same guard as a child's cwd.

Confirmed working as designed: `attention` surfaces the mailbox, due schedule
items and the active goal with the next call for each; a schedule peek does not
consume; user- and agent-created entries stay distinguishable; the goal carries
its own rules and refuses to complete on an exhausted budget.

## Checking the inheritance claim (2026-09-08)

The README's headline is that this speaks Prime Agent's RLM protocol, and
nothing verified it. Comparing our types against the reference surface field by
field found two real breaks in shipping, green code:

**`rlm.delete_subagent` answered in a shape upstream cannot parse.** We returned
`{"deleted": {id, name}}`; upstream reads `payload["subagent"]` and validates a
whole record. An identically named request was mutually unintelligible.

**`RLMSubagent` was missing `session_name`, `session_id`, `active_session_id`.**
The last is a distinction we had collapsed without replacing: `status` says a
child is running, not *which* session is live for one re-tasked across turns. We
already held it as `native_session_id`.

Everything else checked out — `HarnessEntry` matches field for field, our
`ChildStatus` literals are exactly upstream's closed set, `RLMSpawnHandle` and
`RefinementEvent` are supersets.

**Upstream's own skills are a sharper test than its `__all__`.** Extracting every
documented `await x.y(...)` from the 13 SKILL.md files found
`agent_message.list_agents` missing — documented as the call to make *before*
sending, so a pasted agent-message skill would fail at its first step.
Implemented, answered per role: a parent sees its children, a child sees only the
parent. Upstream also lists siblings; we do not, for the same reason
`agent_message.send` has a role gate.

`tests/test_upstream_compat.py` pins all of it. `_ref/` is not committed, so the
contract is transcribed as data with `file:line` citations, including a
reproduction of upstream's `_subagent_from_payload` acceptance rules that our own
wire payloads now run through. Deliberate divergences are asserted too.

**An interop limit no schema compatibility fixes.** Upstream filters unknown keys
on load rather than failing, so our extra fields degrade gracefully — but if
upstream *writes* the file back, the `before` snapshots `harness.rollback()`
needs are dropped. Read-only interop is safe both ways; alternating writers is
not. This is also why `HarnessEntry` is pinned as an exact match rather than a
superset.

**The head-to-head is possible and has not been run.** Upstream has `--print`/`-p`
and `--mode json`, records per-message `Usage` with cache separated from
input/output, and attributes RLM child usage to the parent. What blocks it is an
interactive `/login` and the fact that third-party harness use of a subscription
is billed per token from extra usage — someone's money, not a tooling gap. Every
number we publish compares opa + Claude Code against bare Claude Code, and
`docs/lineage.md` says so.

**A goal could record why it was abandoned but not what achieving it meant.**
Found by closing a real goal: `abandon(note=...)` took a note, `complete()` did
not, and the record had an empty `note` field nothing could fill.

**The README claimed more verification than codex has.** Both adapters sat under
"verified by tests that spawn a real child agent", and only claude-code earns it.
Codex was verified against the real binary by hand when written (`43db9fd`) and
is covered against a stub CLI since; the auth here is expired so it is not being
re-checked. Now stated as "verified once, not continuously".

## The kernel benchmark, and the fifth wrong measurement (2026-09-08)

`bench/depgraph.py`, with its prediction committed before any results ran.

Designing it took five rounds, all before any agent ran, each removing a way to
score well without doing the work: the most-depended-on module is a sink in any
DAG so asking about its imports had no answer; ranking globally named modules
root cannot reach, making the deletion question zero by definition; ranking by
in-degree always landed on a late near-leaf; root's direct imports each head a
subtree so one always won the cut-vertex question; and every module was
reachable, making question one `ls | wc -l`. What survives has a trap that
proves the chain cannot be shortcut — the pivot's closure is 195 but deleting it
disconnects only 99, because the rest survive by a cross edge.

**Then the instrumentation turned out to be wrong.** Two of seven baseline runs
came in at 23–29k tokens on turn 1 against ~1.2k for the rest, and I read that
as a variance finding. The data disagreed: those runs cost $0.005 per 1k tokens
against $0.035 for the others, with the same tool-call count and wall clock.
Tracing turn 1 thirteen times with `--output-format stream-json` produced no
oversized tool result and no blowup at all. It was prompt-cache creation, and
folding it into a token total measures the state of the cache and calls it the
cost of the task.

> An agent's token usage is not a property of the task alone. Any measurement
> spanning separate CLI invocations is measuring cache state too, and has to say
> which it means.

`work_tokens`, `cache_write`, `cache_read` and `cost_usd` are now recorded
separately. Upstream's own `Usage` draws the same distinction, which is mild
evidence it is the right one. Old results kept as
`depgraph-INVALID-cache-writes-counted-as-work.json`.

## The benchmark that found the benchmarks were wrong (2026-09-12)

Benchmark 5 (`bench/bigdata.py`, 8M rows, 337 MB, eight adaptive questions) came
out flat like benchmark 4. Before writing a third "no effect" paragraph I
counted what the agent had actually invoked — kernel executions leave files on
disk:

    benchmark 4 (import graph)   12 runs / 96 turns   0 called opa_python
    benchmark 5 (8M-row file)     3 runs / 24 turns   0 called opa_python

**120 turns, zero calls.** A session directory is created per CLI invocation,
so these are turns rather than independent trials - each one a separate chance
to reach for the kernel. Tracing shows both arms doing the same thing:

    turn 1  Bash: awk -F, 'NR>1{print $2}' events.csv | sort -u | wc -l
    turn 2  Bash: awk -F, 'NR>1{sum[$3]+=$5} END{...}' events.csv

So benchmarks 3, 4 and 5 never compared a kernel against a shell. They compared
a shell against a shell with an unused MCP server attached, which is why every
delta was noise. The conclusion published off benchmark 4 — "a kernel saves you
re-emitting the script, not the data" — was right about the baseline and wrong
as a measurement of the kernel, which was not in the comparison.

Corrected in README.md, bench/README.md and docs/concepts/persistent-python.md.
What the data supports:

> The cost of *offering* the kernel is approximately zero. Its value is
> unmeasured.

The reason is not a bad tool description. `awk` is the right answer to those
questions: a streaming aggregation never materialises the structure a kernel
exists to hold, so our premise — that the agent builds state worth preserving —
is what the task never called for.

Measured before the run and standing on its own: a pickle reload costs 20-25% of
a rebuild at 0.5M, 2M and 8M rows, so a filesystem is a good enough cache for
anything serialisable. That bounds where a kernel could ever win.

- [ ] **The kernel is still unmeasured.** Testing it needs state that cannot be
      streamed out of a file — a loaded model, an open connection, a GPU
      context. Everything else, the shell already does.
- [ ] Whether an instruction in the projected block would change the agent's
      choice, and whether it *should* — talking it out of `awk` when `awk` is
      correct would be a worse product, not a better benchmark.

Also this session: PyPI 0.1.0 → 0.1.2, and the two things only publishing could
find. `uvx open-primeagent` did not work at all (uvx runs the executable named
after the *package*; we shipped only `opa` and `opa-child`), and every one of the
34 links on the PyPI project page was a 404 (relative links resolve against
pypi.org there). Both now covered — the first by a test, the second by
hatch-fancy-pypi-readme rewriting links for the published description only.

`scripts/check_links.py` replaces the hand-rolled slugger that broke three
anchors: it reads GitHub's own rendered HTML, because a reimplementation got
both `_` and U+FE0F wrong and neither mistake is visible in the source.

## Do the tests defend the guards? (2026-09-17)

Two rounds in a row, an existing test caught a mistake of mine - one where I had
quietly turned a loud refusal into a silent skip. That makes the suite worth
trusting, which makes it worth checking.

294 tests, none without a real assertion and none tautological. Then the sharper
question, which coverage cannot answer: a line can be executed by every test in
the file and still have nothing asserting what it decides.

`scripts/mutate_guards.py` breaks each safety guard in turn and runs the suite.
All ten are defended by a failing test:

    projection refuses writes outside its directory
    projection only prunes directories it created
    a child's cwd cannot leave the workspace
    the bridge rejects a token it did not issue
    an unknown token is not silently downgraded to a child
    harness ids must be safe as a path component
    durable writes go through a temp file and a rename
    an unreadable state file is never written over
    a turn interrupted by a restart is reconciled
    a finished goal cannot be reopened

Not in CI: it takes minutes and rewrites source files. Run it after touching
anything on that list. An ANCHOR MISSING result means the code moved out from
under a mutation, which needs fixing rather than ignoring - an unanchored
mutation silently tests nothing, which is the failure this script exists to
catch.

## An outside review breaks the headline promise (2026-11-25)

Two reviewer agents were given the code with no account of what it was supposed
to have fixed, and asked to reproduce anything they reported. They came back
with nineteen findings, all reproduced. The one that matters most is the one
the README was built on.

**"Not one character outside the block" was false.** Projection found its
block with a regex that matched `<!-- opa:begin` anywhere. Our own README
shows the marker, so a user who pasted it into their CLAUDE.md lost everything
from that mention to our END on the next apply. CRLF files came back LF on
every line, and apply-then-remove was not an identity. Every one of these
passed the existing invariant test, because that test used a well-behaved file.
Markers now count only as whole lines, an ambiguous file is refused rather than
guessed at, and the round trip is tested byte for byte across six file shapes.

**A prompt could become a CLI flag.** The child CLIs took the prompt as a
leading positional argument, so a prompt starting with `-` was parsed as
options. Measured on both real CLIs. It now goes last, after `--`.

**The rest:** concurrent kernel cells hung each other; cancelled children kept
running with their tools; the shared harness store still lost writes in a
window the merge did not cover, and a rollback could report success while its
restore vanished; autonomous work was charged to the goal twice; a schedule
time without a timezone fired nine hours late in Seoul.

What is worth keeping is how they were missed. Each guard had a test, and each
test checked the case its author had in mind. `scripts/mutate_guards.py` proves
a guard is *defended*; it cannot prove the guard is *complete*. Only an input
nobody thought of does that, and a reviewer with no memory of writing the code
is the cheapest source of those we have found.

## The CLI changed what a number meant (2026-11-25)

Building the reuse receipt meant running it for real, and the first real run
said that two follow-ups to a warm child cost *more* than the cold turn:
$0.135, then $0.143 and $0.149. That contradicted the warm-child benchmark,
so one of them was wrong.

Neither was. On claude 2.1.332, a resumed session's `total_cost_usd` and
`modelUsage` are the session's running totals while `usage` is still this
turn's: cache reads went 50,289 then 94,045 = 50,289 + 43,756. In August, when
the benchmarks ran, the same field was per turn (the warm arm's $0.035 could
not include a $0.17 setup turn otherwise). So the benchmark stands, and the
registry had been summing running totals, charging each child for all of its
earlier turns again on every follow-up.

The adapter now detects which it got by comparing `modelUsage` with `usage`,
subtracts the previous running total from the same session, and reports the
cost as unknown rather than guessing when it cannot. The real follow-ups cost
$0.0087 and $0.0063: 94% less than the cold turn, not 6% more.

> A field's name is not its definition. Anything we read from a CLI we do not
> own can change meaning without changing shape, and the only check is a real
> run against numbers that must add up.

## The headline was already shipped by the hosts (2026-11-25)

Before launching we compared ourselves with Prime Agent, the third-party tools
and the hosts. The hosts were the finding. During 2026 Claude Code (resume a
finished sub-agent with `SendMessage`), Codex (`resume_agent`,
`followup_task`) and opencode (continue a child by `sessionID`) all shipped the
thing our README led with: a sub-agent you can come back to. Our 81% was real
and is still in the table, but it measured something the user now gets without
us.

What none of them do is cross over. Each host's memory stays in its own home
directory on one machine, and each host's sub-agents are reachable only from
that host. So the headline moved to the one thing that is structurally ours:
what an agent learns is written into the repo's `AGENTS.md`, which all three
read.

That claim needed a measurement that staged nothing, so `bench/portable.py`
runs the whole loop: Claude Code with open-primeagent learns the rule, and a
fresh clone carrying only the resulting `AGENTS.md` is handed to plain Claude
Code with no MCP servers. The first run found two product bugs before it found
a result. The agent filed the rule as a `memory`, which the block shows only as
a title with a path a clone does not have; and a rule that began with this
machine's Python path was cut at 180, then 400, characters before the script
name it needed. Rules are now written out to 800 characters and the tool says
a rule others must follow is a `prompt` with no machine paths. Rerun: the key
fact recorded 6 of 6 times, and the teammate's agent took 26% fewer turns and
26% less time. A modest win, because current models rediscover this rule in
about six turns.

After the easy result we built a `deep` variant on purpose: the same rule, but
three decoy scripts write plausible wrong output, the case a recorded rule is
for. 51% fewer turns and 51% less time, every one of six pairs the same way.
Both variants are reported, and the README says which one the demo replays.

Two side findings. Claude Code 2.1.332 does read `AGENTS.md` natively, checked
with every file tool disabled. And it does not load instruction files from its
own session scratch directory, which briefly made that check look negative.

Prime Agent itself had also moved: 887 commits past our snapshot, rewritten
around a Rust host, `rlm.run` renamed to `rlm.spawn`, a `cancelled` status. Our
compatibility test had pinned one handle field wrong and passed anyway. It now
pins the live contract, and `rlm.spawn` works here. The README's "under 4k
lines" was also wrong: it is about 4,800 without blanks and comments.

## Codex followed the rule and was not faster (2026-11-26)

The README leads with Claude Code learning a repo and Codex knowing none of it,
and until today only the Claude half was measured. `bench/portable.py
--teammate codex` hands the `AGENTS.md` Claude Code wrote to plain Codex CLI.

The first run looked like a 36% time win, and was not: two slow controls made
the whole gap, the medians matched. One logged pair showed why. Codex without
the file never looked for a generator. It read the test, saw it compares the
generated file with the schema, and wrote the generated file by hand; the suite
cannot tell, so it passed. The decoys built to cost Claude Code half its turns
never came into play.

So the second run logged every command. With the file, Codex ran the generator
the rule names 5 of 5 times; without it, 5 of 6 hand-edited the generated file.
That is the result we report: the rule changed what Codex did, not how fast.
A benchmark scored only on "tests pass" and "time" would have called it noise,
and a benchmark scored only on the first run would have called it a win.

One learn step in that run skipped the save (attempt 4, 6 turns), so its pair
has no teammate arm. It is in the data.

## Incident log

### 2026-08-19 — path traversal through harness entry ids

`harness.create(..., id="../../CLAUDE")` was accepted verbatim, and projection
turns ids into file names (`.opa/memory/<id>.md`, `.claude/skills/<id>/`). Proved
it wrote outside the memory directory. Reachable from any code running in the
kernel, which means reachable by prompt injection.
Fixed in two layers: ids must equal their slug (`validate_id`), and projection
resolves every path and refuses to leave its directory. `tests/test_security.py`
covers both.

Audited the same class of bug elsewhere and found it clean: mailbox names are
already sanitised, child directory names are generated (`opa-<hex>`), output
files are index-named, and session ids are uuid4.

### 2026-08-19 — code review turned up five defects (all reproduced, then fixed)

1. **The bridge broke at 64 KB.** `MAX_LINE_BYTES = 4MB` was dead code; asyncio's
   64 KiB `StreamReader` default was the real limit. A 70 KB request raised
   `RuntimeError`, 200 KB raised `BrokenPipeError`. Replies had the same ceiling,
   so an inbox holding a few child reports would blow up.
   → `limit=` passed to both `start_unix_server` and `open_unix_connection`.
2. **Concurrent resume on one child.** Three simultaneous messages spawned three
   CLI processes against the same session id (session-file race → context
   corruption). → per-child `asyncio.Lock`; messages queue instead of being
   dropped, and different children still run in parallel.
3. **Deleting a running child killed its task** with `KeyError`, and the parent
   received neither a result nor a failure. → `_safe_update` plus a `[dropped]`
   notice; exceptions are now retrieved in the done callback.
4. **Unknown arguments were silently ignored.** `rlm(prompt, name='x',
   moodel='opus')` passed and ran on the default model. → whitelist rejection.
5. **The cwd guard misfired on symlinks.** Only one side was resolved, so valid
   paths inside a symlinked workspace (`/tmp` on macOS) were rejected.
   → resolve both sides.

### 2026-08-19 — protocol key shadowing in the bridge

`rlm.run`'s `status: "running"` was merged flat into the reply and overwrote the
protocol's `status: "ok"`; the client died with `unexpected status: 'running'`.
Fixed by wrapping handler results in a `result` envelope. A reserved-word naming
rule would have broken again later, so this is enforced structurally.
`tests/test_bridge.py` guards the regression.

### 2026-08-19 — codex hung waiting on stdin

`codex exec ... --json` through a pipe sat at `Reading additional input from
stdin...` forever, because a non-TTY stdin is treated as extra input.
→ `stdin=DEVNULL` in the adapter; applied to the claude adapter for the same
reason. Separately, codex refuses to run outside a git repository without
`--skip-git-repo-check`.

### 2026-08-19 — IPC transport failed to boot the kernel

`AsyncKernelManager(transport="ipc", ip="")` timed out after 60s.
`jupyter_client` uses `ip` as the **socket path prefix** for IPC
(`<ip>-1` … `<ip>-5`), so an empty string cannot create sockets. Fixed by passing
a short temp-dir prefix, with a TCP fallback when macOS's 104-byte `sun_path`
limit would be exceeded.

### 2026-08-19 — non-ASCII titles collapsed onto one id

`slug()` stripped everything outside `[a-z0-9]`, so every Korean title became the
same fallback id and collided. Now keeps Unicode word characters.
