"""opa_status — 커널 / child / goal / harness 를 한 장으로.

호스트가 컨텍스트를 잃었을 때(compaction, 재시작) 이 한 번의 호출로
"내가 어디까지 했고 누가 일하고 있는지"가 복원되어야 한다.
"""

DESCRIPTION = """\
One-page state of the open-primeagent session: kernel liveness, persistent
sub-agents (name / adapter / status / last turn), active goal and budget,
harness entry counts, and unread mailbox messages.
Call this after a context compaction or when resuming work.
"""
