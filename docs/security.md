# 보안

## 한 줄

**샌드박스가 아니다.**

IPython 커널에서 실행되는 Python과, child 에이전트가 실행하는 shell 명령은
전부 **당신의 OS 권한**으로 돈다. 원본 Prime Agent도 커널과 worker가
security sandbox가 아님을 명시하고 있고, 우리는 거기에 child spawn까지 얹으므로
공격 표면이 더 넓다.

```
호스트 에이전트 → opa MCP → persistent Python → shell → filesystem
                          └→ child agents → shell → filesystem
```

에이전트의 힘이 커질수록 prompt injection · 악성 레포 · 악성 skill의
피해 반경도 같이 커진다.

## 기본값

| 항목 | 기본값 | 근거 |
|---|---|---|
| child 권한 모드 | `acceptEdits` | bypass는 명시적 opt-in만 |
| `--dangerously-skip-permissions` | **비활성** | `OPA_ALLOW_DANGEROUS_CHILD=1` 필요 |
| child `cwd` | workspace 하위로 제한 | 밖으로 못 나감 |
| autonomous | 기본 비활성 | 감시 없이 파일을 고친다 |

## 언제 컨테이너를 써야 하나

다음 중 하나라도 해당하면 devcontainer / VM / Docker 안에서만 실행하라.

- 신뢰할 수 없는 레포를 다룰 때
- 외부에서 온 지시문(이슈 본문, PR 설명, 웹 페이지)을 에이전트가 읽을 때
- **장시간 autonomous 모드**를 쓸 때
- 서드파티 skill을 설치할 때

## 우리가 지키는 약속

`opa_bootstrap`은 **델리미터 블록 안에만** 쓴다.

```markdown
<!-- opa:begin -->
...
<!-- opa:end -->
```

블록 밖의 `CLAUDE.md` / `AGENTS.md` 내용은 바이트 단위로 보존된다.
`opa_bootstrap(remove=True)`로 완전 원상복구된다.
이건 문서상의 약속이 아니라 테스트로 강제된다 (`tests/test_projection.py`).

## 보고

취약점을 찾으면 이슈 대신 비공개로 알려달라.
