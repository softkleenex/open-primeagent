---
name: goal
description: 끝날 때까지 유지되는 persistent goal을 읽고, 사용자가 명시적으로 요청할 때 시작하고, 목표가 실제로 달성됐을 때 완료 처리한다.
---

# Goal

```python
await goal.get()
await goal.create("서비스 전체 성능을 개선하고 테스트를 통과시켜라", token_budget=200000)
await goal.complete()
```

## 규칙

- 사용자가 **명시적으로** 장기 목표를 요청할 때만 `create`. 평범한 작업을 goal로 만들지 않는다.
- 목표가 **실제로 달성됐을 때만** `complete`. 예산이 떨어졌다는 이유로 완료하지 않는다.
- "다 됐습니다"라고 말하는 것으로는 끝나지 않는다. `complete()` 호출이 와야 끝난다.
