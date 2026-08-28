# Documentation

**New here?** [Quickstart](quickstart.md) gets you running in about two minutes.

## Install

| host | guide |
|---|---|
| Claude Code | [install/claude-code.md](install/claude-code.md) |
| Codex | [install/codex.md](install/codex.md) |
| opencode | [install/opencode.md](install/opencode.md) |

Any MCP client works — those pages just spell out the registration syntax.

## Concepts

Read in this order; each layer depends on the one before it.

| | |
|---|---|
| [Persistent Python](concepts/persistent-python.md) | the kernel as external working memory |
| [RLM](concepts/rlm.md) | sub-agent sessions that are not disposable |
| [Continual harness](concepts/harness.md) | prompts, memory, skills, and how they reach your agent |
| [Long-running work](concepts/long-run.md) | goal, schedule, and the autonomous gate loop |
| [Evolution](concepts/evolution.md) | what self-improvement can actually reach, measured |

## Reference

| | |
|---|---|
| [MCP tools](reference/tools.md) | the four tools, and why there are only four |
| [Kernel API](reference/kernel-api.md) | `rlm`, `agent_message`, `harness` |
| [Configuration](reference/configuration.md) | every environment variable |
| [Writing an adapter](reference/adapters.md) | adding a child backend |

## Project

| | |
|---|---|
| [Architecture](architecture.md) | layers, the host bridge, projection |
| [Roadmap](roadmap.md) | phases with executable exit criteria |
| [Benchmarks](../bench/README.md) | measured results, including the ones we lost |
| [Security](security.md) | **read this before enabling anything autonomous** |
| [Contributing](../CONTRIBUTING.md) | |
