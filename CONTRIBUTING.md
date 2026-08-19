# Contributing

## Setup

```bash
uv sync --extra dev
uv run pytest -q          # 99 tests, no CLI is invoked
uv run ruff check .
```

Optional, and they cost real quota:

```bash
uv run pytest -q -m child     # spawns a real coding-agent CLI
uv run python bench/report.py # regenerate benchmark tables from results/
```

## Four rules we do not bend

These are the project's premises, not preferences. A change that breaks one of
them is out of scope even if it works.

1. **Do not replace the host agent.** No TUI, no session UI, no provider layer,
   no OAuth. Those belong to the agent the user already runs.
2. **Never exceed four MCP tools.** `server.MAX_TOOLS = 4`, and a test enforces
   it. New capability is exposed as a
   [kernel symbol](docs/reference/kernel-api.md). Wanting a fifth tool is the
   signal that it belongs in the kernel.
3. **Projection writes only inside the delimiter block.** Not one character of a
   user's own `CLAUDE.md` may change, and `remove` must restore it byte for
   byte. `tests/test_projection.py` and `tests/test_bootstrap.py` enforce this.
4. **`_ref/` is read-only reference.** It is not committed, and no code is
   copied from it. This is an independent reimplementation, not a fork.

## How we verify things

Claims in this repository are meant to be reproducible. Two habits follow:

**Run it.** Phase exit criteria in the [roadmap](docs/roadmap.md) are things
that were executed, not reasoned about. If you find out how a host CLI really
behaves, write it down where it belongs and remove it from the investigation
list in `TODO.md`.

**Keep negative results.** [bench/](bench/) publishes two benchmarks where
open-primeagent lost, because they are what makes the third one worth believing.
If a change makes something worse, say so in the commit message.

## Tests

| kind | marker | runs by default |
|---|---|---|
| unit | — | yes |
| kernel integration | `slow` | yes |
| real child agent | `child` | no — needs auth and quota |

A new adapter should come with parsing tests that always run *and* one `child`
test. See [docs/reference/adapters.md](docs/reference/adapters.md).

## Commits

- Explain **why**, not just what. Bug fixes should say how the bug was
  reproduced.
- English, since the repository is English.
- Author identity comes from your own `git config`.

## Reporting a vulnerability

See [SECURITY.md](SECURITY.md). Please do not open a public issue for one.
