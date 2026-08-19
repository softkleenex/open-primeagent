"""Output handling - does "do not hand the model everything" actually hold?"""

from __future__ import annotations

from pathlib import Path

import pytest

from opa.kernel.exec import store_full, strip_ansi, truncate


def test_short_output_is_untouched():
    text = "hello"
    out, cut = truncate(text, 4000)
    assert out == text
    assert cut is False


@pytest.mark.parametrize("limit", [120, 200, 300, 1000, 4000])
def test_never_exceeds_limit(limit):
    text = "line\n" * 10000
    out, cut = truncate(text, limit, full_path=Path("/tmp/x.txt"))
    assert cut is True
    assert len(out) <= limit


def test_tail_survives_so_traceback_cause_is_visible():
    """A head-only cut truncates error output in the least useful way possible."""
    text = "noise\n" * 5000 + "ValueError: THE ACTUAL CAUSE"
    out, _ = truncate(text, 300)
    assert "THE ACTUAL CAUSE" in out


def test_truncation_marker_points_at_full_output():
    text = "z" * 10000
    out, _ = truncate(text, 300, full_path=Path("/tmp/full.txt"))
    assert "/tmp/full.txt" in out


def test_store_full_writes_sequential_files(tmp_path):
    a = store_full(tmp_path, "one")
    b = store_full(tmp_path, "two")
    assert a.name == "00000.txt" and b.name == "00001.txt"
    assert a.read_text() == "one"


def test_strip_ansi():
    assert strip_ansi("\x1b[31mZeroDivisionError\x1b[39m: x") == "ZeroDivisionError: x"
