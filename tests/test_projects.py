from tests.conftest import auth_headers, register_and_login


def _create_project(client, token, name="Test Project", description="a project"):
    response = client.post(
        "/projects",
        json={"name": name, "description": description},
        headers=auth_headers(token),
    )
    return response


def test_create_project_makes_creator_owner(client):
    token = register_and_login(client, "alice")
    response = _create_project(client, token)
    assert response.status_code == 201
    body = response.json()
    assert body["my_role"] == "owner"
    assert body["name"] == "Test Project"
    assert body["documents"] == []


def test_create_project_rejects_blank_name(client):
    token = register_and_login(client, "alice")
    response = client.post("/projects", json={"name": "   "}, headers=auth_headers(token))
    assert response.status_code == 422


def test_list_projects_only_shows_accessible(client):
    alice_token = register_and_login(client, "alice")
    bob_token = register_and_login(client, "bob")
    _create_project(client, alice_token)

    alice_list = client.get("/projects", headers=auth_headers(alice_token))
    bob_list = client.get("/projects", headers=auth_headers(bob_token))

    assert len(alice_list.json()) == 1
    assert bob_list.json() == []


def test_get_info_blocked_without_access(client):
    alice_token = register_and_login(client, "alice")
    bob_token = register_and_login(client, "bob")
    project_id = _create_project(client, alice_token).json()["id"]

    response = client.get(f"/project/{project_id}/info", headers=auth_headers(bob_token))
    assert response.status_code == 403


def test_get_info_nonexistent_project_404(client):
    token = register_and_login(client, "alice")
    response = client.get(
        "/project/00000000-0000-0000-0000-000000000000/info", headers=auth_headers(token)
    )
    assert response.status_code == 404


def test_invite_grants_participant_access(client):
    alice_token = register_and_login(client, "alice")
    bob_token = register_and_login(client, "bob")
    project_id = _create_project(client, alice_token).json()["id"]

    invite_response = client.post(
        f"/project/{project_id}/invite",
        params={"user": "bob"},
        headers=auth_headers(alice_token),
    )
    assert invite_response.status_code == 200

    bob_info = client.get(f"/project/{project_id}/info", headers=auth_headers(bob_token))
    assert bob_info.status_code == 200
    assert bob_info.json()["my_role"] == "participant"


def test_invite_by_non_owner_forbidden(client):
    alice_token = register_and_login(client, "alice")
    bob_token = register_and_login(client, "bob")
    register_and_login(client, "carol")
    project_id = _create_project(client, alice_token).json()["id"]
    client.post(
        f"/project/{project_id}/invite", params={"user": "bob"}, headers=auth_headers(alice_token)
    )

    response = client.post(
        f"/project/{project_id}/invite",
        params={"user": "carol"},
        headers=auth_headers(bob_token),
    )
    assert response.status_code == 403


def test_invite_nonexistent_user_404(client):
    token = register_and_login(client, "alice")
    project_id = _create_project(client, token).json()["id"]
    response = client.post(
        f"/project/{project_id}/invite", params={"user": "ghost"}, headers=auth_headers(token)
    )
    assert response.status_code == 404


def test_invite_duplicate_conflicts(client):
    alice_token = register_and_login(client, "alice")
    register_and_login(client, "bob")
    project_id = _create_project(client, alice_token).json()["id"]
    client.post(
        f"/project/{project_id}/invite", params={"user": "bob"}, headers=auth_headers(alice_token)
    )
    response = client.post(
        f"/project/{project_id}/invite", params={"user": "bob"}, headers=auth_headers(alice_token)
    )
    assert response.status_code == 409


def test_participant_can_update_info(client):
    alice_token = register_and_login(client, "alice")
    bob_token = register_and_login(client, "bob")
    project_id = _create_project(client, alice_token).json()["id"]
    client.post(
        f"/project/{project_id}/invite", params={"user": "bob"}, headers=auth_headers(alice_token)
    )

    response = client.put(
        f"/project/{project_id}/info",
        json={"description": "updated by bob"},
        headers=auth_headers(bob_token),
    )
    assert response.status_code == 200
    assert response.json()["description"] == "updated by bob"


def test_participant_cannot_delete(client):
    alice_token = register_and_login(client, "alice")
    bob_token = register_and_login(client, "bob")
    project_id = _create_project(client, alice_token).json()["id"]
    client.post(
        f"/project/{project_id}/invite", params={"user": "bob"}, headers=auth_headers(alice_token)
    )

    response = client.delete(f"/project/{project_id}", headers=auth_headers(bob_token))
    assert response.status_code == 403


def test_owner_can_delete(client):
    token = register_and_login(client, "alice")
    project_id = _create_project(client, token).json()["id"]

    response = client.delete(f"/project/{project_id}", headers=auth_headers(token))
    assert response.status_code == 204

    follow_up = client.get(f"/project/{project_id}/info", headers=auth_headers(token))
    assert follow_up.status_code == 404
