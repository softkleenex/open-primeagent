"""The shareable receipt: a card that says only what reuse() measured."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlparse

from opa import receipt

REUSE = {
    "warm_children": 1,
    "follow_ups": 2,
    "estimated_tokens_saved": 60_946,
    "estimated_cost_saved_usd": 0.2514,
    "basis": "each follow-up vs. that sub-agent's own first (cold) turn; an estimate",
    "receipt": "open-primeagent: 2 follow-up(s) to 1 warm sub-agent(s), ~60,946 tokens",
}


def _texts(svg: str) -> list[str]:
    root = ET.fromstring(svg)
    return [t.text or "" for t in root.iter("{http://www.w3.org/2000/svg}text")]


def test_the_card_is_valid_svg_carrying_the_measured_numbers():
    texts = _texts(receipt.card_svg(REUSE))
    assert "~60,946" in texts and "~$0.25" in texts
    assert "2 to 1 warm sub-agent(s)" in texts
    # It is an estimate, and the card says so.
    assert any("estimated" in t for t in texts)


def test_a_saving_under_a_cent_is_not_shown_as_money():
    texts = _texts(receipt.card_svg({**REUSE, "estimated_cost_saved_usd": 0.004}))
    assert not any(t.startswith("~$") for t in texts)


def test_the_share_link_only_prefills_the_receipt():
    url = urlparse(receipt.share_url(REUSE["receipt"]))
    assert (url.scheme, url.netloc, url.path) == ("https", "x.com", "/intent/post")
    query = parse_qs(url.query)
    assert query["text"] == [REUSE["receipt"]]
    assert query["url"] == [receipt.REPO]


def test_dress_writes_the_card_into_the_session_dir(tmp_path):
    dressed = receipt.dress(REUSE, tmp_path)
    assert dressed["card"] == str(tmp_path / receipt.CARD_NAME)
    assert "60,946" in (tmp_path / receipt.CARD_NAME).read_text(encoding="utf-8")
    assert dressed["share_url"].startswith("https://x.com/")


def test_nothing_is_written_when_there_is_nothing_to_show(tmp_path):
    empty = {**REUSE, "follow_ups": 0, "receipt": None}
    assert receipt.dress(empty, tmp_path) == empty
    assert list(tmp_path.iterdir()) == []
