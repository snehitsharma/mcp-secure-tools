from __future__ import annotations

import re
from typing import Protocol

from pydantic import BaseModel, ConfigDict

_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def normalize_phone(raw: str | None) -> str | None:
    """Strip separators; return E.164 or None if it isn't a valid number."""
    if not raw:
        return None
    phone = re.sub(r"[\s\-().]", "", raw)
    return phone if _E164.fullmatch(phone) else None


class Customer(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    phone: str  # registered number, E.164


class CustomerDirectory(Protocol):
    def get(self, customer_id: str) -> Customer | None: ...
    def by_phone(self, phone: str) -> Customer | None: ...


class CustomerRegistrar(Protocol):
    """Creates customers the business DB doesn't know yet (our own table)."""

    def register(self, name: str, phone: str) -> Customer:
        """Idempotent on phone: an existing number returns the existing customer."""
        ...
