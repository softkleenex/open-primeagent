# ARCHITECTURE

> `open-primeagent` (패키지명 `opa`) — Prime Agent의 RLM 아키텍처를,
> 사용자가 **쓰던 코딩 에이전트를 그대로 둔 채** 붙일 수 있는 형태로 옮긴 것.

---

## 0. 설계 제약

이 프로젝트를 규정하는 단 하나의 제약:

> **호스트 에이전트를 대체하지 않는다.**
> Claude Code / Codex / opencode 사용자가 자기 환경·인증·설정·스킬을 유지한 채,
> MCP 서버 한 줄 등록만으로 RLM을 얻는다.

여기서 따라 나오는 결론들:

| | Prime Agent | open-primeagent |
|---|---|---|
| 호스트 | 자체 TS harness (117k LOC) | **사용자가 이미 쓰는 에이전트** |
| 시스템 프롬프트 | 소유함 | 소유 못 함 → *투영(projection)*으로 우회 |
| 커널 브릿지 | Jupyter comm → TS 호스트 | Unix socket → MCP 서버 |
| child 세션 | 자체 세션 매니저 | 호스트 CLI의 `--session-id` / `resume` |
| 모델 선택 | 자체 provider 레이어 | 호스트 CLI에 위임 (`--model`) |

우리가 실제로 새로 만드는 것은 **RLM 런타임뿐**이고, 그 외 전부는 호스트에 위임한다.

### 원본 분석에서 얻은 근거

`_ref/prime-agent` 실측:

```
packages/coding-agent   117,690 LOC (TS)   호스트 harness / 세션 / TUI / CLI
packages/ai              35,332 LOC (TS)   provider + OAuth + MCP
packages/tui             14,635 LOC (TS)   터미널 UI
prime-agent-runtime       1,536 LOC (Py)   ← rlm 커널 shim (전부)
```

`prime-agent-runtime/src/rlm/__init__.py`는 348줄이고 내용은 전부
`await host_request("rlm.run", ...)` 형태의 얇은 RPC 래퍼다.
`harness.py`(820줄)는 `harness_state.json`에 대한 CRUD 스토어일 뿐이다.

**즉 RLM의 개념적 핵심은 1.5k LOC 안에 있고, 나머지는 harness 구현 세부사항이다.**
호스트를 위임하면 이 프로젝트는 현실적인 규모가 된다.

---

## 1. 레이어

```
┌──────────────────────────────────────────────────────────────┐
│  L4  Long-run     goal / heartbeat / schedule / autonomous   │
├──────────────────────────────────────────────────────────────┤
│  L3  Continual Harness   H = (ρ prompts, G subagents,        │
│                               K skills,   M memory)          │
│                          + projection → 호스트가 읽는 파일    │
├──────────────────────────────────────────────────────────────┤
│  L2  RLM          persistent subagents + A2A messaging       │
│                   ├ registry (재시작 후에도 복구)             │
│                   └ adapters: claude-code / codex / opencode │
├──────────────────────────────────────────────────────────────┤
│  L1  Persistent Python   IPython 커널 + 외부 작업 메모리      │
├──────────────────────────────────────────────────────────────┤
│  L0  Session & Store     session dir / JSONL trajectory      │
└──────────────────────────────────────────────────────────────┘
```

의존 방향은 위→아래 단방향. L1 없이 L2 없고, L2 없이 L3의 `G`가 의미 없다.
구현 순서도 동일하다 (ROADMAP 참조).

---

## 2. 런타임 토폴로지

