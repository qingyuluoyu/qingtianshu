from __future__ import annotations

import logging


def _register(client, *, account: str, phone: str, password: str = "Password-123"):
    return client.post(
        "/auth/register",
        json={"account": account, "phone": phone, "password": password},
    )


def test_auth_validation_errors_redact_request_secrets_and_keep_safe_shape(
    client, caplog
):
    secrets = (
        "long-password-secret-" + "x" * 128,
        "xy!9Qz",
        "!@#$%^&*()_+-=secret" + "?" * 128,
        "extra-password-like-secret",
    )
    requests = (
        {
            "account": "redact-long",
            "phone": "13800138000",
            "password": secrets[0],
        },
        {
            "account": "redact-short",
            "phone": "13900139000",
            "password": secrets[1],
        },
        {
            "account": "redact-special",
            "phone": "13700137000",
            "password": secrets[2],
        },
        {
            "account": "redact-extra",
            "phone": "13600136000",
            "password": "Password-123",
            "password_confirmation": secrets[3],
            "api_key": "api-key-secret",
        },
    )

    with caplog.at_level(logging.DEBUG):
        responses = [
            client.post("/auth/register", json=payload) for payload in requests
        ]

    for response in responses:
        assert response.status_code == 422
        payload = response.json()
        assert payload["code"] == "validation_error"
        assert payload["message"] == "请求参数校验失败"
        assert payload["detail"]
        assert {"loc", "msg", "type"}.issubset(payload["detail"][0])

    response_text = "\n".join(response.text for response in responses)
    log_text = caplog.text
    for secret in (*secrets, "api-key-secret"):
        assert secret not in response_text
        assert secret not in log_text


def test_auth_openapi_declares_closed_request_and_response_contracts(client):
    schema = client.get("/openapi.json").json()
    components = schema["components"]["schemas"]

    for name in ("AuthRegisterRequest", "AuthLoginRequest", "AuthSessionResponse"):
        assert components[name]["additionalProperties"] is False

    register = schema["paths"]["/auth/register"]["post"]
    login = schema["paths"]["/auth/login"]["post"]
    session = schema["paths"]["/session"]["get"]
    assert register["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/AuthRegisterRequest"
    )
    assert login["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/AuthLoginRequest"
    )
    for operation, status in ((register, "201"), (login, "200"), (session, "200")):
        assert operation["responses"][status]["content"]["application/json"]["schema"][
            "$ref"
        ].endswith("/AuthSessionResponse")

    for operation, status, schema_name in (
        (register, "409", "AuthErrorResponse"),
        (register, "422", "AuthValidationErrorResponse"),
        (login, "401", "AuthErrorResponse"),
        (login, "422", "AuthValidationErrorResponse"),
        (session, "401", "AuthErrorResponse"),
    ):
        assert operation["responses"][status]["content"]["application/json"][
            "schema"
        ]["$ref"].endswith(f"/{schema_name}")

    response_fields = set(components["AuthSessionResponse"]["properties"])
    assert response_fields == {
        "id",
        "account",
        "name",
        "masked_phone",
        "auth_type",
        "is_registered",
        "created_at",
        "session_expires_at",
    }
    assert {"password", "password_hash", "phone", "token", "workspace_path"}.isdisjoint(
        response_fields
    )


def test_auth_error_contract_has_stable_code_and_message(client):
    assert _register(client, account="duplicate-user", phone="13800138000").status_code == 201
    duplicate = _register(client, account="duplicate-user", phone="13900139000")
    invalid = client.post(
        "/auth/login", json={"login": "duplicate-user", "password": "not-it"}
    )
    expired = client.get("/session", cookies={"qingshu_session": "not-a-session"})

    for response, code in (
        (duplicate, "account_exists"),
        (invalid, "invalid_credentials"),
        (expired, "session_expired"),
    ):
        assert response.status_code in {401, 409}
        assert response.json()["code"] == code
        assert isinstance(response.json()["message"], str)
        assert response.json()["message"]

    malformed = _register(client, account="bad account!", phone="13600136000")
    assert malformed.status_code == 422
    assert malformed.json()["code"] == "validation_error"
    assert malformed.json()["message"] == "请求参数校验失败"


def test_session_status_is_anonymous_safe_and_does_not_change_session_contract(client):
    anonymous = client.get("/session/status")
    assert anonymous.status_code == 200
    assert anonymous.json() == {"authenticated": False}
    # Existing callers keep the original explicit-session contract.
    assert client.get("/session").status_code == 401

    assert _register(client, account="status-user", phone="13500135000").status_code == 201
    authenticated = client.get("/session/status")
    assert authenticated.status_code == 200
    assert authenticated.json()["authenticated"] is True
    assert set(authenticated.json()["session"]) == {
        "id", "account", "name", "masked_phone", "auth_type", "is_registered",
        "created_at", "session_expires_at",
    }


def test_auth_validation_handler_does_not_change_legacy_422_shape(client):
    response = client.post("/users", json={"name": ""})
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert response.json()["detail"][0]["loc"] == ["body", "name"]
