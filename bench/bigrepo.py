"""A codebase too large for one agent to read cheaply, split into 4 subsystems.

Benchmark 0 fanned four children at a 12-file project and lost by 8.8x, but
that setup was rigged against fan-out in two ways: the material fit easily in
one context, and every child re-read the whole project. Neither is how you would
actually use sub-agents.

Here each subsystem is independently reviewable and the children are scoped to
one each, so nothing is read twice. If fan-out cannot win under these conditions
it does not win anywhere.

Every subsystem carries exactly one planted defect, so a review is gradeable.
"""

from __future__ import annotations

import random
import shutil
from pathlib import Path

SEED = 20260820
FILES_PER_SUBSYSTEM = 110

SUBSYSTEMS = {
    "auth": "authentication, sessions and permissions",
    "billing": "invoices, pricing and tax",
    "catalog": "product catalog, search and inventory",
    "delivery": "shipping, routing and tracking",
}

# subsystem -> (file, the defect a reviewer should name)
PLANTED = {
    "auth": ("auth/session_store.py", "hardcoded signing key"),
    "billing": ("billing/refund_engine.py", "float arithmetic on money"),
    "catalog": ("catalog/search_index.py", "SQL built by string concatenation"),
    "delivery": ("delivery/route_planner.py", "quadratic nearest-stop scan"),
}

_FILLER = '''\
"""{module} — {role}."""

from dataclasses import dataclass
from typing import Any


@dataclass
class {cls}Config:
    enabled: bool = True
    retries: int = {retries}
    timeout_seconds: float = {timeout}


class {cls}:
    """{role_sentence}"""

    def __init__(self, config: {cls}Config | None = None) -> None:
        self.config = config or {cls}Config()
        self._cache: dict[str, Any] = {{}}

    def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        key = str(payload.get("id", ""))
        if key in self._cache:
            return self._cache[key]
        result = self._compute(payload)
        self._cache[key] = result
        return result

    def _compute(self, payload: dict[str, Any]) -> dict[str, Any]:
        value = 0
        for index, item in enumerate(payload.get("items", [])):
            value += index * int(item.get("weight", 1))
        return {{"id": payload.get("id"), "score": value, "source": "{module}"}}

    def reset(self) -> None:
        self._cache.clear()


def build_{fn}(config: {cls}Config | None = None) -> {cls}:
    return {cls}(config)
'''

DEFECTS = {
    "auth/session_store.py": '''\
"""session_store — issues and validates session tokens."""

import hmac
import hashlib
import time

# NOTE: rotate this before the next release
SIGNING_KEY = b"s3cr3t-signing-key-do-not-ship-2019"

TTL_SECONDS = 60 * 60 * 24 * 30


def issue(user_id: str) -> str:
    payload = f"{user_id}:{int(time.time())}"
    mac = hmac.new(SIGNING_KEY, payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{mac}"


def verify(token: str) -> str | None:
    try:
        user_id, issued, mac = token.rsplit(":", 2)
    except ValueError:
        return None
    payload = f"{user_id}:{issued}"
    expected = hmac.new(SIGNING_KEY, payload.encode(), hashlib.sha256).hexdigest()
    if mac != expected:
        return None
    if time.time() - int(issued) > TTL_SECONDS:
        return None
    return user_id
''',
    "billing/refund_engine.py": '''\
"""refund_engine — computes partial and full refunds."""


TAX_RATE = 0.1


def line_refund(unit_price: float, quantity: int, used_days: int, term_days: int) -> float:
    """Pro-rate a line item by unused days."""
    unused = max(term_days - used_days, 0)
    return unit_price * quantity * (unused / term_days)


def total_refund(lines: list[dict]) -> float:
    total = 0.0
    for line in lines:
        total += line_refund(
            line["unit_price"], line["quantity"], line["used_days"], line["term_days"]
        )
    return round(total * (1 + TAX_RATE), 2)


def is_fully_refunded(charged: float, refunded: float) -> bool:
    return charged - refunded == 0.0
''',
    "catalog/search_index.py": '''\
"""search_index — keyword search over the product catalog."""

import sqlite3


def search(conn: sqlite3.Connection, term: str, category: str | None = None) -> list:
    query = "SELECT id, name, price FROM products WHERE name LIKE '%" + term + "%'"
    if category:
        query += " AND category = '" + category + "'"
    query += " ORDER BY rank DESC LIMIT 50"
    return conn.execute(query).fetchall()


def suggest(conn: sqlite3.Connection, prefix: str) -> list:
    return conn.execute(
        "SELECT name FROM products WHERE name LIKE '" + prefix + "%' LIMIT 10"
    ).fetchall()
''',
    "delivery/route_planner.py": '''\
"""route_planner — orders stops for a delivery run."""

import math


def distance(a: dict, b: dict) -> float:
    return math.hypot(a["lat"] - b["lat"], a["lng"] - b["lng"])


def plan(stops: list[dict], depot: dict) -> list[dict]:
    """Order stops nearest-first from the depot."""
    remaining = list(stops)
    ordered = []
    current = depot
    while remaining:
        best = None
        best_distance = float("inf")
        for candidate in remaining:
            d = distance(current, candidate)
            if d < best_distance:
                best_distance = d
                best = candidate
        ordered.append(best)
        remaining.remove(best)
        current = best
    return ordered


def total_distance(route: list[dict], depot: dict) -> float:
    points = [depot, *route]
    return sum(distance(points[i], points[i + 1]) for i in range(len(points) - 1))
''',
}

README = """\
# platform

A service split into four independently owned subsystems.

    auth/       {auth}
    billing/    {billing}
    catalog/    {catalog}
    delivery/   {delivery}

Each subsystem is reviewed by its owning team.
"""


def build(root: Path) -> None:
    rng = random.Random(SEED)
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    for subsystem, role in SUBSYSTEMS.items():
        directory = root / subsystem
        directory.mkdir()
        for index in range(FILES_PER_SUBSYSTEM):
            module = f"{subsystem}_mod_{index:02d}"
            cls = "".join(part.title() for part in module.split("_"))
            (directory / f"{module}.py").write_text(
                _FILLER.format(
                    module=module,
                    cls=cls,
                    fn=module,
                    role=role,
                    role_sentence=f"Handles part of {role}.",
                    retries=rng.randint(1, 5),
                    timeout=round(rng.uniform(0.5, 9.5), 1),
                ),
                encoding="utf-8",
            )

    for relative, body in DEFECTS.items():
        (root / relative).write_text(body, encoding="utf-8")

    (root / "README.md").write_text(README.format(**SUBSYSTEMS), encoding="utf-8")


def approximate_tokens(root: Path) -> int:
    """Rough size, to keep benchmark cost predictable. ~4 chars per token."""
    return sum(len(p.read_text(encoding="utf-8")) for p in root.rglob("*.py")) // 4