```
        사용자가 쓰던 코딩 에이전트 (Claude Code / Codex / opencode …)
                              │
                              │  MCP (stdio)
                              ▼
        ┌───────────────────────────────────────────┐
        │            opa MCP 서버 (호스트)           │
        │                                           │
        │   tools:  opa_python  opa_status          │
        │           opa_kernel  opa_bootstrap       │
        │                                           │
        │   ┌─────────────┐    ┌──────────────────┐ │
        │   │ HostBridge  │◄──►│ RLM registry     │ │
        │   │ (unix sock) │    │ harness store    │ │
        │   └──────▲──────┘    │ goal / schedule  │ │
        │          │           └──────────────────┘ │
        └──────────┼────────────────────────────────┘
                   │ JSONL RPC over $OPA_HOST_SOCKET
                   ▼
        ┌───────────────────────────────────────────┐
        │        persistent IPython kernel          │
        │                                           │
        │   preloaded:  rlm  harness  goal          │
        │               agent_message               │
        │   user state: files, results, dfs, …      │
        └───────────────────────────────────────────┘
                   │ adapter가 subprocess spawn
                   ▼
        ┌──────────┬──────────┬──────────┬──────────┐
        │ backend  │ frontend │ test     │ security │  ← child 에이전트
        │ (claude) │ (claude) │ (codex)  │ (claude) │    각자 native session id
        └──────────┴──────────┴──────────┴──────────┘
```

### 왜 Jupyter comm이 아니라 Unix socket인가

원본은 커널이 `Comm(target_name="host.request")`로 TS 호스트를 부른다.
이 방식은 `execute_request` 처리 중 comm 응답을 받기 위해
커널의 `control_handlers`를 런타임 패치해야 한다 (`__init__.py:_install_control_comm_handlers`).

우리는 socket을 택한다:

- 커널 재시작과 **독립적**이다. 브릿지가 커널 채널에 묶여 있지 않다.
- 커널이 아닌 **skill 서브프로세스**도 호스트를 호출할 수 있다 (K 레이어에 필요).
- 커널 없이 브릿지 단독 테스트가 가능하다.
- child 프로세스에 `OPA_HOST_SOCKET` + `OPA_ROLE=child`만 주면
  **child도 부모 호스트에 메시지를 보낼 수 있다** (A2A 양방향의 전제).

프로토콜: 한 줄 = 하나의 JSON.
```
→ {"id":"1","type":"rlm.run","payload":{...}}
← {"id":"1","status":"ok","rlm_child_id":"opa-a1b2","name":"api-reviewer",...}
← {"id":"1","status":"error","error":"..."}
```
타입 이름은 원본과 동일하게 유지한다 (`rlm.run`, `rlm.list_subagents`,
`rlm.delete_subagent`, `rlm.find_models`). 원본 스킬/문서를 그대로 참조 가능하도록.

---

## 3. MCP 도구 표면 — 의도적으로 작게

Prime Agent의 철학은 *"LLM에게 도구 20개를 주지 말고 Python을 줘라"* 이다.
호스트의 도구 목록을 오염시키면 그 철학과 정반대가 되고, 사용자의 기존
에이전트 성능에도 영향을 준다. 그래서 노출 도구는 **4개로 고정**한다.

| 도구 | 역할 |
|---|---|
| `opa_python(code, timeout=…)` | 유일한 작업 도구. persistent 커널에서 실행 |
| `opa_status()` | 커널 / child / goal / harness 요약 한 장 |
| `opa_kernel(action)` | `restart` \| `interrupt` \| `info` |
| `opa_bootstrap(agent=…)` | 현재 호스트에 harness projection·스킬 설치/갱신 |

`rlm`, `harness`, `goal`, `agent_message`는 **MCP 도구가 아니라 커널 안의 Python 심볼**이다.

```python
# 호스트 에이전트가 실제로 하는 일은 이게 전부다
opa_python("""
api  = await rlm("API 보안 검토", name="api-reviewer")
test = await rlm("테스트 커버리지 분석", name="test-reviewer")
""")
```

---

## 4. L1 — Persistent Python

- `jupyter_client.AsyncKernelManager`로 IPython 커널 1개를 세션당 소유.
- 부팅 시 `opa_runtime`을 주입해 `rlm / harness / goal / agent_message` 심볼을 노출.
- top-level `await`는 IPython autoawait가 네이티브로 처리한다.
  원본은 `nest_asyncio`를 쓰지만 실측 결과 불필요해서 의존성에서 뺐다.
