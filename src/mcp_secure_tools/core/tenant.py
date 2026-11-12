"""Loads tenant.toml: the per-business settings file. Each module validates only
its own sections (auth: customers/sms/messages), so
modules stay independent of each other's config."""
from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any


def load_tenant_file(path: str | Path) -> dict[str, Any] | None:
    """Parsed TOML, or None when the file doesn't exist (dev/demo mode)."""
    p = Path(path)
    if not p.exists():
        return None
    with p.open("rb") as f:
        return tomllib.load(f)
