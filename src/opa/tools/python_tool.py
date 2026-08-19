"""opa_python — 유일한 작업 도구.

호스트 에이전트가 하는 일의 90%가 여기로 들어온다.

    opa_python('''
    api  = await rlm("API 보안 검토", name="api-reviewer")
    test = await rlm("테스트 커버리지 분석", name="test-reviewer")
    ''')

응답은 잘려서 온다. 전문 경로가 함께 온다. 그게 요점이다.
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
"""
