# Security

## Reporting a vulnerability

Please report privately rather than opening a public issue — open a GitHub
security advisory on this repository, or contact the maintainer directly.

## Before you report: this is not a sandbox

open-primeagent runs model-generated Python in an IPython kernel and spawns
coding-agent CLIs as child processes. Both run **with your OS permissions**.
That is by design and is documented in
[docs/security.md](docs/security.md), which also lists the defaults we ship and
when you should be running inside a container.

So "the agent can read my files" or "the kernel can run shell commands" is not a
vulnerability — it is the tool working as described.

What we *do* want to hear about:

- a way to escape the delimiter block and modify a user's own `CLAUDE.md`
  content, or to delete skills we did not create
- a child escaping the workspace `cwd` restriction
- the host bridge socket being reachable by another local user, or accepting
  requests it should not
- anything that turns reading an untrusted repository into code execution
  *without* the user having enabled an autonomous mode
- injection through harness entries, mailbox messages, or child output that
  changes host behaviour outside the documented channels
