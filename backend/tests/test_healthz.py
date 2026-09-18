"""
Tests para endpoints de health check (SPEC-011 RF-02).
Placeholder para tests reales en SPECs posteriores.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Fixture para el cliente de pruebas."""
    from app.main import app

    return TestClient(app)


def test_healthz_endpoint(client):
    """
    Test: GET /healthz debe retornar 200 con status 'healthy'.
    """
    response = client.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "timestamp" in data
    assert "environment" in data


def test_readyz_endpoint(client):
    """
    Test: GET /readyz debe retornar 200 con ready=true.
    """
    response = client.get("/readyz")
    assert response.status_code == 200
    data = response.json()
    assert data["ready"] is True


def test_root_endpoint(client):
    """
    Test: GET / debe retornar información sobre la API.
    """
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "docs" in data
    assert "openapi" in data


def test_docs_endpoint(client):
    """
    Test: GET /docs debe estar disponible.
    """
    response = client.get("/docs")
    assert response.status_code == 200
    assert "swagger-ui" in response.text or "openapi" in response.text.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
