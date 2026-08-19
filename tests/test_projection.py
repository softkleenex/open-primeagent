"""projection 불변식 — 이 프로젝트의 전제를 강제한다.

`opa_bootstrap` 이 델리미터 블록 **밖**의 사용자 내용을 바꾸면
"환경을 안 바꾼다"는 약속이 깨진다. 그래서 이건 문서가 아니라 테스트다.
"""

from __future__ import annotations

from opa.harness import projection
from opa.harness.state import HarnessEntry

USER_FILE = """# My Project

프로젝트 규칙:
- 커밋 메시지는 한국어로
- 테스트 없이 머지 금지

<!-- 사용자가 직접 쓴 주석 -->
끝.
"""


def entry(kind, id, title, content="body text"):
    return HarnessEntry(id=id, kind=kind, title=title, content=content)


def test_apply_preserves_content_outside_block(tmp_path):
    """블록 밖 내용은 바이트 단위로 보존된다."""
    target = tmp_path / "CLAUDE.md"
    target.write_text(USER_FILE, encoding="utf-8")

    projection.apply(target, "first version")
    after = target.read_text(encoding="utf-8")

    assert USER_FILE.rstrip("\n") in after
    assert "first version" in after

    # 두 번째 적용에서도 사용자 내용은 그대로여야 한다
    projection.apply(target, "second version")
    after2 = target.read_text(encoding="utf-8")
    assert USER_FILE.rstrip("\n") in after2
    assert "first version" not in after2
    assert "second version" in after2


def test_remove_restores_original_file(tmp_path):
    """remove 후 파일이 원본과 완전히 동일하다."""
    target = tmp_path / "AGENTS.md"
    target.write_text(USER_FILE, encoding="utf-8")

    projection.apply(target, "some projection")
    assert projection.remove(target) is True
    assert target.read_text(encoding="utf-8") == USER_FILE


def test_apply_is_idempotent(tmp_path):
    """같은 내용으로 두 번 적용해도 파일이 변하지 않는다."""
    target = tmp_path / "CLAUDE.md"
    target.write_text(USER_FILE, encoding="utf-8")

    projection.apply(target, "stable body")
    once = target.read_text(encoding="utf-8")
    assert projection.apply(target, "stable body") is False
    assert target.read_text(encoding="utf-8") == once


def test_block_only_file_is_deleted_on_remove(tmp_path):
    """우리가 만든 파일이면 흔적을 남기지 않는다."""
    target = tmp_path / "CLAUDE.md"
    projection.apply(target, "body")
    assert target.exists()
    projection.remove(target)
    assert not target.exists()


def test_remove_on_untouched_file_changes_nothing(tmp_path):
    target = tmp_path / "CLAUDE.md"
    target.write_text(USER_FILE, encoding="utf-8")
    assert projection.remove(target) is False
    assert target.read_text(encoding="utf-8") == USER_FILE


def test_render_puts_only_the_index_for_memories(tmp_path):
    """메모리 본문은 블록에 넣지 않는다 — 컨텍스트를 창고로 쓰지 않는다."""
    entries = [
        entry("prompt", "migration", "migration 후 prisma generate"),
        entry("memory", "ports", "포트 목록", content="아주 긴 본문 " * 200),
    ]
    body = projection.render(entries, memory_dir=tmp_path)
    assert "migration 후 prisma generate" in body
    assert "`.opa/memory/ports.md`" in body
    assert "아주 긴 본문 아주 긴 본문" not in body


def test_write_memories_creates_and_prunes(tmp_path):
    memory_dir = tmp_path / "memory"
    projection.write_memories(memory_dir, [entry("memory", "a", "A"), entry("memory", "b", "B")])
    assert {p.stem for p in memory_dir.glob("*.md")} == {"a", "b"}

    projection.write_memories(memory_dir, [entry("memory", "a", "A")])
    assert {p.stem for p in memory_dir.glob("*.md")} == {"a"}


def test_write_skills_never_touches_user_skills(tmp_path):
    """사용자가 직접 만든 스킬을 지우면 약속이 깨진다."""
    skills = tmp_path / "skills"
    user_skill = skills / "my-own"
    user_skill.mkdir(parents=True)
    (user_skill / "SKILL.md").write_text("mine", encoding="utf-8")

    projection.write_skills(skills, [entry("skill", "opa-one", "One")])
    assert (skills / "opa-one" / "SKILL.md").exists()

    projection.write_skills(skills, [])           # 우리 스킬만 사라져야 한다
    assert not (skills / "opa-one").exists()
    assert (user_skill / "SKILL.md").read_text() == "mine"

    projection.remove_skills(skills)
    assert (user_skill / "SKILL.md").read_text() == "mine"


def test_apply_finds_a_block_written_with_a_different_marker_text(tmp_path):
    """마커 안내문이 바뀌어도 기존 블록을 찾아 교체해야 한다.
    못 찾으면 블록이 매번 새로 쌓인다."""
    target = tmp_path / "CLAUDE.md"
    target.write_text(
        "keep me\n\n<!-- opa:begin (old wording) -->\nold body\n<!-- opa:end -->\n",
        encoding="utf-8",
    )
    projection.apply(target, "new body")
    text = target.read_text(encoding="utf-8")
    assert text.count("opa:begin") == 1
    assert "old body" not in text
    assert "keep me" in text
