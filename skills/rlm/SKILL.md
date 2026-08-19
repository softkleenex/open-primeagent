---
name: rlm
description: persistent Python 커널에서 장기 상주 서브에이전트를 함수처럼 만들고 재호출한다. 병렬 조사, 전문가 팀 구성, 이전에 일했던 에이전트에게 후속 작업을 줄 때 사용.
---

# RLM

`opa_python` 도구 안에서 쓴다. `rlm(...)`은 LLM API 호출이 아니라
**독립된 에이전트 세션**을 만든다.

```python
api  = await rlm("API 코드의 보안 문제를 찾아라", name="api-reviewer")
test = await rlm("테스트 커버리지를 분석해라",     name="test-reviewer")
```

`rlm(...)`은 **기다리지 않는다.** 핸들만 돌아오고 child는 백그라운드에서 계속 돈다.

결과는 부모 메일박스로 온다 (호스트의 턴 루프를 소유하지 않으므로 pull이다):

```python
for m in await agent_message.inbox():
    print(m["sender"], m["message"][:200])
```

## child는 일회용이 아니다

```python
children = await rlm.list_subagents()      # 커널 재시작 후에도 그대로 있다

await agent_message.send(
    "방금 수정한 코드까지 다시 검사해",
    receiver_role="child", receiver_name="api-reviewer",
)   # 이전 컨텍스트를 유지한 채 이어서 일한다
```

새 child를 만들기 전에 **먼저 `list_subagents()`로 기존 child를 찾아라.**
같은 영역을 이미 아는 에이전트가 있으면 그쪽에 후속 작업을 주는 게 항상 낫다.

## 규칙

- `name`은 역할로 짓는다 (`backend`, `security`, `flutter`). 상주할 이름이다.
- 일이 끝났다고 지우지 않는다. `delete_subagent`는 명시적으로 필요할 때만.
- 다른 모델을 섞을 수 있다: `adapter="codex"`, `model=...`.
