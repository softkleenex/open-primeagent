"""The reuse receipt as something you can share: an SVG card and a post link.

`ChildRegistry.reuse()` produces the numbers and the one-line receipt. This
module only dresses them. The card is plain SVG so it needs nothing installed,
and the link only pre-fills a post: nothing leaves the machine unless the user
opens it and presses the button themselves.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode
from xml.sax.saxutils import escape

from .fsutil import atomic_write

REPO = "https://github.com/softkleenex/open-primeagent"
CARD_NAME = "reuse-receipt.svg"

_BG, _FG, _DIM, _GOOD, _RULE = "#0d1117", "#e6edf3", "#8b949e", "#3fb950", "#30363d"
_FONT = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"


def _line(x: int, y: int, text: str, *, size: int, fill: str) -> str:
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}">{escape(text)}</text>'


def card_svg(reuse: dict) -> str:
    """A 1200x630 card (the size link previews use) for a non-empty receipt."""
    cost = reuse.get("estimated_cost_saved_usd") or 0.0
    rows = [
        (
            "follow-ups",
            f"{reuse['follow_ups']} to {reuse['warm_children']} warm sub-agent(s)",
        ),
        ("tokens not re-spent", f"~{reuse['estimated_tokens_saved']:,}"),
    ]
    if cost >= 0.01:
        rows.append(("at API rates", f"~${cost:.2f}"))
    parts = [
        (
            '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" '
            f'viewBox="0 0 1200 630" font-family="{_FONT}">'
        ),
        f'<rect width="1200" height="630" fill="{_BG}"/>',
        _line(72, 110, "open-primeagent receipt", size=44, fill=_FG),
        _line(72, 156, "a sub-agent that already read the code, re-tasked", size=24, fill=_DIM),
        f'<rect x="72" y="196" width="1056" height="2" fill="{_RULE}"/>',
    ]
    for i, (label, value) in enumerate(rows):
        y = 280 + i * 84
        parts.append(_line(72, y, label, size=26, fill=_DIM))
        parts.append(_line(520, y, value, size=40, fill=_GOOD if i else _FG))
    parts += [
        _line(72, 548, "estimated against each sub-agent's own first turn", size=20, fill=_DIM),
        _line(72, 584, REPO.removeprefix("https://"), size=20, fill=_DIM),
        "</svg>",
    ]
    return "\n".join(parts) + "\n"


def share_url(receipt: str) -> str:
    """A link that opens a pre-filled post. Opening it sends nothing by itself."""
    return "https://x.com/intent/post?" + urlencode({"text": receipt, "url": REPO})


def dress(reuse: dict, session_dir: Path) -> dict:
    """Add `card` (an SVG path) and `share_url` to a reuse summary that has a receipt.

    Without follow-ups there is nothing to show, so nothing is written.
    """
    if not reuse.get("receipt"):
        return reuse
    card = session_dir / CARD_NAME
    try:
        atomic_write(card, card_svg(reuse))
    except OSError:
        card = None
    return {
        **reuse,
        "card": str(card) if card else None,
        "share_url": share_url(reuse["receipt"]),
    }
