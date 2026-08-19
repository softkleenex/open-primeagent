# open-primeagent

**RLM을 당신이 쓰던 코딩 에이전트에 그대로 붙인다.**

[Prime Agent](https://github.com/PrimeIntellect-ai/prime-agent)의 핵심 —
persistent Python, persistent subagent, continual harness — 를
Claude Code / Codex / opencode 위에 얹는 MCP 서버.
**에이전트를 갈아타지 않아도 된다.**

```bash
claude mcp add opa -- uvx open-primeagent      # 이게 전부
```

> **상태**: Phase 2 완료 — persistent 커널과 **RLM이 실제로 동작한다.**
> 아래 예제는 실행해서 확인한 것이다. [ROADMAP.md](ROADMAP.md) 참조.

```
✅ L1  Persistent Python      커널 · 외부 작업 메모리 · 출력 잘라내기
✅ L2  RLM                    persistent subagents + A2A messaging
                              adapters: claude-code · codex
🚧 L3  Continual Harness      prompts / subagents / skills / memory
⬜ L4  Long-run               goal / heartbeat / schedule / autonomous
```

---

## 무엇이 달라지나

```python
# 호스트 에이전트가 opa_python 도구로 실행하는 코드

# 1) 장기 상주 전문가 팀을 함수처럼 만든다
api  = await rlm("API 코드의 보안 문제를 찾아라", name="api-reviewer")
test = await rlm("테스트 커버리지를 분석해라",     name="test-reviewer")

# 2) child는 일회용이 아니다 — 나중에 다시 부른다
await agent_message.send(
    "방금 수정한 코드까지 다시 검사해",
    receiver_role="child", receiver_name="api-reviewer",
)   # ← 이전 컨텍스트를 유지한 채 이어서 일한다

# 3) 중간 데이터는 컨텍스트가 아니라 Python에 남는다
files   = collect(...)          # 수백 개
graph   = build_dep_graph(files)  # 30KB
suspect = [f for f in files if graph.fanin(f) > 20]
suspect[:5]                     # ← 모델은 이 5개만 본다
```

`rlm(...)`은 LLM API 호출이 아니라 **독립된 에이전트 세션**을 만든다.
각 child는 자기 컨텍스트·세션 디렉터리·모델을 갖고, 커널 재시작이나
컨텍스트 compaction 이후에도 registry에서 복구된다.

## 설계 한 줄

> LLM 컨텍스트 = **지금 판단에 필요한 것**
> Python 환경  = **거대한 외부 작업 메모리**

## 왜 이게 가능한가

원본에서 RLM 커널 shim은 1,536 LOC고, 나머지 167k LOC는 자체 harness/TUI/provider다.
우리는 harness를 **사용자가 이미 쓰는 에이전트에 위임**한다.
그래서 새로 만들 것은 RLM 런타임뿐이다.

child 세션 영속성은 호스트 CLI가 이미 제공한다:

| | spawn | resume |
|---|---|---|
| `claude` | `-p P --session-id <UUID>` | `-p P --resume <UUID>` |
| `codex` | `exec P --json` | `exec resume <UUID> P` |

## 노출 도구는 4개뿐

`opa_python` · `opa_status` · `opa_kernel` · `opa_bootstrap`*
&nbsp;&nbsp;<sub>*Phase 3</sub>

`rlm` / `harness` / `goal` / `agent_message`는 MCP 도구가 아니라
**커널 안의 Python 심볼**이다. 호스트의 도구 목록을 오염시키지 않는다.

상한은 `server.MAX_TOOLS = 4` 이고 테스트가 이걸 강제한다. 도구를 늘리고 싶어지면
그건 커널 안 심볼로 노출하라는 신호다.

## 지금 동작하는 것

```bash
git clone https://github.com/softkleenex/open-primeagent && cd open-primeagent
uv sync --extra dev
uv run pytest -q                  # 63 passed
claude mcp add opa --scope local -- uv run --directory "$PWD" opa
claude mcp list                   # opa: ✔ Connected
```

**외부 작업 메모리**
```python
opa_python("files = [f'f{i}.py' for i in range(500)]")
opa_python("len(files)")          # → 500   (별도 호출인데 살아있다)
opa_python("print('x' * 30000)")  # → 잘려서 오고, 전문은 outputs/00000.txt
```

**persistent subagent** — 아래는 실제 실행 결과다:
```python
await rlm('Reply with exactly: ALPHA-7', name='probe', model='sonnet')
# → <rlm child 'probe' (claude-code) running>     0.6초 만에 반환, child는 계속 돎

await agent_message.inbox()
# → [{'sender': 'probe', 'message': 'ALPHA-7', 'ok': True, 'tokens': 11}]

# ── 여기서 부모 커널을 재시작한다 ──
await rlm.list_subagents()
# → [<subagent 'probe' (claude-code) completed turns=1 tokens=11>]   살아있다

await agent_message.send('What token did you just say? Reply with only the token.',
                         receiver_name='probe')
await agent_message.inbox()
# → ... {'sender': 'probe', 'message': 'ALPHA-7'}
#   부모 커널이 재시작됐는데도 child는 이전 대화를 기억했다
```

이종 모델 조합도 그대로 된다 — 부모는 Claude Code, child는 Codex:
```python
await rlm('이 모듈 리팩터링', name='refactorer', adapter='codex')
```

## 문서

- [ARCHITECTURE.md](ARCHITECTURE.md) — 레이어, 브릿지 설계, projection
- [ROADMAP.md](ROADMAP.md) — Phase별 exit criteria
- [TODO.md](TODO.md) — 지금 할 일
- `docs/security.md` — **sandbox가 아니다.** 읽어라.

## ⚠️ 보안

IPython 커널과 child 에이전트는 **사용자 OS 권한으로 실행된다.**
샌드박스가 아니다. 신뢰할 수 없는 레포나 장시간 autonomous 실행은
devcontainer/VM 안에서만 하라.

## 라이선스 / 관계

Prime Agent(Apache-2.0)의 아키텍처에서 출발한 **독립 재구현**이다. 포크가 아니다.
`_ref/`의 원본 클론은 연구용이며 배포물에 포함되지 않는다.
