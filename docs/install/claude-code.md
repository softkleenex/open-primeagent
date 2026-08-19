# Claude Code

```bash
claude mcp add opa -- uvx open-primeagent
```

Or from a local checkout:

```bash
claude mcp add opa -- uv run --directory /path/to/open_primeagent opa
```

Verify:

```
/mcp        # opa, with four tools: opa_python / opa_status / opa_kernel / opa_bootstrap
```

## Optional: install the harness projection

```
opa_bootstrap()             # writes an opa block into CLAUDE.md, installs .claude/skills
opa_bootstrap(remove=True)  # restores every touched file exactly
```

Nothing outside the delimiter block is modified, and skills you wrote yourself
are never removed.

## Environment variables

| variable | default | meaning |
|---|---|---|
| `OPA_WORKSPACE` | `cwd` | work root |
| `OPA_ROOT` | `<workspace>/.opa` | per-project state |
| `OPA_GLOBAL_ROOT` | `~/.opa` | state shared across projects |
| `OPA_MAX_OUTPUT_CHARS` | `4000` | how much output reaches the model |
| `OPA_DEFAULT_ADAPTER` | `claude-code` | child backend |
| `OPA_CHILD_PERMISSION_MODE` | `acceptEdits` | child permissions |
| `OPA_ALLOW_DANGEROUS_CHILD` | unset | `1` lets children bypass permission checks |