- 커널 트랜스포트는 POSIX에서 **IPC 소켓**. TCP는 커널 코드/출력을 평문으로 흘린다.
- 출력 정책: stdout/result를 **잘라서** 반환하고 전문은 세션 디렉터리에 저장,
  경로만 알려준다. 이것이 "context를 창고로 쓰지 않는다"의 실질이다.
  - 기본 `OPA_MAX_OUTPUT_CHARS=4000`, 초과분은 `<session>/outputs/<n>.txt`.
- 커널 재시작 시 상태는 소실된다. 대신 **재시작 이후에도 복구되어야 하는 것**
  (child registry, harness, goal)은 전부 호스트 측 디스크에 있다.

---

## 5. L2 — RLM (persistent subagents)

### 5.1 어댑터 계약

```python
class AgentAdapter(Protocol):
    name: str
    def available(self) -> bool: ...
    async def spawn(self, spec: SpawnSpec) -> NativeSession: ...   # 최초 1턴
    async def resume(self, sess: NativeSession, prompt: str) -> TurnResult: ...
    def parse_stream(self, line: str) -> Event | None: ...
```

실측으로 계약이 성립함을 확인했다:

| 어댑터 | spawn | resume | 구조화 출력 | 세션 ID 출처 |
|---|---|---|---|---|
| `claude-code` | `claude -p P --session-id <UUID> --output-format stream-json` | `claude -p P --resume <UUID>` | stream-json | **우리가 발급** |
| `codex` | `codex exec P --json` | `codex exec resume <UUID> P --json` | JSONL | codex가 발급 → 파싱 |
| `opencode` | (조사 필요) | (조사 필요) | — | — |

`claude`가 세션 UUID를 우리가 지정할 수 있다는 점이 크다 —
registry의 id와 native session id를 1:1로 묶어둘 수 있어 복구가 단순해진다.

### 5.2 child registry

`rlm(...)`은 **결과를 기다리지 않는다.** 원본과 동일하게 admit 시점에 핸들을 반환한다.

```python
@dataclass
class ChildRecord:
    rlm_child_id: str        # opa-<8hex>
    name: str                # "api-reviewer" — 재호출 시 주소
    adapter: str             # "claude-code"
    native_session_id: str
    session_dir: Path
    cwd: Path
    model: str | None
    status: Literal["running", "completed", "error"]
    turns: list[TurnRef]
```

`<session>/children/index.json` + `<child>/turns.jsonl`에 영속화.
→ 커널 재시작·컨텍스트 compaction·호스트 재시작 후에도
`await rlm.list_subagents()`가 동일한 child를 되돌려준다. (원본의 핵심 요구사항)

### 5.3 A2A messaging

메일박스: `<session>/mailbox/<name>.jsonl`

- **parent → child**: `agent_message.send(..., receiver_role="child", receiver_name="api-reviewer")`
  → 어댑터 `resume`으로 새 턴. child는 이전 컨텍스트를 그대로 가진 채 이어서 일한다.
- **child → parent**: 두 경로
  1. *Phase 2*: child 프로세스의 최종 출력을 어댑터가 캡처해 parent 메일박스에 적재. 항상 동작.
  2. *Phase 3*: child에 `--mcp-config`로 opa 서버를 붙이고 `OPA_ROLE=child`를 주면
     child가 **작업 도중에도** parent에게 push 가능. socket 브릿지를 택한 이유.

### 5.4 수명

`manager ─┬─ backend  ─┐`
`         ├─ frontend ─┤  장기 상주, 필요할 때 재호출`
`         ├─ test     ─┤`
`         └─ security ─┘`

일회성 fan-out이 아니다. `delete_subagent`는 명시적 호출로만.

---

## 6. L3 — Continual Harness

