"""Customers we registered ourselves (the business DB stays read-only).
Owns table: customers_registered.

CompositeDirectory is what everything else should use: the business's own
directory first, then ours. A phone the business already knows never gets a
second identity here."""
from __future__ import annotations

import secrets
import sqlite3
from collections.abc import Callable

from mcp_secure_tools.core.contracts.customers import Customer, CustomerDirectory, normalize_phone
from mcp_secure_tools.core.db import Database

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers_registered (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    phone       TEXT NOT NULL UNIQUE,
    created_at  INTEGER NOT NULL
);
"""


class CustomerRegistry:
    def __init__(self, db: Database, clock: Callable[[], int]) -> None:
        self._db = db
        self._clock = clock
        db.migrate(SCHEMA)

    def get(self, customer_id: str) -> Customer | None:
        row = self._db.one("SELECT * FROM customers_registered WHERE id = ?", (customer_id,))
        return Customer(id=row["id"], name=row["name"], phone=row["phone"]) if row else None

    def by_phone(self, phone: str) -> Customer | None:
        row = self._db.one("SELECT * FROM customers_registered WHERE phone = ?", (phone,))
        return Customer(id=row["id"], name=row["name"], phone=row["phone"]) if row else None

    def register(self, name: str, phone: str) -> Customer:
        e164 = normalize_phone(phone)
        if e164 is None:
            raise ValueError("invalid phone")
        existing = self.by_phone(e164)
        if existing:
            return existing
        cid = "cr_" + secrets.token_urlsafe(9)
        try:
            self._db.execute(
                "INSERT INTO customers_registered (id, name, phone, created_at) VALUES (?, ?, ?, ?)",
                (cid, name, e164, self._clock()))
        except sqlite3.IntegrityError:  # registered concurrently
            return self.by_phone(e164)
        return self.get(cid)


class CompositeDirectory:
    """Business directory first, then our registry. Also the registrar."""

    def __init__(self, primary: CustomerDirectory, registry: CustomerRegistry) -> None:
        self._primary = primary
        self._registry = registry

    def get(self, customer_id: str) -> Customer | None:
        return self._primary.get(customer_id) or self._registry.get(customer_id)

    def by_phone(self, phone: str) -> Customer | None:
        return self._primary.by_phone(phone) or self._registry.by_phone(phone)

    def register(self, name: str, phone: str) -> Customer:
        e164 = normalize_phone(phone)
        known = self._primary.by_phone(e164) if e164 else None
        return known or self._registry.register(name, phone)
