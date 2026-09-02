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
| claude child tools | `Bash,Read,Edit,Write,Grep,Glob` | a child that cannot run tests is half a sub-agent; narrow with `OPA_CHILD_ALLOWED_TOOLS` |
| `--dangerously-skip-permissions` | **off** | requires `OPA_ALLOW_DANGEROUS_CHILD=1` |
| codex child sandbox | `workspace-write` | no writes outside the workspace |
| child `cwd` | inside the workspace | cannot escape; both paths are resolved before comparison |
| bridge socket | `0600` | another local user cannot push commands into your kernel |
| bridge authority | per-caller token | a child may call one request type; the kernel may call all of them |
| child environment | built, not inherited | the server's other secrets do not travel to a child |
| child MCP servers | `--strict-mcp-config` | a child gets only what we hand it, never the user's registered servers |
| kernel transport | IPC socket | TCP sends code and output in cleartext on localhost |
| autonomous mode | off | it edits files without supervision |

**The socket is not the boundary.** `0600` keeps out other *users*. It does not
separate the kernel from a child, because a child runs as the same user and
holds the socket path. Authority comes from a per-caller token instead: a child's
token authorises `agent_message.send` to its parent and nothing else. Without
that, a prompt-injected child could write a harness entry and project it into
your own `CLAUDE.md` — a persistent, cross-session implant inside the delimiter
block we promise to control.

**Children can run shell commands by default.** This is deliberate — a sub-agent
that edits code but cannot run the tests is worse than useless — but it is a real
capability, and it is granted without anyone approving each command, because a
headless run has nobody to ask. Set `OPA_CHILD_ALLOWED_TOOLS=Read,Grep,Glob` for
a reviewer that only looks.

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
[concepts/evolution.md](concepts/evolution.md) §5. In short: the base system prompt is never
touched, every change is reversible, changes are delivered through tool
*descriptions* rather than tool *results*, and there is no automatic promotion
path where nothing can be measured.

## Reporting

If you find a vulnerability, please report it privately rather than opening a
public issue.
