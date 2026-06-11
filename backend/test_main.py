import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


class TestHealthCheck:
    def test_health_endpoint(self):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"


class TestProjectsEndpoint:
    def test_get_projects_missing_token(self, monkeypatch):
        monkeypatch.setenv("DIGITALOCEAN_TOKEN", "")

        response = client.get("/api/projects")
        assert response.status_code == 500
        assert "DigitalOcean token not configured" in response.json()["error"]

    @pytest.mark.asyncio
    async def test_get_projects_invalid_token(self, monkeypatch):
        monkeypatch.setenv("DIGITALOCEAN_TOKEN", "invalid_token")

        response = client.get("/api/projects")
        assert response.status_code == 401
        assert "Invalid DigitalOcean API Token" in response.json()["error"]


class TestAnalyzeEndpoint:
    def test_analyze_missing_project_id(self):
        response = client.post("/api/analyze", json={})
        assert response.status_code == 422

    def test_analyze_missing_token(self, monkeypatch):
        monkeypatch.setenv("DIGITALOCEAN_TOKEN", "")

        response = client.post("/api/analyze", json={"project_id": "test-project"})
        assert response.status_code == 500
        assert "DigitalOcean token not configured" in response.json()["error"]


class TestErrorHandling:
    def test_not_found_endpoint(self):
        response = client.get("/nonexistent")
        assert response.status_code == 404

    def test_invalid_json(self):
        response = client.post(
            "/api/analyze",
            content="invalid json",
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 422
