"""Login (auth.py, webapp.py) and the identity rule in RepContextMiddleware. Offline, no keys."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import jwt
import pytest
from langgraph_sdk import Auth
from starlette.testclient import TestClient

import auth
from config import DemoUser, parse_auth_users
from conftest import run, scripted
from config import Context
from test_wiring import ask, make
from webapp import app

JANE = DemoUser("jane", "jane-pw", 3)


# ── Settings ──────────────────────────────────────────────────────────────────
def test_auth_users_are_parsed_from_env_format():
    users = parse_auth_users(" Jane:pw:3, margaret:pw2:4 ,")
    assert users == {"jane": DemoUser("jane", "pw", 3), "margaret": DemoUser("margaret", "pw2", 4)}
    for bad in ("jane:pw", "jane::3", "jane:pw:x"):
        with pytest.raises(ValueError):
            parse_auth_users(bad)


def test_server_refuses_to_start_without_login_settings():
    with pytest.raises(RuntimeError, match="AUTH_SECRET"):
        auth.check_settings(secret="short", users={"jane": JANE})
    with pytest.raises(RuntimeError, match="AUTH_USERS"):
        auth.check_settings(secret="x" * 32, users={})


# ── Passwords and tokens ──────────────────────────────────────────────────────
def test_password_check():
    assert auth.check_password("jane", "jane-pw") == JANE
    assert auth.check_password(" JANE ", "jane-pw") == JANE  # usernames are case-insensitive
    assert auth.check_password("jane", "margaret-pw") is None
    assert auth.check_password("nobody", "jane-pw") is None


def test_token_round_trip_carries_the_rep():
    session = auth.issue_token(JANE)
    assert session["user"] == {"username": "jane", "rep_id": 3, "name": "Jane Peacock"}
    claims = auth.verify_token(session["token"])
    assert claims["sub"] == "jane" and claims["rep_id"] == 3


def test_expired_and_tampered_tokens_are_rejected():
    with pytest.raises(jwt.ExpiredSignatureError):
        auth.verify_token(auth.issue_token(JANE, ttl_hours=-1)["token"])
    forged = jwt.encode({"sub": "jane", "rep_id": 4, "exp": int(time.time()) + 60}, "attacker-secret-attacker-secret!!", algorithm="HS256")
    with pytest.raises(jwt.InvalidSignatureError):
        auth.verify_token(forged)


def test_unknown_rep_gets_no_token():
    with pytest.raises(ValueError, match="not an employee"):
        auth.issue_token(DemoUser("ghost", "ghost-pw", 999))


# ── HTTP: /auth/login and /auth/me ────────────────────────────────────────────
def test_login_and_me_endpoints():
    client = TestClient(app)
    assert client.post("/auth/login", json={"username": "jane", "password": "nope"}).status_code == 401
    assert client.post("/auth/login", content=b"not json").status_code == 400
    r = client.post("/auth/login", json={"username": "jane", "password": "jane-pw"})
    assert r.status_code == 200 and r.json()["user"]["rep_id"] == 3
    token = r.json()["token"]
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["user"]["name"] == "Jane Peacock"
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


# ── Agent Server hooks ────────────────────────────────────────────────────────
def test_authenticate_hook():
    token = auth.issue_token(JANE)["token"]
    user = asyncio.run(auth.authenticate(f"Bearer {token}"))
    assert user == {"identity": "jane", "display_name": "Jane Peacock", "rep_id": 3}
    for header in (None, "Basic abc", "Bearer garbage"):
        with pytest.raises(Auth.exceptions.HTTPException) as e:
            asyncio.run(auth.authenticate(header))
        assert e.value.status_code == 401


class _User(dict):
    """Stands in for the server's user proxy: attribute and item access."""

    identity = property(lambda self: self["identity"])
    is_authenticated = True
    display_name = property(lambda self: self["identity"])
    permissions: list = []


def _ctx(resource: str, action: str, user=None) -> Auth.types.AuthContext:
    user = user or _User(identity="jane", rep_id=3)
    return Auth.types.AuthContext(resource=resource, action=action, user=user, permissions=[])


def test_threads_are_tagged_and_filtered_by_owner():
    value = {"metadata": {"graph_id": "sales_assistant"}}
    assert asyncio.run(auth.own_threads(_ctx("threads", "create"), value)) == {"owner": "jane"}
    assert value["metadata"] == {"graph_id": "sales_assistant", "owner": "jane", "rep_id": 3}
    run_value = {"metadata": None}
    asyncio.run(auth.own_threads(_ctx("threads", "create_run"), run_value))
    assert run_value["metadata"] == {"owner": "jane", "rep_id": 3}  # traces can be filtered by rep
    assert asyncio.run(auth.own_threads(_ctx("threads", "search"), {})) == {"owner": "jane"}


def test_studio_sees_everything_and_reps_cannot_touch_the_rest():
    studio = Auth.types.StudioUser("langgraph-studio-user")
    assert asyncio.run(auth.own_threads(_ctx("threads", "search", studio), {})) is None
    assert asyncio.run(auth.deny_by_default(_ctx("crons", "create", studio), {})) is None
    with pytest.raises(Auth.exceptions.HTTPException):
        asyncio.run(auth.deny_by_default(_ctx("store", "get"), {}))
    assert asyncio.run(auth.read_only_assistants(_ctx("assistants", "search"), {})) is None
    with pytest.raises(Auth.exceptions.HTTPException):
        asyncio.run(auth.read_only_assistants(_ctx("assistants", "create"), {}))


# ── RepContextMiddleware: the signed-in rep wins ──────────────────────────────
def _as_user(rep_id: int) -> dict:
    """A run config as the Agent Server builds it for a signed-in user."""
    return {"configurable": {"thread_id": "t", "langgraph_auth_user": SimpleNamespace(identity="u", rep_id=rep_id)}}


def _ask_as(agent, rep_id: int, context: Context):
    from langchain_core.messages import HumanMessage

    return run(agent.ainvoke({"messages": [HumanMessage("hi")]}, _as_user(rep_id), context=context))


def test_signed_in_rep_is_used_without_context():
    main = scripted("Hi Margaret.")
    _ask_as(make(main), 4, Context())
    assert "Margaret Park" in main.prompts[0][0].text


def test_client_cannot_ask_for_another_rep():
    with pytest.raises(PermissionError, match="Signed in as rep 3"):
        _ask_as(make(scripted("hi")), 3, Context(rep_id=4))


def test_studio_and_scripts_still_use_context():
    main = scripted("Hi Jane.")
    run(ask(make(main), "hi"))  # no signed-in user: context {"rep_id": 3}
    assert "Jane Peacock" in main.prompts[0][0].text
