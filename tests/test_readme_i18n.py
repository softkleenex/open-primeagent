"""The translated READMEs must say the same numbers as the English one.

They translate only the English README's first screen, the part between the
`i18n:begin` and `i18n:end` markers. That part is mostly measurements, and a
translation still quoting last month's number would undercut the one thing the
README is built on: that its numbers can be checked. So when a number changes
in English, this fails until every translation changes with it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TRANSLATIONS = ("README.ko.md", "README.zh-CN.md", "README.ja.md")

# Link targets carry dates and anchors that are not claims.
_LINK_TARGET = re.compile(r"\]\([^)]*\)")
# Percentages, and plain counts of 10 or more. Small counts ("4 sub-agents",
# "n=4") are written differently across languages and are not worth policing.
_NUMBER = re.compile(r"(?<![\w.])(\d[\d,]*%|\d{2,}(?![\d,]))")


def numbers(text: str) -> set[str]:
    return set(_NUMBER.findall(_LINK_TARGET.sub("]", text)))


def english_first_screen() -> str:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    begin = text.index("<!-- i18n:begin")
    end = text.index("<!-- i18n:end -->")
    return text[text.index("-->", begin) + 3 : end]


def test_the_english_first_screen_has_numbers_to_check():
    # Guards the regex: an empty set would make every comparison below pass.
    assert {"81%", "777%", "444", "120"} <= numbers(english_first_screen())


@pytest.mark.parametrize("name", TRANSLATIONS)
def test_a_translation_quotes_the_same_numbers(name):
    translated = (ROOT / name).read_text(encoding="utf-8")
    english = numbers(english_first_screen())
    assert numbers(translated) == english, (
        f"{name} is out of date: "
        f"missing {sorted(english - numbers(translated))}, "
        f"extra {sorted(numbers(translated) - english)}"
    )


@pytest.mark.parametrize("name", TRANSLATIONS)
def test_every_readme_links_to_every_other(name):
    for path in ("README.md", *TRANSLATIONS):
        text = (ROOT / path).read_text(encoding="utf-8")
        others = {"README.md", *TRANSLATIONS} - {path}
        for other in others:
            assert f"]({other})" in text, f"{path} has no link to {other}"
