"""In-memory stand-ins for the clock, the SMS provider and the customer DB."""
from __future__ import annotations

import itertools
import re

from mcp_secure_tools.core.contracts.customers import Customer
from mcp_secure_tools.core.contracts.messaging import OutboundSms

DEV_CUSTOMERS = [Customer(id="c_1", name="Asha", phone="+919800000001")]

class FakeClock:
    def __init__(self, start: int = 1_700_000_000) -> None:
        self.now = start

    def __call__(self) -> int:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += seconds


class FakeSms:
    def __init__(self, echo: bool = False) -> None:
        self.outbox: list[OutboundSms] = []
        self.fail = False
        self.echo = echo
        self._ids = itertools.count(1)

    def send_sms(self, msg: OutboundSms) -> str:
        if self.fail:
            raise RuntimeError("provider down")
        self.outbox.append(msg)
        if self.echo:
            print(f"[fake sms -> {msg.to}] {msg.body}", flush=True)
        return f"fake-{next(self._ids)}"

    def last_link(self) -> str:
        match = re.search(r"https?://\S+", self.outbox[-1].body)
        assert match, "no link in last SMS"
        return match.group(0)


class InMemoryCustomers:
    def __init__(self, customers: list[Customer]) -> None:
        self._by_id = {c.id: c for c in customers}

    def get(self, customer_id: str) -> Customer | None:
        return self._by_id.get(customer_id)

    def by_phone(self, phone: str) -> Customer | None:
        return next((c for c in self._by_id.values() if c.phone == phone), None)
