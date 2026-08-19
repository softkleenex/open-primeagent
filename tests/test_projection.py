"""projection 불변식 테스트 — 이 프로젝트의 전제를 강제한다.

`opa_bootstrap`이 델리미터 블록 **밖**의 사용자 내용을 바꾸면
"환경을 안 바꾼다"는 약속이 깨진다. 그래서 이건 문서가 아니라 테스트다.

Phase 3에서 구현. 지금은 의도를 못박아두는 자리.
"""

import pytest


@pytest.mark.skip(reason="Phase 3")
def test_apply_preserves_content_outside_block():
    """블록 밖 내용은 바이트 단위로 보존된다."""


@pytest.mark.skip(reason="Phase 3")
def test_remove_restores_original_file():
    """remove 후 파일이 원본과 완전히 동일하다."""


@pytest.mark.skip(reason="Phase 3")
def test_apply_is_idempotent():
    """같은 내용으로 두 번 적용해도 파일이 변하지 않는다."""
