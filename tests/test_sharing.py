import re
from datetime import datetime, timedelta, timezone

from app.models.share_token import ShareToken
from tests.conftest import auth_headers, register_and_login


def _create_project(client, token, name="Shared Project"):
    return client.post("/projects", json={"name": name}, headers=auth_headers(token)).json()


def _extract_token_from_logs(caplog) -> str:
    """The email service logs the join link when SMTP isn't configured, which
    is exactly how a developer would retrieve it locally."""
    match = re.search(r"/join\?token=([\w\-]+)", caplog.text)
    assert match, f"no join link found in logs: {caplog.text}"
    return match.group(1)


def test_share_sends_invitation(client, caplog):
    token = register_and_login(client, "alice")
    project = _create_project(client, token)

    with caplog.at_level("WARNING"):
        response = client.get(
            f"/project/{project['id']}/share",
            params={"with": "bob@example.com"},
            headers=auth_headers(token),
        )

    assert response.status_code == 200
    assert "bob@example.com" in response.json()["detail"]
    assert "/join?token=" in caplog.text


def test_share_requires_owner(client):
    alice_token = register_and_login(client, "alice")
    bob_token = register_and_login(client, "bob")
    project = _create_project(client, alice_token)
    client.post(
        f"/project/{project['id']}/invite",
        params={"user": "bob"},
        headers=auth_headers(alice_token),
    )

    response = client.get(
        f"/project/{project['id']}/share",
        params={"with": "carol@example.com"},
        headers=auth_headers(bob_token),
    )
    assert response.status_code == 403


def test_share_rejects_invalid_email(client):
    token = register_and_login(client, "alice")
    project = _create_project(client, token)

    response = client.get(
        f"/project/{project['id']}/share",
        params={"with": "not-an-email"},
        headers=auth_headers(token),
    )
    assert response.status_code == 422


def test_join_grants_participant_access(client, caplog):
    alice_token = register_and_login(client, "alice")
    bob_token = register_and_login(client, "bob")
    project = _create_project(client, alice_token)

    with caplog.at_level("WARNING"):
        client.get(
            f"/project/{project['id']}/share",
            params={"with": "bob@example.com"},
            headers=auth_headers(alice_token),
        )
    raw_token = _extract_token_from_logs(caplog)

    assert client.get("/projects", headers=auth_headers(bob_token)).json() == []

    response = client.get("/join", params={"token": raw_token}, headers=auth_headers(bob_token))
    assert response.status_code == 200

    bob_projects = client.get("/projects", headers=auth_headers(bob_token)).json()
    assert len(bob_projects) == 1
    assert bob_projects[0]["my_role"] == "participant"


def test_join_requires_authentication(client, caplog):
    alice_token = register_and_login(client, "alice")
    project = _create_project(client, alice_token)
    with caplog.at_level("WARNING"):
        client.get(
            f"/project/{project['id']}/share",
            params={"with": "bob@example.com"},
            headers=auth_headers(alice_token),
        )
    raw_token = _extract_token_from_logs(caplog)

    response = client.get("/join", params={"token": raw_token})
    assert response.status_code == 401


def test_join_rejects_invalid_token(client):
    token = register_and_login(client, "alice")
    response = client.get(
        "/join", params={"token": "totally-made-up-token"}, headers=auth_headers(token)
    )
    assert response.status_code == 404


def test_join_token_is_single_use(client, caplog):
    alice_token = register_and_login(client, "alice")
    bob_token = register_and_login(client, "bob")
    carol_token = register_and_login(client, "carol")
    project = _create_project(client, alice_token)

    with caplog.at_level("WARNING"):
        client.get(
            f"/project/{project['id']}/share",
            params={"with": "bob@example.com"},
            headers=auth_headers(alice_token),
        )
    raw_token = _extract_token_from_logs(caplog)

    first = client.get("/join", params={"token": raw_token}, headers=auth_headers(bob_token))
    assert first.status_code == 200

    second = client.get("/join", params={"token": raw_token}, headers=auth_headers(carol_token))
    assert second.status_code == 410


def test_join_rejects_expired_token(client, caplog, db_engine):
    from sqlalchemy.orm import Session

    alice_token = register_and_login(client, "alice")
    bob_token = register_and_login(client, "bob")
    project = _create_project(client, alice_token)

    with caplog.at_level("WARNING"):
        client.get(
            f"/project/{project['id']}/share",
            params={"with": "bob@example.com"},
            headers=auth_headers(alice_token),
        )
    raw_token = _extract_token_from_logs(caplog)

    with Session(db_engine) as session:
        share_token = session.query(ShareToken).first()
        share_token.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        session.commit()

    response = client.get("/join", params={"token": raw_token}, headers=auth_headers(bob_token))
    assert response.status_code == 410


def test_raw_token_is_not_stored_in_database(client, caplog, db_engine):
    """The database should only ever hold the hash, never the raw token."""
    from sqlalchemy.orm import Session

    alice_token = register_and_login(client, "alice")
    project = _create_project(client, alice_token)

    with caplog.at_level("WARNING"):
        client.get(
            f"/project/{project['id']}/share",
            params={"with": "bob@example.com"},
            headers=auth_headers(alice_token),
        )
    raw_token = _extract_token_from_logs(caplog)

    with Session(db_engine) as session:
        stored = session.query(ShareToken).first()
        assert stored.token_hash != raw_token
        assert len(stored.token_hash) == 64
