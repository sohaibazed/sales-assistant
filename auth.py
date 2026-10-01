"""Login for the Agent Server (``auth`` in langgraph.json): who is calling, and what they may see.

    POST /auth/login (webapp.py) ─▶ checks AUTH_USERS, returns a signed token with the rep inside
    every API request  ─▶ @auth.authenticate checks the token ─▶ user {identity, rep_id}
                       ─▶ @auth.on.threads tags new threads with their owner and filters reads,
                          so a rep only ever sees their own conversations
    every run          ─▶ RepContextMiddleware takes rep_id from that user, not from the client

The demo users and the signing secret live in .env (AUTH_USERS, AUTH_SECRET). In production
``authenticate`` would verify an Okta / Auth0 JWT instead; the handlers stay the same.

LangSmith Studio connects with its own scheme and arrives as a ``StudioUser``: it skips the
token check, sees everything, and sets ``rep_id`` in the run context as before.
"""

from __future__ import annotations

import hmac
import time
from typing import Any

import jwt
from langgraph_sdk import Auth

from config import AUTH_SECRET, AUTH_TOKEN_TTL_HOURS, DemoUser, auth_users
from tools.sql import query_one

ALGORITHM = "HS256"
MIN_SECRET_LENGTH = 32


def check_settings(secret: str = AUTH_SECRET, users: dict[str, DemoUser] | None = None) -> dict[str, DemoUser]:
    """Fail at server start, not at first login, when .env is missing the login settings."""
    if len(secret) < MIN_SECRET_LENGTH:
        raise RuntimeError(
            f"AUTH_SECRET must be set in .env (at least {MIN_SECRET_LENGTH} characters). "
            'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(32))"'
        )
    users = auth_users() if users is None else users
    if not users:
        raise RuntimeError('AUTH_USERS must be set in .env, e.g. AUTH_USERS="jane:<password>:3,margaret:<password>:4"')
    return users


USERS = check_settings()


# ── Passwords and tokens ──────────────────────────────────────────────────────
def check_password(username: str, password: str, users: dict[str, DemoUser] | None = None) -> DemoUser | None:
    """The user if the password matches. Constant-time compare, also for unknown usernames."""
    user = (USERS if users is None else users).get(username.strip().lower())
    expected = user.password if user else "\0"
    ok = hmac.compare_digest(password.encode(), expected.encode())
    return user if ok and user else None


def rep_name(rep_id: int) -> str | None:
    row = query_one("SELECT FirstName || ' ' || LastName AS name FROM Employee WHERE EmployeeId = ?", (rep_id,))
    return row["name"] if row else None


def issue_token(user: DemoUser, *, secret: str = AUTH_SECRET, ttl_hours: float = AUTH_TOKEN_TTL_HOURS) -> dict[str, Any]:
    """Sign a token for a user whose password was just checked. Refuses a rep that doesn't exist."""
    name = rep_name(user.rep_id)
    if name is None:
        raise ValueError(f"AUTH_USERS maps {user.username!r} to rep_id {user.rep_id}, which is not an employee")
    now = int(time.time())
    claims = {"sub": user.username, "rep_id": user.rep_id, "name": name, "iat": now, "exp": now + int(ttl_hours * 3600)}
    return {
        "token": jwt.encode(claims, secret, algorithm=ALGORITHM),
        "user": {"username": user.username, "rep_id": user.rep_id, "name": name},
        "expires_at": claims["exp"],
    }


def verify_token(token: str, *, secret: str = AUTH_SECRET) -> dict[str, Any]:
    """The token's claims, or ``jwt.InvalidTokenError`` (expired, tampered, malformed)."""
    claims = jwt.decode(token, secret, algorithms=[ALGORITHM], options={"require": ["sub", "exp"]})
    if not isinstance(claims.get("rep_id"), int):
        raise jwt.InvalidTokenError("token has no rep_id")
    return claims


def bearer_token(authorization: str | None) -> str | None:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


# ── The Agent Server hooks ────────────────────────────────────────────────────
auth = Auth()


@auth.authenticate
async def authenticate(authorization: str | None) -> Auth.types.MinimalUserDict:
    token = bearer_token(authorization)
    if not token:
        raise Auth.exceptions.HTTPException(status_code=401, detail="Sign in first.")
    try:
        claims = verify_token(token)
    except jwt.ExpiredSignatureError:
        raise Auth.exceptions.HTTPException(status_code=401, detail="Session expired. Sign in again.") from None
    except jwt.InvalidTokenError:
        raise Auth.exceptions.HTTPException(status_code=401, detail="Invalid session. Sign in again.") from None
    return {"identity": claims["sub"], "display_name": claims.get("name", claims["sub"]), "rep_id": claims["rep_id"]}


def _is_studio(user: Any) -> bool:
    return isinstance(user, Auth.types.StudioUser)


@auth.on
async def deny_by_default(ctx: Auth.types.AuthContext, value: Any) -> None:
    """Anything without a more specific rule below (crons, the store, stateless runs) is off-limits."""
    if not _is_studio(ctx.user):
        raise Auth.exceptions.HTTPException(status_code=403, detail=f"Not allowed: {ctx.resource}.{ctx.action}")


@auth.on.threads
async def own_threads(ctx: Auth.types.AuthContext, value: Any) -> Auth.types.FilterType | None:
    """Tag what a rep creates with their identity, and only let them reach their own threads."""
    if _is_studio(ctx.user):
        return None
    if ctx.action in ("create", "create_run", "update") and isinstance(value, dict):
        if value.get("metadata") is None:
            value["metadata"] = {}
        # In place: the server keeps a reference to this dict, a replacement would be ignored.
        value["metadata"].update(owner=ctx.user.identity, rep_id=ctx.user["rep_id"])
    return {"owner": ctx.user.identity}


@auth.on.assistants
async def read_only_assistants(ctx: Auth.types.AuthContext, value: Any) -> None:
    """Reps may use the assistants, not create or change them."""
    if not _is_studio(ctx.user) and ctx.action not in ("read", "search"):
        raise Auth.exceptions.HTTPException(status_code=403, detail="Assistants are read-only.")
