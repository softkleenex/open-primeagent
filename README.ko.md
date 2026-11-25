# open-primeagent

[English](README.md) · **한국어** · [简体中文](README.zh-CN.md) · [日本語](README.ja.md)

<sub>영어 README의 첫 화면만 옮긴 문서입니다. 전체 문서와 최신 내용은 [영어 README](README.md)에 있습니다.</sub>

**Claude Code가 한참 걸려 저장소를 익혔습니다. 그런데 팀원이 같은 저장소를 Codex로 열면,
Codex는 그중 아무것도 모릅니다.**

요즘 에이전트는 각자 기억합니다. 대신 자기만 압니다. Claude Code는 `~/.claude`에, Codex는 `~/.codex`에,
그것도 기록한 그 컴퓨터에만 남깁니다. open-primeagent는 에이전트가 알아낸 것을 저장소의 `AGENTS.md`와
`CLAUDE.md` 안, 표시해 둔 블록 하나에 적습니다. 그래서 코드와 함께 커밋되고,
Claude Code도 Codex도 opencode도 똑같이 읽습니다.

![다시 찾기 어려운 규칙이 있는 새 클론에서 맨 Claude Code 두 세션을 비교: 앞선 에이전트가 남긴 AGENTS.md가 있는 쪽이 턴 수 51% 감소, 시간 51% 감소](docs/assets/portable-demo.gif)

<sub>[측정 데이터](bench/results/portable-deep-sonnet.json)(Sonnet, 조건당 n=6, 평균)를 재생한 화면이고, 연출한 게 아닙니다. 다시 찾기 쉬운 규칙에서는 효과가 절반 정도입니다: [26%](bench/README.md#p-a-rule-learned-by-one-agent-used-by-the-next-one-without-us---wins-more-when-the-rule-is-hard). [`bench/demo_portable.py`](bench/demo_portable.py)로 다시 만들 수 있습니다.</sub>

지금 쓰는 에이전트(셋 중 무엇이든)에 MCP 서버 하나만 추가하면 됩니다.

- **저장소와 함께 옮겨 가는 규칙.** open-primeagent를 붙인 Claude Code가 한 세션에서 저장소의 숨은 규칙을
  찾아 기록했습니다. 그렇게 만들어진 `AGENTS.md` 하나만 들어 있는 새 클론을, open-primeagent가 전혀 없는
  맨 Claude Code로 열었더니, 다시 찾기 어려운 규칙에서는 턴 수와 시간을 51% 덜 써서, 쉬운 규칙에서는 26% 덜 써서 같은 과제를 끝냈습니다.
  블록은 `opa_bootstrap(remove=True)`로 그대로 걷어낼 수 있습니다.
- **에이전트를 넘나드는 서브에이전트.** Claude Code에서 Codex 서브에이전트를 띄워 두고, 나중에 후속 질문을
  보낼 수 있습니다. 이제 Claude Code, Codex, opencode 모두 자기 서브에이전트는 다시 부를 수 있지만,
  서로의 서브에이전트에는 닿지 못합니다. (Codex 자식은 실제 CLI로 손수 확인했고, CI는 가짜 CLI를 씁니다.)
- **호출 사이에도 살아 있는 Python 프로세스.** 컨텍스트 창에 두기 싫은 상태를 담아 둡니다.
  다만 도움이 된다는 건 아직 보여 주지 못했습니다. 벤치마크 120턴 동안 에이전트가 한 번도 부르지 않았습니다.

```bash
claude mcp add opa -- uvx open-primeagent
# Codex와 opencode는 영어 README의 Install을 보세요. Claude Code 플러그인으로도 설치할 수 있습니다:
# /plugin install open-primeagent --marketplace softkleenex/open-primeagent
```

### 우리가 진 벤치마크

| 실험 | 결과 | |
|---|---|---|
| open-primeagent로 배운 규칙을, open-primeagent 없는 새 에이전트가 `AGENTS.md`로만 읽음 (미끼 스크립트 3개가 그럴듯하게 틀린 결과를 냄) | 턴 수 51% 감소, 시간 51% 감소 | 이김 |
| 같은 실험, 다시 찾기 쉬운 규칙 | 턴 수 26% 감소, 시간 26% 감소 | 조금 이김 |
| 같은 실험의 첫 버전: 에이전트가 규칙을 메모리로 저장해서 다른 에이전트에게는 제목만 보임 | 핵심 사실이 6번 중 4번만 전달됨 | 짐, 고친 뒤 6번 중 6번 |
| 미끼 스크립트 16개 사이에 숨어 있던 지식을 규칙으로 기록 (8월) | 걸린 시간 57% 감소, 편차도 줄어듦 | 이김 |
| 같은 규칙인데 답이 바로 보이는 경우 | 턴 수 26% 증가 | 짐 |
| 새로 만드는 대신 이미 코드를 읽은 서브에이전트에게 다시 일 시키기 | 비용 81% 감소 | 이김, 다만 이제 각 에이전트가 기본으로 함 |
| 새 서브에이전트 4개에게 나눠 맡기기 | 비용 777% 증가 | 짐 |
| 나눠 맡기기가 이기도록 만든 444개 파일짜리 코드베이스에서 | 걸린 시간 127% 증가 | 짐 |
| 영속 커널을 120턴 동안 붙여 둠 | 호출 0회 | 효과 없음 |

진 결과도 지우지 않습니다. 이긴 결과를 믿을 수 있게 해 주는 게 진 결과이고,
왜 졌는지가 숫자보다 쓸모 있습니다. [원본 데이터와 측정 방법](bench/README.md)

우리 자신에게도 같은 기준을 둡니다. 이 README는 원래 "세션이 끝나도 남는 서브에이전트"를 앞세웠습니다.
그런데 각 에이전트와 비교해 보다가, Claude Code, Codex, opencode가 올해 모두 그 기능을 기본으로 넣었다는 걸
알게 됐고, 그래서 더는 첫 문장에 두지 않습니다. 또 "블록 밖은 한 글자도 바꾸지 않는다"고 약속했지만
외부 리뷰에서 그 약속이 깨지는 입력이 나왔고, [경위는 개발 일지에 있습니다](docs/journal.md#an-outside-review-breaks-the-headline-promise-2026-11-25).
지금은 모든 안전장치에 [뮤테이션 테스트](scripts/mutate_guards.py)를 겁니다. 일부러 망가뜨려 보고 테스트가 실패하는지 확인합니다.

**[나머지 문서 (영어) →](README.md#install)**
