"""opa_python - the only work tool.

Almost everything the host agent does goes through here.

    opa_python('''
    api  = await rlm("audit the API layer", name="api-reviewer")
    test = await rlm("map test coverage gaps", name="test-reviewer")
    ''')

The reply is truncated and carries the path to the full text. That is the point.
"""

DESCRIPTION = """\
Execute Python in a persistent IPython kernel. State (variables, imports,
functions) survives across calls and across your own context compaction.

Preloaded symbols — use these instead of asking for more tools:
  rlm(prompt, name=...)            spawn a persistent sub-agent session
  rlm.list_subagents()             recover sub-agents created earlier
  rlm.delete_subagent(name)        remove one
  agent_message.send(...)          re-task an existing sub-agent (keeps its context)
  harness.*                        prompts / memory / skills / subagent specs
  goal.*                           persistent objective

Keep large intermediate data (file lists, search results, graphs) in Python
variables rather than in your context. Print only what you need to decide on.
Output is truncated; the full text is written to a file whose path is returned.

Spawning a sub-agent is expensive: each one is a full coding-agent session and
costs roughly 36k tokens before it reads any of your code. Hand work to a child
only when that work would cost you more than that in your own context, and
prefer re-tasking an existing child over creating a new one.
"""
