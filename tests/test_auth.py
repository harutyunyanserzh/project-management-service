from tests.conftest import auth_headers, register_and_login


def test_register_creates_user(client):
    response = client.post(
        "/auth",
        json={"login": "alice", "password": "password123", "repeat_password": "password123"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["login"] == "alice"
    assert "id" in body
    assert "password" not in body
    assert "hashed_password" not in body


def test_register_duplicate_login_conflicts(client):
    payload = {"login": "alice", "password": "password123", "repeat_password": "password123"}
    client.post("/auth", json=payload)
    response = client.post("/auth", json=payload)
    assert response.status_code == 409


def test_register_password_mismatch_rejected(client):
    response = client.post(
        "/auth",
        json={"login": "bob", "password": "password123", "repeat_password": "different123"},
    )
    assert response.status_code == 422


def test_register_short_password_rejected(client):
    response = client.post(
        "/auth", json={"login": "bob", "password": "short", "repeat_password": "short"}
    )
    assert response.status_code == 422


def test_login_success_returns_token(client):
    client.post(
        "/auth",
        json={"login": "alice", "password": "password123", "repeat_password": "password123"},
    )
    response = client.post("/login", json={"login": "alice", "password": "password123"})
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in_minutes"] == 60
    assert len(body["access_token"]) > 20


def test_login_wrong_password_rejected(client):
    client.post(
        "/auth",
        json={"login": "alice", "password": "password123", "repeat_password": "password123"},
    )
    response = client.post("/login", json={"login": "alice", "password": "wrongpassword"})
    assert response.status_code == 401


def test_login_nonexistent_user_rejected(client):
    response = client.post("/login", json={"login": "ghost", "password": "password123"})
    assert response.status_code == 401


def test_protected_route_requires_token(client):
    response = client.get("/me")
    assert response.status_code == 401


def test_protected_route_rejects_garbage_token(client):
    response = client.get("/me", headers=auth_headers("not-a-real-token"))
    assert response.status_code == 401


def test_protected_route_accepts_valid_token(client):
    token = register_and_login(client, "alice")
    response = client.get("/me", headers=auth_headers(token))
    assert response.status_code == 200
    assert response.json()["login"] == "alice"
