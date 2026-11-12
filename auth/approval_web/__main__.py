"""Run:  TL_SECRET_KEY=... python -m approval_web   (serves :8100/a/...)"""
import uvicorn

from auth.approval_web import create_app
from shared.config import Settings
from auth.tenant import build_tenant_auth

if __name__ == "__main__":
    uvicorn.run(create_app(build_tenant_auth(Settings())), host="127.0.0.1", port=8100)
