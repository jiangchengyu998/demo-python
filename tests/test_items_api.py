from __future__ import annotations

import os

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"] = "http://localhost:4318/v1/traces"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    future=True,
)
TestingSessionLocal = sessionmaker(
    bind=engine, autocommit=False, autoflush=False, future=True
)


def override_get_db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def setup_function() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def test_crud_flow() -> None:
    created = client.post(
        "/api/items",
        json={"name": "demo item", "description": "created from pytest"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["id"] == 1
    assert body["name"] == "demo item"
    assert body["description"] == "created from pytest"
    assert body["createdAt"]
    assert body["updatedAt"]

    listed = client.get("/api/items")
    assert listed.status_code == 200
    page = listed.json()
    assert page["totalElements"] == 1
    assert page["totalPages"] == 1
    assert page["first"] is True
    assert page["last"] is True

    fetched = client.get("/api/items/1")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "demo item"

    updated = client.put(
        "/api/items/1",
        json={"name": "updated item", "description": None},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "updated item"
    assert updated.json()["description"] is None

    deleted = client.delete("/api/items/1")
    assert deleted.status_code == 204

    missing = client.get("/api/items/1")
    assert missing.status_code == 404
    assert missing.json()["message"] == "Item not found: 1"


def test_validation_error_matches_api_error_shape() -> None:
    response = client.post("/api/items", json={"name": "   "})

    assert response.status_code == 400
    body = response.json()
    assert body["status"] == 400
    assert body["error"] == "Bad Request"
    assert body["message"] == "Request validation failed"
    assert body["details"]


def test_health_and_openapi() -> None:
    assert client.get("/actuator/health").json() == {"status": "UP"}
    assert client.get("/v3/api-docs").status_code == 200
