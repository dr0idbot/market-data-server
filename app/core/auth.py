import base64
import hashlib
import secrets
from typing import Final

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings

bearer_scheme = HTTPBearer(auto_error=False)

ENC_PREFIX: Final[str] = "enc:"
_NONCE_LEN: Final[int] = 12  # GCM standard nonce; Java side must do the same


def _derive_key(shared: str) -> bytes:
    """AES-256 key = SHA-256(UTF-8 of the shared secret). Same on Java client."""
    return hashlib.sha256(shared.encode("utf-8")).digest()


def decrypt_app_token(bearer_value: str, enc_key: str | None, app_token: str) -> bool:
    """Validate an `enc:`-prefixed bearer value; True if it decrypts to app_token.

    Scheme (ENC-BEARER v1): bearer_value = "enc:" + base64(nonce || ct || tag)
    where (nonce, ct||tag) come from AES-256-GCM over the UTF-8 APP_TOKEN.
    Never logs the token, key or ciphertext; all failures collapse to False.
    """
    if enc_key is None:
        return False
    blob_src = bearer_value[len(ENC_PREFIX):]
    try:
        blob = base64.b64decode(blob_src, validate=True)
    except ValueError:
        return False
    if len(blob) <= _NONCE_LEN:
        return False
    nonce, ct = blob[:_NONCE_LEN], blob[_NONCE_LEN:]
    try:
        plain = AESGCM(_derive_key(enc_key)).decrypt(nonce, ct, None)
    except Exception:
        return False
    return secrets.compare_digest(plain, app_token.encode("utf-8"))


def require_app_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> None:
    """FastAPI dependency enforcing the shared APP_TOKEN.

    Plain bearer:  Authorization: Bearer <APP_TOKEN>
    Encrypted (optional, in addition): the bearer value may be `enc:<payload>`
    produced with ENC-BEARER v1 (AES-256-GCM, key SHA-256(APP_TOKEN_ENC_KEY)).
    Encryption is only accepted when APP_TOKEN_ENC_KEY is configured; the
    decrypted token is compared constant-time against APP_TOKEN.
    """
    value = credentials.credentials if credentials is not None else None
    if value is None:
        valid = False
    elif value.startswith(ENC_PREFIX):
        valid = decrypt_app_token(value, settings.app_token_enc_key, settings.app_token)
    else:
        valid = secrets.compare_digest(value, settings.app_token)
    if not valid:
        request.state.auth_failure = True
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "message": "Forbidden"},
            headers={"WWW-Authenticate": "Bearer"},
        )
