"""Verification's part of tenant.toml: whose customer DB, which SMS provider,
what the SMS says. The logic is identical for every business; only this config differs.

Secrets (DB URL, provider keys) are never in tenant.toml; it names the env
vars that hold them.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from mcp_secure_tools.core.config import Settings
from mcp_secure_tools.core.customers import DirectoryConfig, MemoryDirectoryConfig, build_directory
from mcp_secure_tools.core.db import Database
from mcp_secure_tools.core.tenant import load_tenant_file
from mcp_secure_tools.providers.sms import ConsoleConfig, SmsConfig, build_sms
from mcp_secure_tools.tools.verification import VerificationService, build_verification
from mcp_secure_tools.tools.verification.service import DEFAULT_APPROVAL_TEXT, DEFAULT_REGISTRATION_TEXT


class Messages(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # {link} and {minutes}. Must match your DLT-registered template word for word.
    approval_link: str = DEFAULT_APPROVAL_TEXT
    registration_link: str = DEFAULT_REGISTRATION_TEXT


class VerificationTenantConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")  # other modules' sections live in the same file

    customers: DirectoryConfig = Field(default_factory=MemoryDirectoryConfig)
    sms: SmsConfig = Field(default_factory=ConsoleConfig)
    messages: Messages = Field(default_factory=Messages)


def load_tenant(path: str | Path) -> VerificationTenantConfig:
    raw = load_tenant_file(path)
    if raw is None:
        raise FileNotFoundError(path)
    return VerificationTenantConfig.model_validate(raw)


def dev_tenant() -> VerificationTenantConfig:
    """No tenant.toml: in-memory demo customer, SMS printed to the console."""
    from mcp_secure_tools.core.fakes import DEV_CUSTOMERS

    return VerificationTenantConfig(customers=MemoryDirectoryConfig(customers=DEV_CUSTOMERS))


def build_tenant_verification(settings: Settings, tenant: VerificationTenantConfig | None = None) -> VerificationService:
    if tenant is None:
        raw: dict[str, Any] | None = load_tenant_file(settings.tenant_file)
        tenant = VerificationTenantConfig.model_validate(raw) if raw is not None else dev_tenant()
    db = Database(settings.db_path)
    return build_verification(
        settings,
        build_directory(tenant.customers, db),  # business DB + our registry
        build_sms(tenant.sms),
        db=db,
        approval_text=tenant.messages.approval_link,
        registration_text=tenant.messages.registration_link,
    )
