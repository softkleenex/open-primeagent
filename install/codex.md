# Codex에 붙이기

`~/.codex/config.toml`:

```toml
[mcp_servers.opa]
command = "uvx"
args = ["open-primeagent"]
```

로컬 체크아웃:

```toml
[mcp_servers.opa]
command = "uv"
args = ["run", "--directory", "/path/to/open_primeagent", "opa"]
```

Codex를 **child**로도 쓸 수 있다:

```python
await rlm("이 모듈 리팩터링", name="refactorer", adapter="codex", model="gpt-5.4")
```

부모는 Claude Code, child는 Codex 같은 이종 조합이 그대로 된다.
호스트 CLI에 모델 선택을 위임하기 때문이다.
