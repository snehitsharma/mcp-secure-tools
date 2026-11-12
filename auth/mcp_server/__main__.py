"""Run:  TL_SECRET_KEY=... python -m mcp_auth   (MCP endpoint at :8101/mcp)
Reads tenant.toml if present; otherwise a demo customer and console SMS."""
import uvicorn

from shared.config import Settings
from auth.mcp_server.server import build_server
from auth.tenant import build_tenant_auth

if __name__ == "__main__":
    auth = build_tenant_auth(Settings())
    uvicorn.run(build_server(auth).streamable_http_app(), host="127.0.0.1", port=8101)
