# Writing an adapter

An adapter is how open-primeagent drives a coding-agent CLI as a child. We do
not reimplement session management — the CLI already has it.

## The contract

A backend qualifies if it can do exactly two things:

1. run non-interactively from a single prompt, and
2. **resume by session id.**

The second one is where child persistence comes from. Without it a child is
disposable, and this project has no point.

```python
class AgentAdapter(Protocol):
    name: str

    def available(self) -> bool: ...
    def preassign_session_id(self) -> str | None: ...
    async def run(self, request: TurnRequest) -> TurnResult: ...
```

`preassign_session_id()` returns an id we choose, or `None` if the backend
issues its own. `claude` lets us pass `--session-id`, so the registry id and the
native session id map 1:1. `codex` issues its own, which we read back from the
first turn's `thread.started` event and store.

`TurnRequest` carries `prompt`, `cwd`, `session_dir`, `session_id`, `resume`,
`model`, `system_prompt`, `permission_mode`, `allow_dangerous`, `timeout`.

`TurnResult` carries `ok`, `text`, `session_id`, `tokens`, `cost_usd`,
`raw_path`, `error`, `duration_ms`. Returning `session_id` is how a
backend-issued id reaches the registry.

## Two things that will bite you

Both were found by running real CLIs, not by reading their docs.

**Close stdin.** Left open as a pipe, `codex exec` waits forever at
`Reading additional input from stdin...`, and `claude -p` treats piped stdin as
extra input. Always `stdin=asyncio.subprocess.DEVNULL`.

**Check the CLI's assumptions about the working directory.** `codex` refuses to
run outside a git repository unless you pass `--skip-git-repo-check`.

## Existing adapters

| adapter | spawn | resume |
|---|---|---|
| `claude-code` | `claude -p P --session-id <UUID> --output-format json` | `claude -p P --resume <UUID>` |
| `codex` | `codex exec P --json --skip-git-repo-check` | `codex exec resume <TID> P --json` |

Read `src/opa/rlm/adapters/claude_code.py` — it is about 120 lines including the
comments.

## Registering

Add the class to `ADAPTERS` in `src/opa/rlm/spawn.py`. It becomes usable as
`rlm(..., adapter="your-name")` and as `OPA_DEFAULT_ADAPTER`.

## Testing without burning quota

`tests/test_adapters.py` verifies command assembly and output parsing without
invoking anything, and `tests/test_rlm_service.py` drives the whole service
through a fake adapter. Only `tests/test_rlm_integration.py` spawns a real
child, and it is excluded from the default run:

```bash
uv run pytest -q            # no CLI is invoked
uv run pytest -q -m child   # spawns a real agent; needs auth and quota
```

Please add both kinds for a new adapter: parsing tests that always run, and one
integration test marked `child`.
