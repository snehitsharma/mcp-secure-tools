"""Approval web page: where the SMS link lands. Talks to auth core only."""
from fastapi import FastAPI

from auth.approval_web.routes import build_router
from auth import AuthService


def create_app(auth: AuthService) -> FastAPI:
    app = FastAPI(title="approval", docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(build_router(auth))
    return app


__all__ = ["create_app"]
