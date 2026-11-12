"""Auth's part of tenant.toml: whose customer DB, which SMS provider, what the
SMS says. Auth logic is identical for every business; only this config differs.

Secrets (DB URL, provider keys) are never in tenant.toml; it names the env
vars that hold them.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from auth import AuthService, build_auth
from auth.core.service import DEFAULT_APPROVAL_TEXT, DEFAULT_REGISTRATION_TEXT
from customers import DirectoryConfig, MemoryDirectoryConfig, build_directory
from providers.sms import ConsoleConfig, SmsConfig, build_sms
from shared.config import Settings
from shared.db import Database
from shared.tenant import load_tenant_file


class Messages(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # {link} and {minutes}. Must match your DLT-registered template word for word.
    approval_link: str = DEFAULT_APPROVAL_TEXT
    registration_link: str = DEFAULT_REGISTRATION_TEXT


class AuthTenantConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")  # other modules' sections live in the same file

    customers: DirectoryConfig = Field(default_factory=MemoryDirectoryConfig)
    sms: SmsConfig = Field(default_factory=ConsoleConfig)
    messages: Messages = Field(default_factory=Messages)


def load_tenant(path: str | Path) -> AuthTenantConfig:
    raw = load_tenant_file(path)
    if raw is None:
        raise FileNotFoundError(path)
    return AuthTenantConfig.model_validate(raw)


def dev_tenant() -> AuthTenantConfig:
    """No tenant.toml: in-memory demo customer, SMS printed to the console."""
    from shared.fakes import DEV_CUSTOMERS

    return AuthTenantConfig(customers=MemoryDirectoryConfig(customers=DEV_CUSTOMERS))


def build_tenant_auth(settings: Settings, tenant: AuthTenantConfig | None = None) -> AuthService:
    if tenant is None:
        raw: dict[str, Any] | None = load_tenant_file(settings.tenant_file)
        tenant = AuthTenantConfig.model_validate(raw) if raw is not None else dev_tenant()
    db = Database(settings.db_path)
    return build_auth(
        settings,
        build_directory(tenant.customers, db),  # business DB + our registry
        build_sms(tenant.sms),
        db=db,
        approval_text=tenant.messages.approval_link,
        registration_text=tenant.messages.registration_link,
    )
