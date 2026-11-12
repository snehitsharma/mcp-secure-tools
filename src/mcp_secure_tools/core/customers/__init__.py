"""Customer directory adapters. Auth only sees the CustomerDirectory protocol
(contracts/customers.py); which business DB sits behind it is configuration."""
from __future__ import annotations

import time
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from mcp_secure_tools.core.contracts.customers import Customer, CustomerDirectory
from mcp_secure_tools.core.customers.registry import CompositeDirectory, CustomerRegistry
from mcp_secure_tools.core.customers.sql import SqlCustomerDirectory, SqlDirectoryConfig
from mcp_secure_tools.core.db import Database


class MemoryDirectoryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: Literal["memory"] = "memory"
    customers: list[Customer] = Field(default_factory=list)


DirectoryConfig = Annotated[
    SqlDirectoryConfig | MemoryDirectoryConfig, Field(discriminator="backend")
]


def build_directory(
    cfg: SqlDirectoryConfig | MemoryDirectoryConfig, db: Database | None = None
) -> CustomerDirectory:
    """With a db: the business directory plus our own registry (and registration).
    Without: the business directory alone (read-only)."""
    if isinstance(cfg, SqlDirectoryConfig):
        primary: CustomerDirectory = SqlCustomerDirectory(cfg)
    else:
        from mcp_secure_tools.core.fakes import InMemoryCustomers

        primary = InMemoryCustomers(cfg.customers)
    if db is None:
        return primary
    return CompositeDirectory(primary, CustomerRegistry(db, lambda: int(time.time())))


__all__ = ["CompositeDirectory", "CustomerRegistry", "DirectoryConfig", "build_directory",
           "SqlCustomerDirectory", "SqlDirectoryConfig"]
