# opencode에 붙이기

> 🚧 어댑터 조사중 (TODO.md). MCP 클라이언트로서의 등록은 opencode의
> MCP 설정 규약을 따르면 되고, **child 백엔드**로 쓰려면
> headless 실행 + 세션 재개 인터페이스 확인이 필요하다.

어댑터 계약(`src/opa/rlm/adapters/base.py`)이 요구하는 것은 두 가지뿐이다:

1. 프롬프트 하나로 비대화식 실행
2. 세션 id로 재개

이 둘만 되면 30줄짜리 어댑터로 붙는다.
