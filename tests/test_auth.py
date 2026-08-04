from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from app.auth import normalize_account, normalize_phone, verify_password
from app.main import create_app


def _register(client: TestClient, *, account: str, phone: str, password: str = "Password-123"):
    return client.post(
        "/auth/register",
        json={"account": account, "phone": phone, "password": password},
    )


def test_registers_password_user_sets_cookie_and_hides_sensitive_fields(client, app):
    response = _register(client, account="\u4e2d\u6587\u7528\u6237", phone="13800138000")

    assert response.status_code == 201
    assert "qingshu_session=" in response.headers["set-cookie"]
    assert "httponly" in response.headers["set-cookie"].lower()
    payload = response.json()
    assert payload["account"] == "\u4e2d\u6587\u7528\u6237"
    assert payload["masked_phone"] == "+86138****8000"
    assert payload["auth_type"] == "account"
    assert payload["is_registered"] is True
    assert {"password_hash", "phone", "token", "token_hash", "workspace_path"}.isdisjoint(payload)

    stored = app.state.database.get_user(payload["id"])
    assert stored["password_hash"].startswith("$argon2")
    assert verify_password(stored["password_hash"], "Password-123")
    assert stored["password_hash"] != "Password-123"
    assert app.state.database.list_watchlist(payload["id"]) == []
    assert app.state.database.list_conversations(payload["id"]) == []


def test_account_and_phone_normalization_are_stable_and_login_accepts_both(client):
    created = _register(client, account="  Alice.Test  ", phone="+86 13800138000")
    assert created.status_code == 201
    assert created.json()["account"] == "alice.test"

    duplicate = _register(client, account="ALICE.TEST", phone="13900139000")
    assert duplicate.status_code == 409
    assert duplicate.json() == {"code": "account_exists", "message": "账号已存在"}

    by_account = client.post(
        "/auth/login", json={"login": "ALICE.TEST", "password": "Password-123"}
    )
    assert by_account.status_code == 200
    assert by_account.json()["account"] == "alice.test"

    by_phone = client.post(
        "/auth/login", json={"login": "86 13800138000", "password": "Password-123"}
    )
    assert by_phone.status_code == 200
    assert normalize_account("  ALICE.TEST ") == "alice.test"
    assert normalize_phone("+86 13800138000") == "+8613800138000"


def test_duplicate_phone_and_invalid_credentials_do_not_leak_which_field_failed(client):
    assert _register(client, account="auth-user-a", phone="13800138000").status_code == 201
    duplicate = _register(client, account="auth-user-b", phone="13800138000")
    assert duplicate.status_code == 409
    assert duplicate.json() == {"code": "phone_exists", "message": "手机号已存在"}

    missing = client.post(
        "/auth/login", json={"login": "missing-user", "password": "Password-123"}
    )
    wrong = client.post(
        "/auth/login", json={"login": "auth-user-a", "password": "wrong-password"}
    )
    assert missing.status_code == wrong.status_code == 401
    assert missing.json() == wrong.json() == {
        "code": "invalid_credentials",
        "message": "账号或密码错误",
    }


def test_phone_shaped_accounts_cannot_collide_with_phone_login_aliases(client):
    numeric_account = _register(
        client,
        account="13800138000",
        phone="13900139000",
    )
    assert numeric_account.status_code == 201

    phone_alias_collision = _register(
        client,
        account="phone-owner",
        phone="13800138000",
    )
    assert phone_alias_collision.status_code == 409
    assert phone_alias_collision.json()["code"] == "phone_exists"

    phone_owner = _register(
        client,
        account="real-phone-owner",
        phone="13700137000",
    )
    assert phone_owner.status_code == 201

    account_alias_collision = _register(
        client,
        account="8613700137000",
        phone="13600136000",
    )
    assert account_alias_collision.status_code == 409
    assert account_alias_collision.json()["code"] == "account_exists"

    login = client.post(
        "/auth/login",
        json={"login": "13800138000", "password": "Password-123"},
    )
    assert login.status_code == 200
    assert login.json()["id"] == numeric_account.json()["id"]


