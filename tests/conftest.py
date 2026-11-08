"""Test fixtures. Token tests use APP_TOKEN=test-token via conftest env."""
import os

import pytest

# Must be set before app.settings is first imported/cached.
os.environ.setdefault("APP_TOKEN", "test-token")
os.environ.setdefault("APP_ENV", "dev")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, headers=None)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}
