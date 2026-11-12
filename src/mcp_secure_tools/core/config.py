from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TL_", env_file=".env", extra="ignore")

    secret_key: SecretStr
    base_url: str = "http://localhost:8100"  # where approval_web is reachable
    db_path: str = "toolcall.db"             # trust-layer tables, shared by every service process
    tenant_file: str = "tenant.toml"         # per-business: customer DB, SMS provider, texts

    session_ttl_s: int = 3600          # hard cap on a session's lifetime (level 0/1 tokens)
    verified_ttl_s: int = 600          # level 2 lasts this long, then drops back to level 1
    approval_ttl_s: int = 300          # approval link lifetime
    approval_max_per_session: int = 3  # SMS sends allowed per session
    default_country_code: str = "91"   # for numbers given without +country
