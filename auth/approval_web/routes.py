"""Approval page. GET shows the buttons and changes nothing, so link scanners
and SMS previews can't approve. Only the POST records a decision."""
from __future__ import annotations

from html import escape
from typing import Literal

from fastapi import APIRouter, Form
from fastapi.responses import HTMLResponse

from auth.core.service import AuthService
from shared.contracts.auth import AuthError
from shared.contracts.verification import ApprovalKind, ApprovalStatus

_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",  # the secret is in the URL
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'",
}

_STYLE = (
    "body{font-family:system-ui,sans-serif;max-width:28rem;margin:3rem auto;padding:0 1rem;"
    "line-height:1.5}button{font-size:1rem;padding:.75rem 1.25rem;margin:.25rem .5rem 0 0;"
    "border-radius:.5rem;border:1px solid #888;cursor:pointer}.ok{background:#1a7f37;color:#fff;"
    "border-color:#1a7f37}"
)

_ERRORS = {
    "invalid_link": ("Link not valid", 404),
    "expired_link": ("Link expired", 410),
    "not_pending": ("Already used", 410),
}


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{escape(title)}</title><style>{_STYLE}</style></head>"
        f"<body><h1>{escape(title)}</h1>{body}</body></html>"
    )
    return HTMLResponse(html, status_code=status, headers=_HEADERS)


def _error(code: str) -> HTMLResponse:
    title, status = _ERRORS.get(code, ("Could not complete", 409))
    return _page(title, "<p>Ask the agent to send a new link if you still need one.</p>", status)


def _form(approval_id: str, s: str, kind: ApprovalKind, error: str = "") -> HTMLResponse:
    action = f"/a/{escape(approval_id)}"
    hidden = f"<input type='hidden' name='s' value='{escape(s)}'>"
    err = f"<p style='color:#b42318'>{escape(error)}</p>" if error else ""
    if kind is ApprovalKind.REGISTER:
        body = (
            "<p>Confirm this is your number to finish signing up.</p>"
            f"<form method='post' action='{action}'>{hidden}{err}"
            "<label for='name'>Your name</label><br>"
            "<input id='name' name='name' maxlength='60' required autocomplete='name' "
            "style='font-size:1rem;padding:.6rem;width:100%;margin:.25rem 0 1rem'>"
            "<button class='ok' name='decision' value='approve'>Sign up</button>"
            "<button name='decision' value='reject' formnovalidate>This wasn't me</button></form>"
        )
        return _page("Sign up", body, 422 if error else 200)
    title = "Sign in" if kind is ApprovalKind.SIGNIN else "Confirm it's you"
    body = (
        "<p>Approve the request you just made on your call or chat?</p>"
        f"<form method='post' action='{action}'>{hidden}"
        "<button class='ok' name='decision' value='approve'>Approve</button>"
        "<button name='decision' value='reject'>This wasn't me</button></form>"
    )
    return _page(title, body)


def build_router(auth: AuthService) -> APIRouter:
    router = APIRouter()

    @router.get("/a/{approval_id}/{s}")
    def show(approval_id: str, s: str) -> HTMLResponse:
        try:
            approval = auth.inspect_link(approval_id, s)
        except AuthError as e:
            return _error(e.code)
        if approval.status is ApprovalStatus.EXPIRED:
            return _error("expired_link")
        if approval.status is not ApprovalStatus.PENDING:
            return _error("not_pending")
        return _form(approval_id, s, approval.kind)

    @router.post("/a/{approval_id}")
    def decide(
        approval_id: str,
        s: str = Form(...),
        decision: Literal["approve", "reject"] = Form(...),
        name: str = Form(""),
    ) -> HTMLResponse:
        try:
            approval = auth.decide_link(approval_id, s, approve=decision == "approve", name=name)
        except AuthError as e:
            if e.code == "name_required":
                return _form(approval_id, s, ApprovalKind.REGISTER, error="Please enter your name.")
            return _error(e.code)
        if decision == "approve":
            done = "You're signed up" if approval.kind is ApprovalKind.REGISTER else "You're verified"
            return _page("Approved", f"<p>{done}. You can return to your call or chat.</p>")
        return _page("Declined", "<p>Nothing was approved. You can close this page.</p>")

    return router
