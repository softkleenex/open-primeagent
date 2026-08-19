# Security

## In one line

**This is not a sandbox.**

Python executed in the kernel, and shell commands executed by child agents, run
with **your OS permissions**. Upstream Prime Agent states the same about its
kernel and workers; we add child spawning on top, so the blast radius is larger.

```
host agent → opa MCP → persistent Python → shell → filesystem
                     └→ child agents     → shell → filesystem
```

The more capable the agent, the wider the damage radius of prompt injection, a
malicious repository, or a malicious skill.

## Defaults

| item | default | why |
|---|---|---|
| claude child permissions | `acceptEdits` | bypass is explicit opt-in only |
| `--dangerously-skip-permissions` | **off** | requires `OPA_ALLOW_DANGEROUS_CHILD=1` |
| codex child sandbox | `workspace-write` | no writes outside the workspace |
| child `cwd` | inside the workspace | cannot escape; both paths are resolved before comparison |
| bridge socket | `0600` | another local user cannot push commands into your kernel |
| kernel transport | IPC socket | TCP sends code and output in cleartext on localhost |
| autonomous mode | off | it edits files without supervision |

## When you need a container

Run inside a devcontainer / VM / Docker if **any** of these apply:

- You are working on a repository you do not trust
- The agent will read instructions from outside (issue bodies, PR descriptions, web pages)
- You are enabling **long autonomous runs**
- You are installing third-party skills

## The promise we keep

`opa_bootstrap` writes **only inside the delimiter block**:

```markdown
<!-- opa:begin -->
...
<!-- opa:end -->
```

Content outside the block in `CLAUDE.md` / `AGENTS.md` is preserved byte for
byte, and skill directories that lack our `.opa-managed` marker are never
touched. `opa_bootstrap(remove=True)` restores everything.

This is not a documentation promise — `tests/test_projection.py` and
`tests/test_bootstrap.py` enforce it.

## A note on self-modification

An agent that rewrites its own operating instructions is a real risk surface.
Our position, and the reasoning behind it, is in
[evolution.md](evolution.md) §5. In short: the base system prompt is never
touched, every change is reversible, changes are delivered through tool
*descriptions* rather than tool *results*, and there is no automatic promotion
path where nothing can be measured.

## Reporting

If you find a vulnerability, please report it privately rather than opening a
public issue.
