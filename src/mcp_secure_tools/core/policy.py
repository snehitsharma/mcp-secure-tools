"""Which scopes each level grants. Cumulative: a level gets everything below it.

    0 anonymous   unknown caller: may ask to sign in / sign up
    1 identified  caller ID matches a customer: may ask for verification
    2 verified    tapped the SMS approval link: may do sensitive actions

Add your own tools' scopes here, e.g. "payment:create" at level 2.
"""
from mcp_secure_tools.core.contracts.auth import Level

_GRANTS: dict[Level, frozenset[str]] = {
    Level.ANONYMOUS: frozenset({"customer:register"}),
    Level.IDENTIFIED: frozenset({"verification:request"}),
    Level.VERIFIED: frozenset({"payment:create"}),  # example sensitive action
}


def scopes_for(level: Level) -> frozenset[str]:
    out: set[str] = set()
    for lvl, scopes in _GRANTS.items():
        if lvl <= level:
            out |= scopes
    return frozenset(out)
