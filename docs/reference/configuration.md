# Configuration

Every setting arrives as an environment variable on the MCP server registration
line. There is no config file, because adding one would mean asking you to
change your environment.

```bash
claude mcp add opa \
  --env OPA_MAX_OUTPUT_CHARS=8000 \
  --env OPA_DEFAULT_ADAPTER=codex \
  -- uvx open-primeagent
```

## Paths

| variable | default | meaning |
|---|---|---|
| `OPA_WORKSPACE` | current directory | the work root. Child agents cannot escape it. |
| `OPA_ROOT` | `<workspace>/.opa` | per-project state: sessions, trajectory, harness, children |
| `OPA_GLOBAL_ROOT` | `~/.opa` | state shared across projects (`global` harness scope) |

Add `.opa/` to your `.gitignore`.

## Kernel

| variable | default | meaning |
|---|---|---|
| `OPA_MAX_OUTPUT_CHARS` | `4000` | how much of a cell's output reaches the model. The rest is written to `<session>/outputs/` and referenced by path. |

Raise it when you are debugging and want more traceback inline; lower it when
you are working through very noisy tooling.

## Child agents

| variable | default | meaning |
|---|---|---|
| `OPA_DEFAULT_ADAPTER` | `claude-code` | backend used when `rlm(...)` does not name one |
| `OPA_CHILD_PERMISSION_MODE` | `acceptEdits` | passed to `claude --permission-mode` |
| `OPA_ALLOW_DANGEROUS_CHILD` | unset | `1` lets children bypass permission checks entirely |

`OPA_ALLOW_DANGEROUS_CHILD=1` gives children
`--dangerously-skip-permissions` (claude) or
`--dangerously-bypass-approvals-and-sandbox` (codex). Read
[security.md](../security.md) first; without it, codex children run under
`--sandbox workspace-write`.

## Set by us, for processes we start

You do not set these; the server injects them into the kernel and into child
processes.

| variable | meaning |
|---|---|
| `OPA_HOST_SOCKET` | Unix socket for calling back into the host |
| `OPA_SESSION_DIR` | the current session directory |
| `OPA_ROLE` | `parent` in the kernel; `child` in spawned agents |
| `OPA_CHILD_NAME` | the spawned child's registry name, used when it messages the parent |

A child inherits `OPA_HOST_SOCKET`, which is what will let it message its parent
mid-run.
