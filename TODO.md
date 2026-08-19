# TODO

> 세션 간 컨텍스트 유지용. 새 세션은 여기부터 읽는다.

## 현재 상황 (2026-08-19)

Phase 0 진행중. 설계 확정 + 리포 골격 완료. **코드는 전부 스텁이다.**

확정된 결정:
- 언어: Python + uv (커널이 IPython이라 shim을 in-process로 두는 게 유일하게 깔끔)
- 전달: MCP 서버 1개 = 모든 에이전트 (claude code / codex / opencode)
- child 백엔드: claude-code 우선, 어댑터로 확장
- 커널↔호스트 브릿지: Jupyter comm ❌ → **Unix socket JSONL RPC** ✅
- MCP 도구 4개로 고정, 나머지는 커널 안 Python 심볼

검증 완료 (실행해서 확인함):
- `uv sync --extra dev` 통과, 워크스페이스 멤버 `opa-runtime` 연결됨
- 전 모듈 import 통과, `ruff check` 통과, `pytest` 수집 통과 (3 skip = Phase 3 자리)
- `.python-version` = 3.12 로 고정 (uv가 3.12.11 선택)

## 다음 할 일 (우선순위 순)

1. `src/opa/server.py` — MCP handshake. **Phase 0 Exit의 마지막 항목.**
   현재 `main()`은 의도적으로 `NotImplementedError`.
2. `src/opa/kernel/manager.py` — 커널 부팅/실행/재시작
3. `opa_python` 도구 — 출력 잘라내기 + 전문 파일 저장 (`kernel/exec.py:truncate`)
4. Phase 1 Exit criteria 3개 실제로 돌려서 확인

## 조사 필요

- [ ] **opencode** headless/resume 인터페이스 (`opencode run`? 세션 재개 방식?)
- [ ] `claude --output-format json`의 usage 필드로 child 토큰 회계가 되는가
- [ ] child에 `--mcp-config`로 opa를 붙일 때 재귀 spawn 깊이 제한 방법
- [ ] `nest_asyncio`가 실제 IPython 커널에서 top-level await를 물어주는지 (3.12 기준)

## 참고 파일

| 경로 | 왜 |
|---|---|
| `_ref/prime-agent/prime-agent-runtime/src/rlm/__init__.py` | rlm API 표면 전체 (348줄) |
| `_ref/prime-agent/prime-agent-runtime/src/rlm/harness.py` | harness 스토어 스키마 (820줄) |
| `_ref/prime-agent/packages/coding-agent/skills/` | 원본 스킬 13종 (goal/refine/agent-message/rlm-heartbeat) |
| `_ref/prime-agent/AGENTS.md` | 원본이 자기 에이전트에게 주는 지침 |

## 이슈 기록

*(발생 시 여기에. 문제 → 원인 → 해결)*