def test_preexisting_ambiguous_login_alias_fails_closed(client, app):
    owner = _register(client, account="13800138000", phone="13900139000")
    stored = app.state.database.get_user(owner.json()["id"])
    with app.state.database.connect() as connection:
        connection.execute(
            """
            INSERT INTO users(
                id, name, workspace_path, created_at, account, phone,
                password_hash, last_login_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-alias-collision",
                "legacy-alias-collision",
                "legacy-alias-collision",
                stored["created_at"],
                "other-account",
                "+8613800138000",
                stored["password_hash"],
                stored["last_login_at"],
            ),
        )

    response = client.post(
        "/auth/login",
        json={"login": "13800138000", "password": "Password-123"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"


def test_same_password_uses_distinct_argon2_hashes(client, app):
    first = _register(client, account="hash-user-a", phone="13800138000")
    second = _register(client, account="hash-user-b", phone="13900139000")
    first_hash = app.state.database.get_user(first.json()["id"])["password_hash"]
    second_hash = app.state.database.get_user(second.json()["id"])["password_hash"]
    assert first_hash != second_hash
    assert verify_password(first_hash, "Password-123")
    assert verify_password(second_hash, "Password-123")


def test_login_rotates_current_session_and_logout_revokes_it(client, app):
    registered = _register(client, account="rotate-user", phone="13800138000")
    old_token = client.cookies.get("qingshu_session")
    with app.state.database.connect() as connection:
        connection.execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", registered.json()["id"]),
        )
    login = client.post(
        "/auth/login", json={"login": "rotate-user", "password": "Password-123"}
    )
    new_token = client.cookies.get("qingshu_session")
    assert login.status_code == 200
    assert new_token and new_token != old_token
    assert app.state.database.get_user(registered.json()["id"])["last_login_at"] != "2000-01-01T00:00:00+00:00"

    old_client = TestClient(app)
    old_client.cookies.set("qingshu_session", old_token)
    assert old_client.get("/session").status_code == 401

    assert client.delete("/session").status_code == 204
    assert client.get("/session").status_code == 401


def test_session_contract_for_registered_user_and_unknown_fields(client):
    assert _register(client, account="session-user", phone="13800138000").status_code == 201
    session = client.get("/session")
    assert session.status_code == 200
    assert set(session.json()) == {
        "id", "account", "name", "masked_phone", "auth_type", "is_registered",
        "created_at", "session_expires_at",
    }
    rejected = client.post(
        "/auth/register",
        json={"account": "extra-user", "phone": "13900139000", "password": "Password-123", "role": "admin"},
    )
    assert rejected.status_code == 422
    assert client.post(
        "/auth/login",
        json={"login": "session-user", "password": "Password-123", "ignored": True},
    ).status_code == 422


def test_login_rate_limit_returns_stable_429_and_retry_after(client):
    assert _register(client, account="limited-user", phone="13800138000").status_code == 201

    for _ in range(10):
        response = client.post(
            "/auth/login",
            json={"login": "limited-user", "password": "Wrong-Password-123"},
        )
        assert response.status_code == 401

    limited = client.post(
        "/auth/login",
        json={"login": "limited-user", "password": "Wrong-Password-123"},
    )
    assert limited.status_code == 429
    assert limited.json() == {
        "code": "rate_limited",
        "message": "请求过于频繁，请稍后再试",
    }
    assert int(limited.headers["retry-after"]) >= 1


def test_legacy_anonymous_mode_controls_legacy_endpoints(settings):
    enabled = TestClient(create_app(settings))
    assert enabled.post("/users", json={"name": "legacy user"}).status_code == 201

    disabled = TestClient(create_app(replace(settings, legacy_anonymous_mode=False)))
    assert disabled.post("/users", json={"name": "legacy user"}).status_code == 403
    assert disabled.post("/sessions/claim", json={"user_id": "00000000-0000-0000-0000-000000000000"}).status_code == 403


def test_schema_6_user_is_upgraded_to_schema_7_without_losing_anonymous_user(
    isolated_postgres_schema, tmp_path
):
    from app.db import Database

    database = Database(tmp_path / "workspaces", isolated_postgres_schema)
    legacy_workspace = tmp_path / "legacy-workspace"
    legacy_workspace.mkdir()
    with database.connect() as connection:
        connection.execute(
            "CREATE TABLE users (id TEXT PRIMARY KEY, name TEXT NOT NULL, workspace_path TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO users(id, name, workspace_path, created_at) VALUES (?, ?, ?, ?)",
            ("legacy-user", "legacy anonymous", str(legacy_workspace), "2026-08-04T00:00:00+00:00"),
        )
    database.initialize()
    database.initialize()
    legacy = database.get_user("legacy-user")
    assert database.schema_status()["schema_version"] == 7
    assert legacy["account"] is None
    assert legacy["phone"] is None
    assert legacy["password_hash"] is None
    assert legacy["last_login_at"] is None
