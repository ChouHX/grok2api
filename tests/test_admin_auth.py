from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import admin as admin_api
from app.core import auth as auth_module


def _build_client(monkeypatch, *, admin_username="admin", app_key="admin-pass", api_key="", legacy_keys=None):
    legacy_keys = set(legacy_keys or set())

    def _admin_get_config(key: str, default=None):
        values = {
            "app.admin_username": admin_username,
            "app.app_key": app_key,
            "app.api_key": api_key,
        }
        return values.get(key, default)

    def _auth_get_config(key: str, default=None):
        values = {
            "app.app_key": app_key,
            "app.api_key": api_key,
        }
        return values.get(key, default)

    async def _fake_legacy_keys():
        return legacy_keys

    monkeypatch.setattr(admin_api, "get_config", _admin_get_config)
    monkeypatch.setattr(auth_module, "get_config", _auth_get_config)
    monkeypatch.setattr(auth_module, "_load_legacy_api_keys", _fake_legacy_keys)

    app = FastAPI()
    app.include_router(admin_api.router)
    return TestClient(app)


def test_admin_login_returns_app_auth_key(monkeypatch):
    client = _build_client(
        monkeypatch,
        admin_username="root",
        app_key="docker-admin-pass",
        api_key="public-api-key",
    )

    res = client.post(
        "/api/v1/admin/login",
        json={"username": "root", "password": "docker-admin-pass"},
    )

    assert res.status_code == 200
    assert res.json() == {
        "status": "success",
        "auth_key": "docker-admin-pass",
        "api_key": "public-api-key",
    }


def test_admin_routes_use_app_key_even_when_legacy_keys_exist(monkeypatch):
    client = _build_client(
        monkeypatch,
        app_key="docker-admin-pass",
        api_key="",
        legacy_keys={"legacy-public-key"},
    )

    login = client.post(
        "/api/v1/admin/login",
        json={"username": "admin", "password": "docker-admin-pass"},
    )

    assert login.status_code == 200
    assert login.json()["auth_key"] == "docker-admin-pass"

    admin_res = client.get(
        "/api/v1/admin/config",
        headers={"Authorization": "Bearer docker-admin-pass"},
    )
    assert admin_res.status_code == 200

    legacy_res = client.get(
        "/api/v1/admin/config",
        headers={"Authorization": "Bearer legacy-public-key"},
    )
    assert legacy_res.status_code == 401
