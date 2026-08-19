# Claude Code에 붙이기

```bash
claude mcp add opa -- uvx open-primeagent
```

또는 로컬 체크아웃으로:

```bash
claude mcp add opa -- uv run --directory /path/to/open_primeagent opa
```

확인:

```
/mcp        # opa 에 도구 4개 (opa_python / opa_status / opa_kernel / opa_bootstrap)
```

## 선택: harness projection 설치

```
opa_bootstrap()             # CLAUDE.md 에 opa 블록 + .claude/skills/ 설치
opa_bootstrap(remove=True)  # 완전 원상복구
```

블록 밖 내용은 건드리지 않는다.

## 환경 변수

| 변수 | 기본 | 의미 |
|---|---|---|
| `OPA_WORKSPACE` | `cwd` | 작업 루트 |
| `OPA_ROOT` | `<workspace>/.opa` | 상태 저장 위치 |
| `OPA_MAX_OUTPUT_CHARS` | `4000` | 응답에 실을 최대 출력 |
| `OPA_DEFAULT_ADAPTER` | `claude-code` | child 백엔드 |
| `OPA_CHILD_PERMISSION_MODE` | `acceptEdits` | child 권한 |
| `OPA_ALLOW_DANGEROUS_CHILD` | (unset) | `1`이면 child에 권한 우회 허용 |
