---
name: refine
description: 이번 작업 기록(trajectory)을 보고 harness(프롬프트 노트/메모리/스킬/서브에이전트 스펙)에 최소 변경을 적용해 다음 작업이 더 잘 되게 만든다.
---

# Refine

"self-improving"은 모델 weight가 아니라 **harness**가 개선되는 것이다.

```python
await harness.refine(dry_run=True)   # 제안만 본다
await harness.refine()               # 적용 + history 기록
await harness.rollback(event_id)     # 되돌린다
```

## 승격 판단

한 번 겪은 일은 승격하지 않는다. **반복해서 나타난 패턴만** 올린다.

| 발견한 것 | 어디로 |
|---|---|
| 이 프로젝트에서 항상 지켜야 하는 절차 | `prompt` |
| 특정 사실 (포트, 경로, 담당자, 결정 이유) | `memory` |
| 반복 실행되는 절차 | `skill` |
| 특정 역할이 늘 필요한 컨텍스트 | `subagent` 스펙 |

## 규칙

- **최소 변경.** 큰 리라이트가 아니라 작은 CRUD delta.
- base system prompt는 건드리지 않는다.
- 모든 변경은 rollback 가능해야 한다.
