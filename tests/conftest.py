import pytest
from fastapi.testclient import TestClient
from moto import mock_aws
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.session as db_session_module
from app.core.config import settings
from app.db.session import Base
from app.main import app


@pytest.fixture()
def db_engine():
    """A fresh in-memory SQLite DB per test, wired into the app's session module
    so every route (which depends on get_db) uses this test database instead
    of the real Postgres one. StaticPool is required here: without it, each
    new connection to a sqlite ':memory:' URL gets its own separate, empty
    database, so a request in one connection wouldn't see data written by
    another."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    db_session_module.engine = engine
    db_session_module.SessionLocal = TestingSessionLocal

    # import models so their tables are registered on Base.metadata
    from app.models import Document, Project, ProjectAccess, ShareToken, User  # noqa: F401

    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def s3_bucket(db_engine):
    """A mocked S3 bucket matching the app's configured bucket name, active
    for the duration of one test."""
    with mock_aws():
        import boto3

        boto3.client("s3", region_name=settings.AWS_REGION).create_bucket(
            Bucket=settings.S3_BUCKET_NAME
        )
        yield


@pytest.fixture()
def client(s3_bucket):
    return TestClient(app)


def register_and_login(client: TestClient, login: str, password: str = "password123") -> str:
    """Test helper: register a user and return their bearer access_token."""
    client.post("/auth", json={"login": login, "password": password, "repeat_password": password})
    response = client.post("/login", json={"login": login, "password": password})
    return response.json()["access_token"]


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
