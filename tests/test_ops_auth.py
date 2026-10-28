from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.auth_deps import require_role
from app.main import app
from app.security import make_token


def test_ask_route_is_mounted() -> None:
    paths = {route.path for route in app.routes}
    assert "/api/ops/ask" in paths


def test_missing_token_is_401() -> None:
    dependency = require_role("admin")
    with pytest.raises(HTTPException) as excinfo:
        dependency(x_auth_token=None)
    assert excinfo.value.status_code == 401


def test_forged_token_is_401() -> None:
    dependency = require_role("admin")
    with pytest.raises(HTTPException) as excinfo:
        dependency(x_auth_token="1.admin.9999999999.deadbeef")
    assert excinfo.value.status_code == 401


def test_student_role_is_403() -> None:
    dependency = require_role("admin")
    token = make_token(2, "student")
    with pytest.raises(HTTPException) as excinfo:
        dependency(x_auth_token=token)
    assert excinfo.value.status_code == 403


def test_rider_role_is_403() -> None:
    dependency = require_role("admin")
    token = make_token(3, "rider")
    with pytest.raises(HTTPException) as excinfo:
        dependency(x_auth_token=token)
    assert excinfo.value.status_code == 403


def test_admin_role_is_allowed() -> None:
    dependency = require_role("admin")
    token = make_token(1, "admin")
    assert dependency(x_auth_token=token) == (1, "admin")


def test_multi_role_accepts_each_listed_role() -> None:
    dependency = require_role("admin", "rider")
    assert dependency(x_auth_token=make_token(3, "rider")) == (3, "rider")
    with pytest.raises(HTTPException) as excinfo:
        dependency(x_auth_token=make_token(2, "student"))
    assert excinfo.value.status_code == 403