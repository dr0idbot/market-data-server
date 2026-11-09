from __future__ import annotations

import base64
import hashlib
import os

import pytest
from fastapi.testclient import TestClient

from app.core.auth import ENC_PREFIX, decrypt_app_token


def encrypt_token(app_token: str, shared_key: str) -> str:
    """Reference implementation of the documented ENC-BEARER v1 client side."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(12)
    aesgcm = AESGCM(hashlib.sha256(shared_key.encode("utf-8")).digest())
    blob = nonce + aesgcm.encrypt(nonce, app_token.encode("utf-8"), None)
    return ENC_PREFIX + base64.b64encode(blob).decode("ascii")


@pytest.fixture()
def with_enc_key():
    """Enable APP_TOKEN_ENC_KEY on the cached settings for the duration."""
    from app.core.config import get_settings

    settings = get_settings()
    original = settings.app_token_enc_key
    settings.app_token_enc_key = "enc-secret-alpha"
    yield settings
    settings.app_token_enc_key = original


def test_encrypted_bearer_accepted(
    client: TestClient, auth_headers: dict[str, str], with_enc_key
) -> None:
    header = {"Authorization": f"Bearer {encrypt_token('test-token', 'enc-secret-alpha')}"}
    resp = client.get("/v1/health", headers=header)
    assert resp.status_code == 200
    assert resp.json()["error"] is None


def test_plain_bearer_still_accepted(
    client: TestClient, auth_headers: dict[str, str], with_enc_key
) -> None:
    assert client.get("/v1/health", headers=auth_headers).status_code == 200


def test_encrypted_bearer_wrong_key_rejected(
    client: TestClient, with_enc_key
) -> None:
    header = {"Authorization": f"Bearer {encrypt_token('test-token', 'other-key')}"}
    resp = client.get("/v1/health", headers=header)
    assert resp.status_code == 401


def test_encrypted_bearer_no_key_configured_rejected(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    enc = encrypt_token("test-token", "enc-secret-alpha")
    resp = client.get("/v1/health", headers={"Authorization": f"Bearer {enc}"})
    assert resp.status_code == 401
    assert client.get("/v1/health", headers=auth_headers).status_code == 200


def test_encrypted_bearer_decrypts_to_wrong_token_rejected(
    client: TestClient, with_enc_key
) -> None:
    header = {"Authorization": f"Bearer {encrypt_token('nope-token', 'enc-secret-alpha')}"}
    assert client.get("/v1/health", headers=header).status_code == 401


def test_encrypted_bearer_tampered_payload_rejected(
    client: TestClient, with_enc_key
) -> None:
    enc = encrypt_token("test-token", "enc-secret-alpha")
    tampered = enc[:-4] + ("AAAA" if enc[-4:] != "AAAA" else "BBBB")
    resp = client.get("/v1/health", headers={"Authorization": f"Bearer {tampered}"})
    assert resp.status_code == 401


def test_encrypted_bearer_malformed_payloads_rejected(
    client: TestClient, with_enc_key
) -> None:
    for bad in ["enc:", "enc:ZZZZ", "enc:AAAA", "enc:only.token.score"]:
        resp = client.get("/v1/health", headers={"Authorization": f"Bearer {bad}"})
        assert resp.status_code == 401, bad


def test_decrypt_app_token_unit() -> None:
    enc = encrypt_token("secret-token", "shared")
    assert decrypt_app_token(enc, "shared", "secret-token") is True
    assert decrypt_app_token(enc, "shared", "other") is False
    assert decrypt_app_token(enc, None, "secret-token") is False
    assert decrypt_app_token("enc:!!!not-b64!!!", "shared", "secret-token") is False
    assert decrypt_app_token("enc:AAAA", "shared", "secret-token") is False
    assert decrypt_app_token("plain", "shared", "secret-token") is False
