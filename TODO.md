# TODO

> 세션 간 컨텍스트 유지용. 새 세션은 여기부터 읽는다.

## 현재 상황 (2026-08-19)

**Phase 0 ✅ / Phase 1 ✅ 완료.** L0(세션/JSONL) · L1(persistent 커널) 동작한다.
Claude Code에 실제로 붙여서 `opa: ✔ Connected` 확인했고, 테스트 25개가 통과한다.

확정된 결정:
- 언어: Python + uv (커널이 IPython이라 shim을 in-process로 두는 게 유일하게 깔끔)
- 전달: MCP 서버 1개 = 모든 에이전트 (claude code / codex / opencode)
- child 백엔드: claude-code 우선, 어댑터로 확장
- 커널↔호스트 브릿지: Jupyter comm ❌ → **Unix socket JSONL RPC** ✅
- MCP 도구 4개 상한 (`server.MAX_TOOLS`, 테스트로 강제). 현재 3개 구현,
  `opa_bootstrap`은 Phase 3에서 추가
- 커널 트랜스포트: IPC 소켓 (경로 길이 초과 시 TCP 폴백)
- `nest_asyncio` **불필요** — IPython autoawait가 top-level await를 네이티브 처리

## 다음 할 일 — Phase 2 (RLM)

1. `src/opa/bridge.py` `HostBridge` — Unix socket JSONL RPC 서버.
   커널 없이 단독으로 테스트 가능하게 먼저 만든다.
2. `runtime/src/opa_runtime/client.py` `host_request` — 소켓 클라이언트 쪽.
3. `rlm/adapters/claude_code.py` — spawn/resume. UUID를 우리가 발급한다.
4. `rlm/registry.py` — 디스크 영속. **커널 재시작 후 복구**가 핵심.
5. `rlm/spawn.py` — 논블로킹. 핸들만 반환하고 child는 백그라운드.
6. `rlm/message.py` — 메일박스 + parent→child resume.

Phase 2 Exit criteria는 ROADMAP 참조. 특히 3번(이전 컨텍스트를 유지한 채 이어서
답한다)이 이 프로젝트가 실제로 동작하는지의 유일한 증거다.

## 조사 필요

- [ ] **opencode** headless/resume 인터페이스 (`opencode run`? 세션 재개 방식?)
- [ ] `claude --output-format json`의 usage 필드로 child 토큰 회계가 되는가
- [ ] child에 `--mcp-config`로 opa를 붙일 때 재귀 spawn 깊이 제한 방법

## 참고 파일

| 경로 | 왜 |
|---|---|
| `_ref/prime-agent/prime-agent-runtime/src/rlm/__init__.py` | rlm API 표면 전체 (348줄) |
| `_ref/prime-agent/prime-agent-runtime/src/rlm/harness.py` | harness 스토어 스키마 (820줄) |
| `_ref/prime-agent/packages/coding-agent/skills/` | 원본 스킬 13종 (goal/refine/agent-message/rlm-heartbeat) |
| `_ref/prime-agent/AGENTS.md` | 원본이 자기 에이전트에게 주는 지침 |

## 이슈 기록

### 2026-08-19 — 커밋 신원이 잘못 박힘
Phase 0 커밋 2개가 `heyeun9858@gmail.com`(Claude 계정 이메일) author로 생성됨.
push 전이라 `git rebase --root --exec 'git commit --amend --no-edit --reset-author'`
로 정정. 이후 `~/.gitconfig` 값(`softkleenex1217@gmail.com`)만 사용한다.

### 2026-08-19 — IPC 트랜스포트가 커널 부팅 실패
`AsyncKernelManager(transport="ipc", ip="")` 로 하면 60초 타임아웃.
원인: jupyter_client는 ipc에서 `ip`를 **소켓 경로 프리픽스**로 쓴다(`<ip>-1`~`<ip>-5`).
빈 문자열이라 소켓 생성 실패. 해결: 짧은 tempdir 경로를 ip로 넘기고,
macOS `sun_path` 104바이트 제한에 걸리면 TCP로 폴백.