원본의 상태 모델을 그대로 가져온다. `H = (ρ, G, K, M)`, kind ∈
`prompt | subagent | skill | memory`, scope ∈ `local | global`.
`harness_state.json` 스키마도 호환되게 유지한다 (원본 세션 이식 가능성).

### 6.1 projection — 이 프로젝트만의 문제

원본은 시스템 프롬프트를 소유하므로 harness를 그냥 주입하면 된다.
우리는 못 한다. 그래서 **호스트가 이미 읽는 파일로 투영한다.**

| harness kind | 투영 대상 |
|---|---|
| `prompt` (ρ) | `CLAUDE.md` / `AGENTS.md` 내부의 델리미터 블록 |
| `skill` (K) | `.claude/skills/<n>/SKILL.md`, python 패키지는 커널에 `uv pip install -e` |
| `memory` (M) | `.opa/memory/*.md` + 프롬프트 블록에는 **인덱스만** |
| `subagent` (G) | registry의 default spec (spawn 시 `--append-system-prompt`) |

**불변식**: 쓰기는 오직 델리미터 안에서만 한다.

```markdown
<!-- opa:begin — 자동 생성. 이 블록 밖은 건드리지 않음. `opa_bootstrap()`이 갱신 -->
...
<!-- opa:end -->
```

블록 밖 사용자 내용은 절대 수정하지 않는다. "환경을 안 바꾼다"는 약속은
여기서 지켜지거나 깨진다. 그래서 이건 테스트로 강제한다 (`tests/test_projection.py`).

### 6.2 refine

`/refine`은 호스트 슬래시커맨드라 에이전트마다 다르다. 그래서 2중으로 제공한다:

- 이식 가능한 코어: `await harness.refine(trajectory)` — 최소 CRUD delta 제안
- Claude Code 전용 편의: 플러그인 `/opa:refine` 슬래시 커맨드

원본 규칙 유지: base system prompt는 수정하지 않고, refinement history를 남기며
rollback이 가능해야 한다.

---

## 7. L4 — Long-run

| 기능 | 구현 |
|---|---|
| goal | `<session>/goal.json`. `opa_status()`와 커널 `goal.*` API가 노출 |
| heartbeat | 호스트 측 스케줄러가 메일박스에 리마인더 push. 호스트 에이전트는 다음 턴에 수거 |
| schedule | one-time / cron. 사용자용과 `rlm_heartbeat`(에이전트 자율 생성)를 분리 |
| autonomous | max turns / token budget / wall-clock + quality gate. 실패 gate 출력은 다시 입력으로 |

**한계를 명시한다**: 우리는 호스트의 턴 루프를 소유하지 않는다.
따라서 "에이전트를 깨운다"는 push가 아니라 pull(다음 턴에 수거)이다.
진짜 push가 필요하면 opa가 **직접 child를 돌리는** autonomous 모드를 쓴다
(이 경우 부모도 어댑터 위에서 돈다).

---

## 8. 보안

원본 문서도 명시하듯 IPython 커널과 worker는 **security sandbox가 아니다.**
모델이 만든 Python과 shell이 사용자 OS 권한으로 실행된다.
우리는 child spawn까지 하므로 표면이 더 넓다.

기본값 정책:
- child 기본 권한은 보수적으로. `--dangerously-skip-permissions`는 **명시적 opt-in만**.
- child `cwd`는 허용 경로 밖으로 못 나간다.
- `_ref/` 같은 신뢰 못 하는 코드를 다루는 세션에서 autonomous 금지.
- 장시간 autonomous는 devcontainer/VM 권장을 문서에 명시. (`docs/security.md`)

---

## 9. 열린 질문

- opencode의 headless/resume 인터페이스 확인 필요.
- child 토큰 사용량 회계: `claude --output-format json`의 usage 필드로 충분한가.
- harness `global` scope를 `~/.opa/`에 둘 때 여러 프로젝트 간 충돌 처리.
- 커널 재시작 시 사용자 변수 복구를 어디까지 시도할 것인가 (원본은 안 함).
