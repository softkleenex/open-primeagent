"""A small service with four planted defects, one per review dimension.

Planting them is what makes the sub-agent benchmark gradeable: we can ask
whether a review actually found each one instead of judging prose quality.
"""

from __future__ import annotations

import shutil
from pathlib import Path

# marker -> (file, what a review should notice)
PLANTED = {
    "security": ("api/auth.py", "hardcoded credential and SQL string concatenation"),
    "tests": ("billing/invoice.py", "the only module with no test file at all"),
    "performance": ("reports/aggregate.py", "quadratic scan over orders"),
    "api": ("api/routes.py", "three different error response shapes"),
}

FILES: dict[str, str] = {
    "api/auth.py": '''\
"""Authentication helpers."""
import hashlib
import sqlite3

# TODO(sec): move this out of source control
ADMIN_TOKEN = "sk-live-9f2c41ab77de4c0e8a13bb90fe217c55"


def find_user(conn: sqlite3.Connection, email: str):
    cur = conn.cursor()
    cur.execute("SELECT id, email, pw FROM users WHERE email = '" + email + "'")
    return cur.fetchone()


def check_password(stored: str, given: str) -> bool:
    return stored == hashlib.md5(given.encode()).hexdigest()


def is_admin(token: str) -> bool:
    return token == ADMIN_TOKEN
''',
    "api/routes.py": '''\
"""HTTP routes."""
from api.auth import find_user, is_admin


def get_user(request, conn):
    user = find_user(conn, request["email"])
    if not user:
        return {"error": "not found"}, 404
    return {"user": {"id": user[0], "email": user[1]}}, 200


def delete_user(request, conn):
    if not is_admin(request.get("token", "")):
        return {"message": "forbidden", "code": 403}, 403
    conn.execute("DELETE FROM users WHERE id = ?", (request["id"],))
    return {"ok": True}, 200


def update_user(request, conn):
    if not request.get("email"):
        return "email is required", 400
    conn.execute(
        "UPDATE users SET email = ? WHERE id = ?", (request["email"], request["id"])
    )
    return {"status": "updated"}, 200
''',
    "billing/invoice.py": '''\
"""Invoice construction and totals."""
from decimal import Decimal


def line_total(item: dict) -> Decimal:
    return Decimal(str(item["price"])) * item["quantity"]


def subtotal(items: list[dict]) -> Decimal:
    return sum((line_total(i) for i in items), Decimal("0"))


def apply_discount(amount: Decimal, percent: int) -> Decimal:
    return amount - (amount * Decimal(percent) / Decimal(100))


def build_invoice(customer: str, items: list[dict], discount: int = 0) -> dict:
    total = apply_discount(subtotal(items), discount)
    return {"customer": customer, "items": items, "total": total}
''',
    "billing/tax.py": '''\
"""Tax rates by region."""
from decimal import Decimal

RATES = {"us": Decimal("0.07"), "eu": Decimal("0.21"), "kr": Decimal("0.10")}


def tax_for(region: str, amount: Decimal) -> Decimal:
    return amount * RATES.get(region, Decimal("0"))
''',
    "reports/aggregate.py": '''\
"""Reporting aggregations."""


def orders_per_customer(orders: list[dict], customers: list[dict]) -> dict:
    """Count orders for each customer."""
    counts = {}
    for customer in customers:
        counts[customer["id"]] = 0
        for order in orders:
            if order["customer_id"] == customer["id"]:
                counts[customer["id"]] += 1
    return counts


def top_customers(orders: list[dict], customers: list[dict], n: int = 10) -> list:
    counts = orders_per_customer(orders, customers)
    return sorted(counts.items(), key=lambda kv: -kv[1])[:n]
''',
    "reports/format.py": '''\
"""Report rendering."""


def as_table(rows: list[tuple]) -> str:
    return "\\n".join(f"{a}\\t{b}" for a, b in rows)
''',
    "storage/db.py": '''\
"""Database connection helpers."""
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT, pw TEXT);
CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY, customer_id INTEGER);
"""


def connect(path: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn
''',
    "tests/test_auth.py": '''\
from api.auth import check_password


def test_check_password_matches():
    assert check_password("5f4dcc3b5aa765d61d8327deb882cf99", "password")
''',
    "tests/test_routes.py": '''\
from api.routes import get_user
from storage.db import connect


def test_get_user_missing():
    body, status = get_user({"email": "nobody@example.com"}, connect())
    assert status == 404
''',
    "tests/test_tax.py": '''\
from decimal import Decimal

from billing.tax import tax_for


def test_us_rate():
    assert tax_for("us", Decimal("100")) == Decimal("7.00")
''',
    "tests/test_aggregate.py": '''\
from reports.aggregate import orders_per_customer


def test_counts():
    orders = [{"customer_id": 1}, {"customer_id": 1}, {"customer_id": 2}]
    customers = [{"id": 1}, {"id": 2}]
    assert orders_per_customer(orders, customers) == {1: 2, 2: 1}
''',
    "README.md": '''\
# demo service

A small order and billing service.

    api/       HTTP routes and auth
    billing/   invoices and tax
    reports/   aggregations
    storage/   database helpers
    tests/     pytest suite
''',
}


def build(root: Path) -> None:
    if root.exists():
        shutil.rmtree(root)
    for relative, body in FILES.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
