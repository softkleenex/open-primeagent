# Runs the open-primeagent MCP server over stdio, built from this checkout.
#
# Used by registries that start the server in a container to check it lists its
# tools (Glama). For your own use, `uvx open-primeagent` is simpler: sub-agents
# need the `claude` or `codex` CLI, which this image does not include, so here
# the kernel, harness and projection work and spawning a child does not.
FROM python:3.12-slim

WORKDIR /src
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY src ./src
COPY runtime ./runtime
COPY skills ./skills
RUN pip install --no-cache-dir .

# The server treats its working directory as the workspace it projects into.
WORKDIR /workspace
ENTRYPOINT ["open-primeagent"]
