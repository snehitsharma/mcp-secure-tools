"""The SQL adapter against differently shaped 'business' schemas."""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from customers.sql import SqlCustomerDirectory, SqlDirectoryConfig


def _engine(ddl: str, rows: list[str]):
    e = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    with e.begin() as c:
        c.execute(text(ddl))
        for r in rows:
            c.execute(text(r))
    return e


def test_national_format_custom_columns():
    e = _engine(
        "CREATE TABLE clients (client_no INTEGER, full_name TEXT, mobile TEXT)",
        ["INSERT INTO clients VALUES (42, 'Asha', '9800000001')"],
    )
    d = SqlCustomerDirectory(
        SqlDirectoryConfig(table="clients", id_column="client_no", name_column="full_name",
                           phone_column="mobile", phone_format="national", country_code="91"),
        engine=e,
    )
    c = d.by_phone("+919800000001")
    assert c is not None and c.id == "42" and c.phone == "+919800000001"
    assert d.get("42").name == "Asha"
    assert d.by_phone("+14155550100") is None  # other country never matches national


def test_cc_digits_format():
    e = _engine("CREATE TABLE customers (id TEXT, name TEXT, phone TEXT)",
                ["INSERT INTO customers VALUES ('c1', 'Ravi', '919800000002')"])
    d = SqlCustomerDirectory(SqlDirectoryConfig(table="customers", phone_format="cc_digits"), engine=e)
    assert d.by_phone("+919800000002").id == "c1"


def test_shared_number_identifies_nobody():
    e = _engine("CREATE TABLE customers (id TEXT, name TEXT, phone TEXT)", [
        "INSERT INTO customers VALUES ('c1', 'A', '+919800000003')",
        "INSERT INTO customers VALUES ('c2', 'B', '+919800000003')",
    ])
    d = SqlCustomerDirectory(SqlDirectoryConfig(table="customers"), engine=e)
    assert d.by_phone("+919800000003") is None


def test_unusable_stored_number_is_skipped():
    e = _engine("CREATE TABLE customers (id TEXT, name TEXT, phone TEXT)",
                ["INSERT INTO customers VALUES ('c1', 'A', 'n/a')"])
    d = SqlCustomerDirectory(SqlDirectoryConfig(table="customers"), engine=e)
    assert d.get("c1") is None


def test_custom_queries_for_complex_schema():
    e = _engine("CREATE TABLE people (pid TEXT, nm TEXT, deleted INTEGER)", [
        "INSERT INTO people VALUES ('p1', 'Asha', 0)",
        "INSERT INTO people VALUES ('p2', 'Gone', 1)",
    ])
    with e.begin() as c:
        c.execute(text("CREATE TABLE phones (pid TEXT, num TEXT, is_primary INTEGER)"))
        c.execute(text("INSERT INTO phones VALUES ('p1', '+919800000001', 1), ('p2', '+919800000009', 1)"))
    base = ("SELECT p.pid AS id, p.nm AS name, ph.num AS phone FROM people p "
            "JOIN phones ph ON ph.pid = p.pid AND ph.is_primary = 1 WHERE p.deleted = 0 AND ")
    d = SqlCustomerDirectory(
        SqlDirectoryConfig(by_id_query=base + "p.pid = :value", by_phone_query=base + "ph.num = :value"),
        engine=e,
    )
    assert d.by_phone("+919800000001").id == "p1"
    assert d.by_phone("+919800000009") is None  # soft-deleted
    assert d.get("p1").phone == "+919800000001"


def test_identifiers_are_quoted_not_interpolated():
    e = _engine('CREATE TABLE "weird table" (id TEXT, name TEXT, phone TEXT)',
                ["INSERT INTO \"weird table\" VALUES ('c1', 'A', '+919800000001')"])
    d = SqlCustomerDirectory(SqlDirectoryConfig(table="weird table"), engine=e)
    assert d.by_phone("+919800000001").id == "c1"


def test_config_requires_table_or_queries():
    with pytest.raises(ValueError):
        SqlDirectoryConfig()


def test_missing_db_url_env(monkeypatch):
    monkeypatch.delenv("TL_CUSTOMERS_DB_URL", raising=False)
    with pytest.raises(RuntimeError, match="TL_CUSTOMERS_DB_URL"):
        SqlCustomerDirectory(SqlDirectoryConfig(table="customers"))
