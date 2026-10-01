"""Custom routes for the Agent Server (http.app in langgraph.json): login, and the chat UI at /app.

    POST /auth/login   {"username", "password"} -> {"token", "user", "expires_at"} or 401
    GET  /auth/me      Authorization: Bearer <token> -> {"user"} or 401
    /app/              the chat UI (static export of ui/: `cd ui && pnpm build:static` -> ui/out)

Custom routes skip the server's auth (auth.py), which is what a login endpoint needs; /auth/me
checks the token itself. Every API call the UI makes (/threads, /runs, ...) goes through auth.py.
The UI is mounted under /app, not /, because custom routes take precedence over the server's own.
"""

from __future__ import annotations

import asyncio

import jwt
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from auth import bearer_token, check_password, issue_token, verify_token
from config import REPO_ROOT

UI_DIR = REPO_ROOT / "ui" / "out"


async def login(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        username, password = str(body["username"]), str(body["password"])
    except (ValueError, KeyError, TypeError):
        return JSONResponse({"detail": "Send JSON with username and password."}, status_code=400)
    user = check_password(username, password)
    if user is None:
        return JSONResponse({"detail": "Wrong username or password."}, status_code=401)
    try:
        session = await asyncio.to_thread(issue_token, user)
    except ValueError as e:  # AUTH_USERS points at a rep that doesn't exist
        return JSONResponse({"detail": str(e)}, status_code=500)
    return JSONResponse(session)


async def me(request: Request) -> JSONResponse:
    token = bearer_token(request.headers.get("authorization"))
    try:
        claims = verify_token(token or "")
    except jwt.InvalidTokenError:
        return JSONResponse({"detail": "Sign in first."}, status_code=401)
    return JSONResponse({"user": {"username": claims["sub"], "rep_id": claims["rep_id"], "name": claims.get("name")}})


async def _to_ui(request):
    return RedirectResponse("/app/")


async def _not_built(request):
    return PlainTextResponse("Chat UI not built. Run: cd ui && npx pnpm@10.5.1 build:static", status_code=503)


routes = [
    Route("/auth/login", login, methods=["POST"]),
    Route("/auth/me", me, methods=["GET"]),
    Route("/app", _to_ui),
]
if (UI_DIR / "index.html").exists():
    routes.append(Mount("/app", app=StaticFiles(directory=UI_DIR, html=True), name="ui"))
else:
    routes.append(Route("/app/{path:path}", _not_built))

app = Starlette(routes=routes)
