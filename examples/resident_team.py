"""예제: 프로젝트에 상주하는 전문가 팀.

fan-out 후 종료가 아니라, 같은 child들을 계속 다시 부르는 것이 요점이다.
(Phase 2 완료 후 동작)
"""

# --- 1일차: 팀 구성 -------------------------------------------------------
await rlm("백엔드 아키텍처와 API 계약을 파악해라", name="backend")
await rlm("프론트 상태관리 구조를 파악해라",        name="frontend")
await rlm("테스트 전략과 커버리지 구멍을 찾아라",    name="test", adapter="codex")
await rlm("인증/권한 경로의 위험을 목록화해라",      name="security")

# --- 며칠 뒤, 커널을 몇 번 재시작한 후 -------------------------------------
team = await rlm.list_subagents()      # 네 명 그대로 살아있다
print([c.name for c in team])

# 이미 맥락을 아는 에이전트에게 후속 작업을 준다 (새로 만들지 않는다)
await agent_message.send(
    "방금 머지한 결제 모듈까지 포함해서 다시 검토해",
    receiver_role="child", receiver_name="security",
)

# --- 중간 데이터는 컨텍스트가 아니라 여기에 남는다 -------------------------
inbox = await agent_message.poll()
issues = [m for m in inbox if m["sender"] == "security"]
issues[:3]        # 모델은 이 3개만 본다
