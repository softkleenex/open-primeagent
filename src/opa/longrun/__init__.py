"""L4 — 장시간 자율 작업. goal / heartbeat / schedule / autonomous.

한계 명시: 우리는 호스트의 턴 루프를 소유하지 않는다.
따라서 "깨우기"는 push가 아니라 pull(다음 턴에 메일박스 수거)이다.
진짜 push가 필요하면 opa가 직접 어댑터 위에서 도는 autonomous 모드를 쓴다.
"""
