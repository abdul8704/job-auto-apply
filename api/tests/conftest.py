import os
import tempfile
from pathlib import Path

import pytest

_tmp = Path(tempfile.mkdtemp(prefix="jaa-tests-"))
_llm_cfg = _tmp / "llm.yaml"
_llm_cfg.write_text(
    """
providers:
  fake: {type: fake}
roles:
  extract: {provider: fake, model: fake-small}
  write: {provider: fake, model: fake-large}
  verify: {provider: fake, model: fake-small}
  agent: {provider: fake, model: fake-large}
"""
)
os.environ.update(
    DATABASE_URL=f"sqlite:///{_tmp / 'test.db'}",
    LOCAL_STORAGE_DIR=str(_tmp / "files"),
    LLM_CONFIG_PATH=str(_llm_cfg),
    CELERY_EAGER="true",
    JWT_SECRET="test-secret-test-secret-test-secret",
    SIGNUP_ALLOWLIST="friend@example.com",
)

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, get_engine  # noqa: E402
from app.llm import get_llm  # noqa: E402
from app.llm.providers.fake import FakeProvider  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def fake_llm() -> FakeProvider:
    provider = FakeProvider()
    client = get_llm()
    client._providers["fake"] = provider
    client.backoff_seconds = 0
    yield provider
    client._providers.pop("fake", None)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def signup_and_login(
    client: TestClient, email: str = "me@example.com", password: str = "password123"
) -> dict:
    r = client.post("/auth/signup", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    r = client.post("/auth/login", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def auth(client) -> dict:
    return signup_and_login(client)
