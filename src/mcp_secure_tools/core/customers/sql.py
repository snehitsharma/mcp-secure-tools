"""Read-only customer lookup against a business's own SQL database.

Each business keeps its schema. tenant.toml maps it: table and column names,
how phones are stored, or a custom query for anything more complex. Auth logic
never changes; only this mapping does. Use a read-only DB user.
"""
from __future__ import annotations

import os
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import Engine, bindparam, column, create_engine, select, table, text

from mcp_secure_tools.core.contracts.customers import Customer, normalize_phone


class SqlDirectoryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: Literal["sql"] = "sql"
    url_env: str = "TL_CUSTOMERS_DB_URL"  # DSN lives in env, never in the file

    # simple mapping
    table: str | None = None
    db_schema: str | None = None
    id_column: str = "id"
    name_column: str = "name"
    phone_column: str = "phone"

    # how the business stores phone numbers
    #   e164      "+919800000001"
    #   cc_digits "919800000001"
    #   national  "9800000001" (country_code added on read, stripped on lookup)
    phone_format: Literal["e164", "cc_digits", "national"] = "e164"
    country_code: str = "91"

    # escape hatch for complex schemas (joins, soft deletes, multiple phones).
    # Must return columns id, name, phone; bound parameter is :value.
    by_id_query: str | None = None
    by_phone_query: str | None = None

    @model_validator(mode="after")
    def _needs_table_or_queries(self) -> SqlDirectoryConfig:
        if self.table is None and not (self.by_id_query and self.by_phone_query):
            raise ValueError("set `table`, or both `by_id_query` and `by_phone_query`")
        return self


class SqlCustomerDirectory:
    def __init__(self, cfg: SqlDirectoryConfig, engine: Engine | None = None) -> None:
        self._cfg = cfg
        if engine is None:
            url = os.environ.get(cfg.url_env)
            if not url:
                raise RuntimeError(f"customer DB URL missing: set {cfg.url_env}")
            engine = create_engine(url, pool_pre_ping=True)
        self._engine = engine
        self._by_id = self._query(cfg.by_id_query, cfg.id_column)
        self._by_phone = self._query(cfg.by_phone_query, cfg.phone_column)

    def get(self, customer_id: str) -> Customer | None:
        rows = self._run(self._by_id, customer_id)
        return self._to_customer(rows[0]) if len(rows) == 1 else None

    def by_phone(self, phone: str) -> Customer | None:
        stored = self._to_stored(phone)
        if stored is None:
            return None
        rows = self._run(self._by_phone, stored)
        # A number shared by several customers identifies nobody.
        return self._to_customer(rows[0]) if len(rows) == 1 else None

    # -- internals -------------------------------------------------------

    def _query(self, custom: str | None, where_column: str):
        if custom:
            return text(custom)
        c = self._cfg
        t = table(c.table, column(c.id_column), column(c.name_column), column(c.phone_column),
                  schema=c.db_schema)
        # Identifiers go through SQLAlchemy's quoting; values are bound params.
        return (
            select(
                t.c[c.id_column].label("id"),
                t.c[c.name_column].label("name"),
                t.c[c.phone_column].label("phone"),
            )
            .where(t.c[where_column] == bindparam("value"))
            .limit(2)
        )

    def _run(self, stmt, value: str) -> list:
        with self._engine.connect() as conn:
            return list(conn.execute(stmt, {"value": value}).mappings().fetchmany(2))

    def _to_stored(self, e164: str) -> str | None:
        e164 = normalize_phone(e164)
        if e164 is None:
            return None
        fmt, cc = self._cfg.phone_format, self._cfg.country_code
        if fmt == "e164":
            return e164
        if fmt == "cc_digits":
            return e164[1:]
        return e164[1 + len(cc):] if e164.startswith("+" + cc) else None

    def _to_e164(self, stored: object) -> str | None:
        digits = re.sub(r"\D", "", str(stored or ""))
        fmt, cc = self._cfg.phone_format, self._cfg.country_code
        if fmt == "national":
            digits = cc + digits.lstrip("0")
        return normalize_phone("+" + digits)

    def _to_customer(self, row) -> Customer | None:
        phone = self._to_e164(row["phone"])
        if phone is None:  # unusable number on file -> can't verify this customer
            return None
        return Customer(id=str(row["id"]), name=str(row["name"] or ""), phone=phone)
