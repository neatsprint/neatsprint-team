from fastapi.testclient import TestClient

from neatsprint_team.main import app


def test_healthz() -> None:
    response = TestClient(app).get("/healthz")
    assert response.status_code == 200
    assert response.json()["service"] == "team"


def test_readyz_without_database_is_ready() -> None:
    assert TestClient(app).get("/readyz").status_code == 200


def test_ping() -> None:
    response = TestClient(app).get("/api/v1/teams/ping")
    assert response.status_code == 200
    assert response.json()["ping"] == "pong"
