# ROADMAP

의존 순서가 곧 구현 순서다: **Persistent REPL → Persistent Subagents → Continual Harness → Long-run.**
아래로 갈수록 위 단계가 없으면 의미가 없다.

각 Phase는 **직접 실행해서 확인한 Exit criteria**를 통과해야 다음으로 간다.

---

## Phase 0 — 골격 · 결정 확정  ✅ 완료

- [x] 원본 레포 실측 분석 (`_ref/prime-agent`)
- [x] 호스트 CLI 어댑터 계약 검증 (claude / codex의 session-id · resume · json)
- [x] ARCHITECTURE / ROADMAP / TODO
- [x] `uv sync` 통과, `opa` 엔트리포인트가 MCP handshake 응답

**Exit ✅**: `claude mcp add opa --scope local -- uv run --directory <repo> opa` →
`claude mcp list` 에서 `opa: ✔ Connected`. MCP stdio 클라이언트로도 handshake 확인
(`server: opa 0.0.1`, tools 3개).

---

## Phase 1 — Persistent Python  (L1)  ✅ 완료

핵심 가치 하나: *LLM 컨텍스트를 창고로 쓰지 않는다.*

- [x] `KernelManager` — 세션당 IPython 커널 1개, 부팅/재시작/인터럽트
- [x] `opa_python` 도구 — 실행 · 출력 캡처 · **잘라내기 + 전문 파일 저장**
- [x] ~~`nest_asyncio` 주입~~ → IPython autoawait가 네이티브로 처리. 의존성 제거
- [x] 세션 디렉터리 규약 + JSONL trajectory 기록
- [x] `opa_status` / `opa_kernel`

**Exit ✅** (`tests/test_kernel_integration.py` 가 셋 다 강제):
1. ✅ 셀 A의 `files`(500개) → 셀 B에서 `len(files)` == 500
2. ✅ 30KB 출력 → limit만큼만 반환, 전문은 `outputs/00000.txt`
3. ✅ restart 후 변수 소멸, `trajectory.jsonl`과 `rlm` 심볼은 유지

추가로 확인한 것:
- 커널 트랜스포트를 **IPC 소켓**으로 (TCP는 코드/출력을 로컬 평문으로 흘린다).
  경로 길이 제한에 걸리면 TCP로 폴백.
- traceback의 ANSI 코드 제거 — 모델 컨텍스트에 잡음이 안 들어가게
- 잘라낼 때 **꼬리를 반드시 남긴다** — traceback의 실제 원인은 마지막 줄에 있다
- 커널은 **지연 부팅** — MCP 서버가 떴다는 이유만으로 커널을 올리지 않는다

---

## Phase 2 — RLM: persistent subagents  (L2)  ✅ 완료

이 프로젝트의 존재 이유.

- [x] `HostBridge` — Unix socket JSONL RPC (커널 없이 단독 테스트 가능)
- [x] `opa_runtime` shim — 커널 안 `rlm` 심볼 (`rlm(...)`, `list_subagents`, `delete_subagent`)
- [x] `AgentAdapter` 프로토콜 + `claude-code` 어댑터
- [x] `ChildRegistry` — 디스크 영속, 커널/호스트 재시작 후 복구
- [x] `agent_message` — 메일박스, parent→child 재개(resume)
- [x] `codex` 어댑터

**Exit ✅** (`tests/test_rlm_integration.py`, 실제 claude child로 확인):
1. ✅ `await rlm(...)`가 0.6초에 핸들 반환 — child는 백그라운드에서 계속 돈다
2. ✅ 커널 재시작 후에도 `list_subagents()`에 그대로 남아있다
3. ✅ `agent_message.send(...)` → child가 **재시작 이전 턴의 토큰을 기억하고** 답했다
4. ✅ claude / codex 두 어댑터 모두 resume 동작 확인 (BETA-9 재현)

발견해서 고친 것:
- **프로토콜 키 shadowing**: 핸들러의 `status:"running"`이 프로토콜 `status:"ok"`를
  덮어써서 클라이언트가 터졌다 → 결과를 `result` 봉투 안에 넣어 구조로 차단
- 두 CLI 모두 **stdin을 닫아야** 한다 (codex는 열려 있으면 무한 대기)
- codex는 git 저장소 밖에서 `--skip-git-repo-check` 필요

---

## Phase 3 — Continual Harness  (L3)

- [ ] `HarnessState` CRUD (원본 `harness_state.json` 스키마 호환)
- [ ] local / global scope
- [ ] **projection** — 델리미터 블록으로만 `CLAUDE.md` / `AGENTS.md` 갱신
- [ ] skill 설치: `SKILL.md` 배포 + python 패키지 `uv pip install -e` → 커널
- [ ] `harness.refine(trajectory)` — 최소 CRUD delta + history + rollback
- [ ] `opa_bootstrap()` — 호스트별 설치/갱신
- [ ] child → parent push (child에 opa MCP 부착, `OPA_ROLE=child`)

**Exit**:
1. 새 노하우가 `prompt` 엔트리로 승격되고, 다음 세션에서 호스트가 그걸 읽는다.
2. projection이 델리미터 **밖** 사용자 내용을 한 글자도 바꾸지 않는다 (테스트로 강제).
3. refine 결과를 rollback하면 이전 상태로 정확히 되돌아간다.

---

## Phase 4 — Long-run  (L4)

- [ ] `goal` — create / get / complete, token budget 회계
- [ ] `heartbeat` — 사용자용 / `rlm_heartbeat`(에이전트 자율) 분리
- [ ] `schedule` — one-time · cron
- [ ] autonomous: max turns / token budget / wall-clock + quality gate
- [ ] gate 실패 출력을 다음 입력으로 되먹임

**Exit**: 목표 하나를 주면 gate 통과까지 사람 개입 없이 여러 child를 오가며 수렴한다.

---

## Phase 5 — 배포

- [ ] `uvx open-primeagent` 원샷 실행
- [ ] `install/claude-code.md` · `codex.md` · `opencode.md`
- [ ] Claude Code 플러그인 (`/opa:refine`, `/opa:goal`, `/opa:status`)
- [ ] `docs/security.md` — sandbox 아님 명시, devcontainer 권장
- [ ] 예제: 4-specialist 상주 팀 시나리오

---

## 비목표 (Non-goals)

명시적으로 **안 하는 것**:

- 자체 TUI / 세션 UI — 호스트가 이미 있다
- 자체 모델 provider 레이어 / OAuth — 호스트 CLI에 위임
- 모델 fine-tuning — "self-improving"은 harness의 개선이지 weight가 아니다
- prime-agent와의 기능 1:1 패리티 — 우리는 **이식 가능한 RLM 코어**만 목표
