"""End-to-end tests for the AI assistant API, using fake models (no network, no cost)."""

import io

from app.ai.prompts import NOT_FOUND_ANSWER
from app.api.assistant import chat_model_or_503
from app.main import app
from tests.ai_helpers import DOCX_CONTENT_TYPE, FakeChatModel, make_docx, make_pdf, tool_call
from tests.conftest import auth_headers, register_and_login

CONTRACT = [
    "Vendor contract between Acme Studio and the client.",
    "The launch deadline is March 3, 2027. Late delivery costs 2 percent per week.",
    "Payment terms: the client pays 50 percent upfront and 50 percent on delivery.",
]
BUDGET_TABLE = [["Item", "Cost"], ["Design", "10,000 USD"], ["Development", "40,000 USD"]]


def _project(client, token, name="AI Project"):
    return client.post("/projects", json={"name": name}, headers=auth_headers(token)).json()


def _upload(client, token, project_id, name, data, content_type):
    response = client.post(
        f"/project/{project_id}/documents",
        files={"files": (name, io.BytesIO(data), content_type)},
        headers=auth_headers(token),
    )
    assert response.status_code == 201
    return response.json()[0]


def _setup(client):
    """Alice owns a project with a contract (DOCX) and a two-page brief (PDF)."""
    token = register_and_login(client, "alice")
    project = _project(client, token)
    _upload(
        client,
        token,
        project["id"],
        "contract.docx",
        make_docx(CONTRACT, BUDGET_TABLE),
        DOCX_CONTENT_TYPE,
    )
    _upload(
        client,
        token,
        project["id"],
        "brief.pdf",
        make_pdf(
            ["Project brief: a mobile app for booking yoga classes.", "Kickoff is in Yerevan."]
        ),
        "application/pdf",
    )
    return token, project


def _ask(client, token, project_id, question, mode="rag"):
    return client.post(
        f"/project/{project_id}/assistant/ask",
        json={"question": question, "mode": mode},
        headers=auth_headers(token),
    )


def _use_model(model: FakeChatModel) -> FakeChatModel:
    app.dependency_overrides[chat_model_or_503] = lambda: model
    return model


# --- indexing ------------------------------------------------------------------------


def test_upload_indexes_documents(client):
    token, project = _setup(client)

    status = client.get(
        f"/project/{project['id']}/assistant/status", headers=auth_headers(token)
    ).json()

    assert status["documents"] == 2
    assert status["indexed_documents"] == 2
    assert status["chunks"] >= 3
    assert status["embedding_model"].startswith("hash:")
    assert status["llm_provider"] == "none"


def test_unreadable_file_does_not_break_upload(client):
    token = register_and_login(client, "alice")
    project = _project(client, token)

    _upload(client, token, project["id"], "broken.pdf", b"%PDF-1.4 not really", "application/pdf")

    status = client.get(
        f"/project/{project['id']}/assistant/status", headers=auth_headers(token)
    ).json()
    assert status["documents"] == 1
    assert status["indexed_documents"] == 0


def test_deleting_document_removes_its_chunks(client):
    token, project = _setup(client)
    documents = client.get(
        f"/project/{project['id']}/documents", headers=auth_headers(token)
    ).json()

    for document in documents:
        client.delete(f"/document/{document['id']}", headers=auth_headers(token))

    status = client.get(
        f"/project/{project['id']}/assistant/status", headers=auth_headers(token)
    ).json()
    assert status["chunks"] == 0


def test_reindex_is_owner_only(client):
    token, project = _setup(client)
    register_and_login(client, "bob")
    client.post(f"/project/{project['id']}/invite?user=bob", headers=auth_headers(token))
    bob = register_and_login(client, "bob")

    assert (
        client.post(
            f"/project/{project['id']}/assistant/reindex", headers=auth_headers(bob)
        ).status_code
        == 403
    )
    response = client.post(
        f"/project/{project['id']}/assistant/reindex", headers=auth_headers(token)
    )
    assert response.status_code == 200
    assert response.json()["documents"] == 2
    assert response.json()["failed"] == []


# --- RAG -------------------------------------------------------------------------------


