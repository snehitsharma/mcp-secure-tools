"""Run the verification tool on one port: MCP at /mcp, approval page at /a/...

    TL_SECRET_KEY=... python -m mcp_secure_tools.tools.verification

Reads tenant.toml if present; otherwise a demo customer and console SMS.
"""
import os

import uvicorn
from starlette.routing import Mount

from mcp_secure_tools.core.config import Settings
from mcp_secure_tools.tools.verification.approval_web import create_app
from mcp_secure_tools.tools.verification.server import build_server
from mcp_secure_tools.tools.verification.tenant import build_tenant_verification


def main() -> None:
    port = int(os.environ.get("TL_PORT", "8100"))
    os.environ.setdefault("TL_BASE_URL", f"http://localhost:{port}")
    verification = build_tenant_verification(Settings())
    app = build_server(verification).streamable_http_app()
    app.router.routes.append(Mount("/", app=create_app(verification)))
    uvicorn.run(app, host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
