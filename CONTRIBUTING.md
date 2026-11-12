# Contributing

## Setup

```sh
pip install -e ".[dev]"
ruff check src tests
pytest -q
```

## The one rule

**Identity never comes from the model.** A tool learns who it is serving only from the token in
the request's `Authorization` header, checked by the gate. Never accept a customer id, phone
number or level as a tool argument and trust it.

## Adding a tool

Each tool is a folder under `src/mcp_secure_tools/tools/<name>/`:

```
tools/<name>/
  __init__.py     build_<name>(...): wires the service
  service.py      the logic. No HTTP, no MCP: plain Python, easy to test
  server.py       the MCP tools: gate.require(...) first, then call the service
  __main__.py     python -m mcp_secure_tools.tools.<name>
```

1. Pick the minimum level and a scope for each tool, and add the scope to `core/policy.py`.
2. Start every tool function with the gate:
   ```python
   claims = gate.require(ctx, min_level=Level.VERIFIED, scopes={"payment:create"})
   ```
3. Return results with `respond(ToolResult(...))` so failures carry a machine-readable `code`
   the model can act on.
4. Add tests under `tests/tools/<name>/` (the fixtures in `tests/conftest.py` give you a
   session, a token and an MCP client).
5. Add the tool to the table in `README.md` and an entry in `CHANGELOG.md`.

## Pull requests

Keep them small and focused, with tests. CI runs lint and tests on Python 3.12 and 3.13.
