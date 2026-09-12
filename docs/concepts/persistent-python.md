# Persistent Python

> The model's context is for **deciding**. Python is for **holding**.

A coding agent spends much of its context on data it does not need to reason
about: file listings, grep output, JSON blobs, the thirty results it will filter
down to three. That data has to be there because tool results have nowhere else
to live.

open-primeagent gives it somewhere else to live.

```python
opa_python("files = [p for p in Path('.').rglob('*.py')]")   # 500 paths
opa_python("graph = build_dependency_graph(files)")          # 30 KB structure
opa_python("[f.name for f in suspicious(graph)][:5]")        # the model sees 5 names
```

State survives across calls, across turns, and across your own context
compaction. Only the kernel process holds it, so a kernel restart clears it —
which is why everything that *must* survive (the sub-agent registry, the
harness, the goal) lives on the host's disk instead.

## Output is truncated on purpose

A cell's output is capped at `OPA_MAX_OUTPUT_CHARS` (4000 by default). The full
text is written to `<session>/outputs/<n>.txt` and the truncation marker carries
the path, so nothing is lost — it is just not in your context unless you ask.

Truncation keeps **head and tail**, never head alone. The real cause of a Python
traceback is on its last line; a head-only cut removes exactly the part you
needed.

ANSI colour codes are stripped from tracebacks. IPython emits them, and to a
model they are noise that costs tokens.

## Practical notes

- Top-level `await` works. IPython's autoawait handles it natively — upstream
  Prime Agent uses `nest_asyncio` for this and we measured that it is
  unnecessary.
- The kernel boots **lazily**, on your first `opa_python` call. Registering the
  MCP server costs you nothing until you use it.
- The kernel runs under the server's own interpreter, via a kernelspec we write
  ourselves. Relying on your installed kernelspec would boot a Python without
  `opa_runtime`, and the `rlm` symbols would silently disappear.
- On POSIX the kernel talks over an **IPC socket**, not TCP. TCP puts kernel code
  and output in cleartext on localhost; ipykernel warns about this itself.

## An honest limit

A shell is *already* an external computer. For anything a `grep -c | sort`
one-liner solves, the kernel buys you nothing and costs you a tool round trip —
we [measured that and published the loss](../../bench/README.md#3-multi-turn-corpus-analysis---opa-loses).

That limit turned out to be wider than we thought. We built two more benchmarks
on the theory that the kernel earns its place once intermediate state is
expensive to rebuild and gets reused across turns — an import graph over 600
modules, then an 8-million-row file — and then counted what the agent had
actually called:

| benchmark | opa-arm sessions | sessions that ran `opa_python` |
|---|---:|---:|
| import graph | 96 | **0** |
| 8M-row file | 27 | **0** |

Given a shell, the agent reaches for `awk`, and a streaming aggregation never
materialises the structure a kernel exists to hold. It was not a worse choice
than the kernel; it was the right one.

So the honest statement of what this is for:

> The kernel is **external working memory**, not a speed-up. Its cost has been
> measured and is approximately zero. Its benefit has not been measured at all,
> because in 123 sessions across two benchmarks designed to elicit it, the agent
> never once chose it.

Where it is load-bearing regardless of that: `rlm` handles, the harness API and
the long-run symbols live in this kernel, and they have to survive a compaction
that your context does not. That is a correctness property rather than a
performance one, and it is what the kernel is actually carrying today.

Where it might still pay, untested: state that cannot be streamed out of a file
— a loaded model, an open connection, a GPU context. If you have that case,
[the benchmarks](../../bench/README.md) are designed to be copied.
