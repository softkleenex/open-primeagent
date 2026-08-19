# TODO

> 세션 간 컨텍스트 유지용. 새 세션은 여기부터 읽는다.

## 현재 상황 (2026-08-19)

**Phase 0 ✅ / Phase 1 ✅ / Phase 2 ✅.** RLM이 실제로 동작한다.
실제 claude child로 확인: `rlm()`이 논블로킹으로 핸들 반환 → 결과가 메일박스로
도착 → **부모 커널 재시작 후에도** child가 registry에 남아있고, `agent_message.send`로
재호출하면 재시작 이전 턴을 기억한 채 답한다. 테스트 63 passed (+ child 1).

확정된 결정:
- 언어: Python + uv / 전달: MCP 서버 1개 = 모든 에이전트
- 커널↔호스트 브릿지: **Unix socket JSONL RPC**, 결과는 `result` 봉투 안에
  (평탄 병합하면 핸들러 키가 프로토콜 키를 덮어쓴다 — 실제로 터졌다)
- MCP 도구 4개 상한 (`server.MAX_TOOLS`, 테스트로 강제). 현재 3개
- 커널 트랜스포트: IPC 소켓 (경로 길이 초과 시 TCP 폴백)
- child 어댑터: `claude-code`(기본) · `codex`. 둘 다 resume 실측 확인
- child는 **명시적으로만** 삭제한다. 상주가 기본값

## 다음 할 일 — Phase 3 (Continual Harness)

1. `harness/state.py` — HarnessEntry CRUD, local/global scope,
   원본 `harness_state.json` 스키마 호환
2. `harness/projection.py` — **델리미터 블록 안에만 쓴다.**
   `tests/test_projection.py`의 skip 3개가 이걸 기다리고 있다
3. `opa_bootstrap` 도구 — 설치/갱신/제거(원상복구). 4번째이자 마지막 도구
4. `harness/refine.py` — trajectory → 최소 CRUD delta + history + rollback
5. child → parent push: child에 `--mcp-config`로 opa 부착 + `OPA_ROLE=child`

## 조사 필요

- [ ] **opencode** headless/resume 인터페이스 (`opencode run`? 세션 재개 방식?)
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

### 2026-08-19 — 코드리뷰에서 나온 결함 5건 (전부 재현 후 수정)

1. **브릿지가 64KB에서 깨짐.** `MAX_LINE_BYTES = 4MB` 는 죽은 코드였고 실제로는
   asyncio StreamReader의 기본 64KiB가 걸렸다. 70KB 요청은 `RuntimeError`,
   200KB는 `BrokenPipeError`. 응답도 같아서 자식 리포트가 쌓인 inbox가 터진다.
   → `start_unix_server(limit=)` / `open_unix_connection(limit=)` 양쪽에 지정.
2. **같은 child에 동시 resume.** 메시지 3개를 동시에 보내면 같은 세션 id로
   CLI 프로세스 3개가 동시에 떴다 (세션 파일 경쟁 → 컨텍스트 손상).
   → child별 `asyncio.Lock`. 메시지는 버리지 않고 줄을 세운다. child 간 병렬은 유지.
3. **실행 중 child 삭제 → 백그라운드 태스크가 `KeyError`로 사망**, 부모는 결과도
   실패도 못 받음. → `_safe_update` + 삭제 감지 시 `[dropped]` 메시지 전달.
   `add_done_callback`에서 예외를 회수하도록 수정.
4. **모르는 인자를 조용히 무시.** `rlm(prompt, name='x', moodel='opus')` 가 예외
   없이 통과하고 모델은 기본값으로 돌았다. → `SPAWN_KWARGS` 화이트리스트로 거절.
5. **cwd 가드가 심링크에서 오작동.** workspace 한쪽만 resolve 해서 `/tmp` 처럼
   심링크를 낀 workspace 안의 정상 경로가 거부됐다. → 양쪽 resolve.

### 2026-08-19 — 브릿지 프로토콜 키 shadowing
`rlm.run` 핸들러가 돌려준 `status: "running"` 이 응답에 평탄 병합되면서
프로토콜의 `status: "ok"` 를 덮어써, 클라이언트가
`unexpected status: 'running'` 으로 터졌다.
해결: 핸들러 결과를 `result` 봉투에 감싼다. 이름 규칙(예약어 금지)으로 막으면
언젠가 또 깨지므로 구조로 막았다. `tests/test_bridge.py`가 회귀를 잡는다.

### 2026-08-19 — codex가 stdin을 기다리며 멈춤
`codex exec ... --json` 을 파이프로 실행하면 `Reading additional input from
stdin...` 상태로 무한 대기. 원인: stdin이 TTY가 아니면 추가 입력으로 읽으려 한다.
해결: 어댑터에서 `stdin=DEVNULL`. claude 어댑터에도 같은 이유로 적용.
추가로 codex는 git 저장소 밖에서 `--skip-git-repo-check` 없이는 거부한다.

### 2026-08-19 — IPC 트랜스포트가 커널 부팅 실패
`AsyncKernelManager(transport="ipc", ip="")` 로 하면 60초 타임아웃.
원인: jupyter_client는 ipc에서 `ip`를 **소켓 경로 프리픽스**로 쓴다(`<ip>-1`~`<ip>-5`).
빈 문자열이라 소켓 생성 실패. 해결: 짧은 tempdir 경로를 ip로 넘기고,
macOS `sun_path` 104바이트 제한에 걸리면 TCP로 폴백.
