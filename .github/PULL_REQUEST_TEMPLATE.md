## What and why

## How it was verified

<!-- Commands you actually ran, and their output. "Should work" does not count. -->

```
uv run pytest -q
uv run ruff check .
```

## Checklist

- [ ] Tests cover the change; a bug fix has a test that fails without it
- [ ] No new MCP tool (`MAX_TOOLS` is still 4)
- [ ] Projection still writes only inside the delimiter block
- [ ] If something got measurably worse, the commit message says so
