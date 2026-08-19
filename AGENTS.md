# 이 리포에서 일하는 에이전트를 위한 지침

## 프로젝트 한 줄

Prime Agent의 RLM을, **사용자가 쓰던 코딩 에이전트를 그대로 둔 채** 붙이는 MCP 서버.

## 먼저 읽을 것

1. `TODO.md` — 지금 상황과 다음 할 일
2. `ARCHITECTURE.md` — 왜 이렇게 설계했는지
3. `ROADMAP.md` — 현재 Phase의 exit criteria

## 절대 어기지 말 것

1. **호스트 에이전트를 대체하지 않는다.** 자체 TUI·세션 UI·provider 레이어·OAuth를
   만들려는 충동이 들면 그건 스코프 밖이다. 호스트에 위임한다.
2. **MCP 도구는 4개를 넘기지 않는다.** 새 기능은 커널 안 Python 심볼로 노출한다.
   도구를 늘리면 호스트의 도구 목록을 오염시키고, 이 프로젝트의 철학과 정반대가 된다.
3. **projection은 델리미터 블록 안에만 쓴다.** 사용자가 쓴 `CLAUDE.md` 내용을
   한 글자도 바꾸지 않는다. 이 약속이 프로젝트의 전제다.
4. **`_ref/` 는 읽기 전용 참조다.** 커밋되지 않고, 코드를 복사해오지 않는다.
   독립 재구현이지 포크가 아니다.

## 작업 규칙

- Phase exit criteria는 **실제로 실행해서** 확인한다. "아마 될 것이다"는 안 된다.
- Phase 순서를 건너뛰지 않는다. L2는 L1 없이 의미가 없다.
- 새로 알게 된 것(특히 호스트 CLI의 실제 동작)은 `TODO.md`의 조사 항목에서 지운다.

## 원본 참조 위치

| 무엇 | 경로 |
|---|---|
| rlm API 표면 (348줄, 전부) | `_ref/prime-agent/prime-agent-runtime/src/rlm/__init__.py` |
| harness 스토어 스키마 | `_ref/prime-agent/prime-agent-runtime/src/rlm/harness.py` |
| 스킬 13종 | `_ref/prime-agent/packages/coding-agent/skills/` |
