"""Authentication tests."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    """Get test client."""
    return TestClient(app)


class TestAuthEndpoints:
    """Tests for authentication endpoints."""

    def test_health_check(self, client):
        """Test health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data

    def test_register_user(self, client):
        """Test user registration."""
        user_data = {
            "email": "test@example.com",
            "username": "testuser",
            "password": "secure_password_123",
        }
        
        response = client.post("/api/v1/auth/register", json=user_data)
        assert response.status_code in [201, 400]  # 400 if user already exists
        
        if response.status_code == 201:
            data = response.json()
            assert "user_id" in data
            assert data["email"] == user_data["email"]
            assert data["username"] == user_data["username"]

    def test_login_logout(self, client):
        """Test login and logout flow."""
        # First register a user
        user_data = {
            "email": "login_test@example.com",
            "username": "loginuser",
            "password": "secure_password_123",
        }
        client.post("/api/v1/auth/register", json=user_data)
        
        # Login
        login_data = {
            "email": "login_test@example.com",
            "password": "secure_password_123",
        }
        response = client.post("/api/v1/auth/login", json=login_data)
        assert response.status_code == 200
        
        data = response.json()
        assert "user_id" in data
        assert data["email"] == login_data["email"]
        
        # Logout
        response = client.post("/api/v1/auth/logout")
        assert response.status_code == 200
        assert response.json()["status"] == "success"

    def test_get_current_user(self, client):
        """Test getting current user info."""
        response = client.get("/api/v1/auth/me")
        assert response.status_code == 401  # Not authenticated