def test_without_llm_returns_relevant_passages(client):
    token, project = _setup(client)

    body = _ask(client, token, project["id"], "When is the launch deadline?").json()

    assert body["used_fallback"] is True
    assert body["sources"][0]["file_name"] == "contract.docx"
    assert "March 3, 2027" in body["answer"]


def test_pdf_sources_keep_page_numbers(client):
    token, project = _setup(client)

    body = _ask(client, token, project["id"], "Where is the kickoff?").json()

    top = body["sources"][0]
    assert top["file_name"] == "brief.pdf"
    assert top["page_number"] == 2
    assert top["label"] == "brief.pdf, page 2"


def test_rag_answer_uses_model_and_retrieved_context(client):
    token, project = _setup(client)
    model = _use_model(FakeChatModel(["The launch deadline is March 3, 2027 [1]."]))

    body = _ask(client, token, project["id"], "When is the launch deadline?").json()

    assert body["answer"] == "The launch deadline is March 3, 2027 [1]."
    assert body["used_fallback"] is False
    assert body["mode"] == "rag"
    prompt = model.calls[0][-1].content
    assert "<documents>" in prompt and "March 3, 2027" in prompt
    assert "[1] (contract.docx)" in prompt
    system = model.calls[0][0].content
    assert "ONLY the document excerpts" in system


def test_no_relevant_documents_skips_the_model(client):
    token, project = _setup(client)
    model = _use_model(FakeChatModel(["should not be used"]))

    body = _ask(client, token, project["id"], "volcano eruption forecast").json()

    assert body["answer"] == NOT_FOUND_ANSWER
    assert body["sources"] == []
    assert model.calls == []


def test_model_failure_falls_back_to_passages(client):
    token, project = _setup(client)
    _use_model(FakeChatModel(error=ConnectionError("ollama is not running")))

    body = _ask(client, token, project["id"], "What are the payment terms?").json()

    assert body["used_fallback"] is True
    assert "ConnectionError" in body["warning"]
    assert "50 percent upfront" in body["answer"]


def test_misconfigured_provider_returns_503(client, monkeypatch):
    from app.core.config import settings

    token, project = _setup(client)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None)

    response = _ask(client, token, project["id"], "deadline?")

    assert response.status_code == 503
    assert "ANTHROPIC_API_KEY" in response.json()["detail"]


# --- security --------------------------------------------------------------------------


def test_non_member_cannot_ask(client):
    _, project = _setup(client)
    bob = register_and_login(client, "bob")

    assert _ask(client, bob, project["id"], "When is the deadline?").status_code == 403


def test_search_never_crosses_projects(client):
    token, project = _setup(client)
    other = _project(client, token, name="Empty project")

    body = _ask(client, token, other["id"], "When is the launch deadline?").json()

    assert body["answer"] == NOT_FOUND_ANSWER
    assert body["sources"] == []
    assert project["id"] != other["id"]


# --- conversation memory -----------------------------------------------------------------


def test_history_is_saved_and_sent_with_follow_ups(client):
    token, project = _setup(client)
    model = _use_model(
        FakeChatModel(
            ["The deadline is March 3, 2027 [1].", "Late delivery costs 2% per week [1]."]
        )
    )

    _ask(client, token, project["id"], "When is the launch deadline?")
    _ask(client, token, project["id"], "What happens if it is late?")

    # The second call carries the first question and answer as memory
    second_call = model.calls[1]
    assert [m.type for m in second_call] == ["system", "human", "ai", "human"]
    assert second_call[1].content == "When is the launch deadline?"

    history = client.get(
        f"/project/{project['id']}/assistant/history", headers=auth_headers(token)
    ).json()
    assert [m["role"] for m in history] == ["user", "assistant", "user", "assistant"]
    assert history[1]["sources"][0]["file_name"] == "contract.docx"

    client.delete(f"/project/{project['id']}/assistant/history", headers=auth_headers(token))
    assert (
        client.get(
            f"/project/{project['id']}/assistant/history", headers=auth_headers(token)
        ).json()
        == []
    )


