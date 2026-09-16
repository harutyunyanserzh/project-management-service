import io

from app.core.config import settings
from tests.conftest import auth_headers, register_and_login


def _create_project(client, token, name="Doc Project"):
    return client.post("/projects", json={"name": name}, headers=auth_headers(token)).json()


PDF_BYTES = b"%PDF-1.4 fake pdf content"
DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_upload_document_success(client):
    token = register_and_login(client, "alice")
    project = _create_project(client, token)

    response = client.post(
        f"/project/{project['id']}/documents",
        files={"files": ("report.pdf", io.BytesIO(PDF_BYTES), "application/pdf")},
        headers=auth_headers(token),
    )
    assert response.status_code == 201
    body = response.json()
    assert len(body) == 1
    assert body[0]["file_name"] == "report.pdf"
    assert body[0]["size_bytes"] == len(PDF_BYTES)


def test_upload_rejects_disallowed_file_type(client):
    token = register_and_login(client, "alice")
    project = _create_project(client, token)

    response = client.post(
        f"/project/{project['id']}/documents",
        files={"files": ("virus.exe", io.BytesIO(b"evil"), "application/x-msdownload")},
        headers=auth_headers(token),
    )
    assert response.status_code == 400


def test_upload_rejects_project_storage_over_limit(client, monkeypatch):
    token = register_and_login(client, "alice")
    project = _create_project(client, token)
    monkeypatch.setattr(settings, "MAX_PROJECT_STORAGE_BYTES", 5)

    response = client.post(
        f"/project/{project['id']}/documents",
        files={"files": ("report.pdf", io.BytesIO(b"123456"), "application/pdf")},
        headers=auth_headers(token),
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "Project storage limit exceeded"
    documents = client.get(
        f"/project/{project['id']}/documents", headers=auth_headers(token)
    ).json()
    assert documents == []


def test_batch_upload_checks_combined_size(client, monkeypatch):
    token = register_and_login(client, "alice")
    project = _create_project(client, token)
    monkeypatch.setattr(settings, "MAX_PROJECT_STORAGE_BYTES", 8)

    response = client.post(
        f"/project/{project['id']}/documents",
        files=[
            ("files", ("one.pdf", io.BytesIO(b"12345"), "application/pdf")),
            ("files", ("two.pdf", io.BytesIO(b"67890"), "application/pdf")),
        ],
        headers=auth_headers(token),
    )

    assert response.status_code == 413
    documents = client.get(
        f"/project/{project['id']}/documents", headers=auth_headers(token)
    ).json()
    assert documents == []


def test_upload_blocked_without_project_access(client):
    alice_token = register_and_login(client, "alice")
    bob_token = register_and_login(client, "bob")
    project = _create_project(client, alice_token)

    response = client.post(
        f"/project/{project['id']}/documents",
        files={"files": ("report.pdf", io.BytesIO(PDF_BYTES), "application/pdf")},
        headers=auth_headers(bob_token),
    )
    assert response.status_code == 403


def test_list_documents(client):
    token = register_and_login(client, "alice")
    project = _create_project(client, token)
    client.post(
        f"/project/{project['id']}/documents",
        files={"files": ("report.pdf", io.BytesIO(PDF_BYTES), "application/pdf")},
        headers=auth_headers(token),
    )

    response = client.get(f"/project/{project['id']}/documents", headers=auth_headers(token))
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_download_document_returns_original_bytes(client):
    token = register_and_login(client, "alice")
    project = _create_project(client, token)
    upload = client.post(
        f"/project/{project['id']}/documents",
        files={"files": ("report.pdf", io.BytesIO(PDF_BYTES), "application/pdf")},
        headers=auth_headers(token),
    )
    document_id = upload.json()[0]["id"]

    response = client.get(f"/document/{document_id}", headers=auth_headers(token))
    assert response.status_code == 200
    assert response.content == PDF_BYTES


def test_download_blocked_without_access(client):
    alice_token = register_and_login(client, "alice")
    bob_token = register_and_login(client, "bob")
    project = _create_project(client, alice_token)
    upload = client.post(
        f"/project/{project['id']}/documents",
        files={"files": ("report.pdf", io.BytesIO(PDF_BYTES), "application/pdf")},
        headers=auth_headers(alice_token),
    )
    document_id = upload.json()[0]["id"]

    response = client.get(f"/document/{document_id}", headers=auth_headers(bob_token))
    assert response.status_code == 403


def test_participant_can_update_document(client):
    alice_token = register_and_login(client, "alice")
    bob_token = register_and_login(client, "bob")
    project = _create_project(client, alice_token)
    client.post(
        f"/project/{project['id']}/invite",
        params={"user": "bob"},
        headers=auth_headers(alice_token),
    )
    upload = client.post(
        f"/project/{project['id']}/documents",
        files={"files": ("report.pdf", io.BytesIO(PDF_BYTES), "application/pdf")},
        headers=auth_headers(alice_token),
    )
    document_id = upload.json()[0]["id"]

    new_content = b"updated pdf content"
    response = client.put(
        f"/document/{document_id}",
        files={"file": ("report_v2.pdf", io.BytesIO(new_content), "application/pdf")},
        headers=auth_headers(bob_token),
    )
    assert response.status_code == 200
    assert response.json()["file_name"] == "report_v2.pdf"
    assert response.json()["size_bytes"] == len(new_content)

    download = client.get(f"/document/{document_id}", headers=auth_headers(alice_token))
    assert download.content == new_content


def test_update_accounts_for_replaced_file_size(client, monkeypatch):
    token = register_and_login(client, "alice")
    project = _create_project(client, token)
    monkeypatch.setattr(settings, "MAX_PROJECT_STORAGE_BYTES", 10)

    upload = client.post(
        f"/project/{project['id']}/documents",
        files={"files": ("old.pdf", io.BytesIO(b"12345678"), "application/pdf")},
        headers=auth_headers(token),
    )
    assert upload.status_code == 201
    document_id = upload.json()[0]["id"]

    response = client.put(
        f"/document/{document_id}",
        files={"file": ("new.pdf", io.BytesIO(b"abcdefghi"), "application/pdf")},
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    assert response.json()["file_name"] == "new.pdf"
    assert response.json()["size_bytes"] == 9


def test_update_rejects_storage_over_limit(client, monkeypatch):
    token = register_and_login(client, "alice")
    project = _create_project(client, token)
    monkeypatch.setattr(settings, "MAX_PROJECT_STORAGE_BYTES", 10)

    upload = client.post(
        f"/project/{project['id']}/documents",
        files={"files": ("old.pdf", io.BytesIO(b"12345"), "application/pdf")},
        headers=auth_headers(token),
    )
    document_id = upload.json()[0]["id"]

    response = client.put(
        f"/document/{document_id}",
        files={"file": ("large.pdf", io.BytesIO(b"12345678901"), "application/pdf")},
        headers=auth_headers(token),
    )

    assert response.status_code == 413
    original = client.get(f"/document/{document_id}", headers=auth_headers(token))
    assert original.status_code == 200
    assert original.content == b"12345"


def test_document_delete_removes_it(client):
    token = register_and_login(client, "alice")
    project = _create_project(client, token)
    upload = client.post(
        f"/project/{project['id']}/documents",
        files={"files": ("report.pdf", io.BytesIO(PDF_BYTES), "application/pdf")},
        headers=auth_headers(token),
    )
    document_id = upload.json()[0]["id"]

    delete = client.delete(f"/document/{document_id}", headers=auth_headers(token))
    assert delete.status_code == 204

    follow_up = client.get(f"/document/{document_id}", headers=auth_headers(token))
    assert follow_up.status_code == 404


def test_deleting_project_cascades_to_documents(client):
    token = register_and_login(client, "alice")
    project = _create_project(client, token)
    upload = client.post(
        f"/project/{project['id']}/documents",
        files={"files": ("report.pdf", io.BytesIO(PDF_BYTES), "application/pdf")},
        headers=auth_headers(token),
    )
    document_id = upload.json()[0]["id"]

    client.delete(f"/project/{project['id']}", headers=auth_headers(token))

    follow_up = client.get(f"/document/{document_id}", headers=auth_headers(token))
    assert follow_up.status_code == 404


def test_project_list_embeds_documents(client):
    token = register_and_login(client, "alice")
    project = _create_project(client, token)
    client.post(
        f"/project/{project['id']}/documents",
        files={"files": ("report.pdf", io.BytesIO(PDF_BYTES), "application/pdf")},
        headers=auth_headers(token),
    )

    response = client.get("/projects", headers=auth_headers(token))
    assert len(response.json()[0]["documents"]) == 1