def test_history_is_private_per_user(client):
    token, project = _setup(client)
    register_and_login(client, "bob")
    client.post(f"/project/{project['id']}/invite?user=bob", headers=auth_headers(token))
    bob = register_and_login(client, "bob")

    _ask(client, token, project["id"], "When is the launch deadline?")

    bob_history = client.get(
        f"/project/{project['id']}/assistant/history", headers=auth_headers(bob)
    ).json()
    assert bob_history == []


# --- agent -------------------------------------------------------------------------------


def test_agent_calls_tools_then_answers(client):
    token, project = _setup(client)
    model = _use_model(
        FakeChatModel(
            [
                tool_call("search_documents", {"query": "development cost"}),
                "Development costs 40,000 USD [1].",
            ]
        )
    )

    body = _ask(
        client, token, project["id"], "How much does development cost?", mode="agent"
    ).json()

    assert body["mode"] == "agent"
    assert body["tool_calls"] == ["search_documents"]
    assert body["answer"] == "Development costs 40,000 USD [1]."
    assert body["sources"][0]["file_name"] == "contract.docx"
    assert set(model.bound_tools) == {
        "search_documents",
        "list_documents",
        "read_document",
        "get_project_info",
    }
    # The tool result (with the numbered excerpt) was sent back to the model
    tool_message = model.calls[1][-1]
    assert tool_message.type == "tool" and "40,000 USD" in tool_message.content


def test_agent_can_list_and_read_documents(client):
    token, project = _setup(client)
    model = _use_model(
        FakeChatModel(
            [
                tool_call("list_documents", {}, "c1"),
                tool_call("read_document", {"file_name": "brief.pdf"}, "c2"),
                "The brief describes a yoga booking app with a kickoff in Yerevan [1][2].",
            ]
        )
    )

    body = _ask(client, token, project["id"], "Summarise the brief", mode="agent").json()

    assert body["tool_calls"] == ["list_documents", "read_document"]
    assert "contract.docx" in model.calls[1][-1].content  # list_documents output
    assert [s["page_number"] for s in body["sources"]] == [1, 2]


def test_agent_stops_at_step_limit(client, monkeypatch):
    from app.core.config import settings

    token, project = _setup(client)
    monkeypatch.setattr(settings, "AGENT_MAX_STEPS", 2)
    _use_model(FakeChatModel([tool_call("list_documents", {}, f"c{i}") for i in range(10)]))

    body = _ask(client, token, project["id"], "Loop forever", mode="agent").json()

    assert "step limit" in body["answer"]
    assert body["warning"]


def test_agent_mode_without_llm_uses_rag(client):
    token, project = _setup(client)

    body = _ask(client, token, project["id"], "launch deadline", mode="agent").json()

    assert body["mode"] == "rag"
    assert "Agent mode needs a language model" in body["warning"]


# --- monitoring ----------------------------------------------------------------------------


def test_feedback_and_stats(client):
    token, project = _setup(client)
    _use_model(FakeChatModel(["Answer one [1].", "Answer two [1]."]))

    first = _ask(client, token, project["id"], "launch deadline").json()
    _ask(client, token, project["id"], "payment terms")

    feedback = client.post(
        f"/project/{project['id']}/assistant/feedback/{first['request_id']}",
        json={"helpful": True},
        headers=auth_headers(token),
    )
    assert feedback.status_code == 204

    stats = client.get(
        f"/project/{project['id']}/assistant/stats", headers=auth_headers(token)
    ).json()
    assert stats["requests"] == 2
    assert stats["fallback_rate"] == 0.0
    assert stats["feedback_count"] == 1
    assert stats["helpful_rate"] == 1.0
    assert stats["avg_top_score"] > 0


def test_feedback_only_for_own_requests(client):
    token, project = _setup(client)
    register_and_login(client, "bob")
    client.post(f"/project/{project['id']}/invite?user=bob", headers=auth_headers(token))
    bob = register_and_login(client, "bob")

    request_id = _ask(client, token, project["id"], "launch deadline").json()["request_id"]

    response = client.post(
        f"/project/{project['id']}/assistant/feedback/{request_id}",
        json={"helpful": False},
        headers=auth_headers(bob),
    )
    assert response.status_code == 404
