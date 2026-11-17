"""LangGraph agent: the model decides which tools to call, in what order, before answering.

The graph has two nodes and one loop:

    START -> agent --(model asked for tools)--> tools -> agent -> ...
                   \\-(model wrote an answer)--> END

RAG always does exactly one search. The agent can search several times, list the
documents, or read a whole document -- useful for "compare the two contracts" or
"summarise the requirements doc".
"""

import uuid

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool, tool
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.ai.prompts import AGENT_SYSTEM_PROMPT, format_context
from app.ai.rag import AssistantAnswer, message_text, retrieve
from app.ai.vector_store import ScoredChunk
from app.core.config import settings
from app.models.ai import DocumentChunk
from app.models.document import Document
from app.models.project import Project, ProjectAccess


class SourceTracker:
    """Collects every chunk the tools showed the model, numbered consistently.

    The numbers the model sees ([1], [2], ...) match the order of the `sources` list
    returned to the client, so citations in the answer can be looked up.
    """

    def __init__(self) -> None:
        self.items: list[ScoredChunk] = []
        self._numbers: dict[uuid.UUID, int] = {}

    def add(self, chunks: list[ScoredChunk]) -> str:
        blocks = []
        for item in chunks:
            if item.chunk.id not in self._numbers:
                self.items.append(item)
                self._numbers[item.chunk.id] = len(self.items)
            number = self._numbers[item.chunk.id]
            blocks.append(format_context([item], start=number))
        return "\n\n".join(blocks)


def build_tools(db: Session, project_id: uuid.UUID, tracker: SourceTracker) -> list[BaseTool]:
    """Create tools bound to ONE project.

    The project id is captured in the closure, not passed by the model, so the model
    cannot be talked into reading another project's documents.
    """

    def _document_by_name(file_name: str) -> Document | None:
        documents = db.query(Document).filter(Document.project_id == project_id).all()
        exact = [d for d in documents if d.file_name.lower() == file_name.lower()]
        partial = [d for d in documents if file_name.lower() in d.file_name.lower()]
        return (exact or partial or [None])[0]

    @tool
    def search_documents(query: str) -> str:
        """Search the project's documents for passages relevant to the query.
        Use short, specific keywords, for example 'payment terms' or 'launch deadline'."""
        chunks = retrieve(db, project_id, query)
        if not chunks:
            return "No relevant passages found."
        return tracker.add(chunks)

    @tool
    def list_documents() -> str:
        """List the documents in this project with their size and how many chunks are indexed."""
        rows = (
            db.query(Document, func.count(DocumentChunk.id))
            .outerjoin(DocumentChunk, DocumentChunk.document_id == Document.id)
            .filter(Document.project_id == project_id)
            .group_by(Document.id)
            .all()
        )
        if not rows:
            return "This project has no documents."
        return "\n".join(
            f"- {doc.file_name} ({doc.size_bytes // 1024} KB, {chunks} indexed chunks)"
            for doc, chunks in rows
        )

    @tool
    def read_document(file_name: str) -> str:
        """Read a document from the beginning (up to the context budget).
        Use it to summarise or compare whole documents. Pass the file name from list_documents."""
        document = _document_by_name(file_name)
        if document is None:
            return f"No document named '{file_name}' in this project."
        chunks = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == document.id)
            .order_by(DocumentChunk.chunk_index)
            .all()
        )
        if not chunks:
            return f"'{document.file_name}' has no indexed text."
        scored, used = [], 0
        for chunk in chunks:
            used += len(chunk.content)
            if scored and used > settings.CONTEXT_CHAR_BUDGET // 2:
                break
            scored.append(ScoredChunk(chunk=chunk, file_name=document.file_name, score=1.0))
        return tracker.add(scored)

    @tool
    def get_project_info() -> str:
        """Get the project's name, description, number of members and number of documents."""
        project = db.get(Project, project_id)
        members = db.query(ProjectAccess).filter(ProjectAccess.project_id == project_id).count()
        documents = db.query(Document).filter(Document.project_id == project_id).count()
        return (
            f"Name: {project.name}\n"
            f"Description: {project.description or '(none)'}\n"
            f"Members: {members}\nDocuments: {documents}"
        )

    return [search_documents, list_documents, read_document, get_project_info]


def build_agent_graph(llm: BaseChatModel, tools: list[BaseTool]):
    model_with_tools = llm.bind_tools(tools)

    def call_model(state: MessagesState) -> dict:
        return {"messages": [model_with_tools.invoke(state["messages"])]}

    graph = StateGraph(MessagesState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", ToolNode(tools))
    graph.add_edge(START, "agent")
    # tools_condition routes to "tools" if the last message requested tool calls, else END
    graph.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    return graph.compile()


def answer_with_agent(
    db: Session,
    project_id: uuid.UUID,
    question: str,
    history: list[BaseMessage],
    llm: BaseChatModel,
) -> AssistantAnswer:
    tracker = SourceTracker()
    tools = build_tools(db, project_id, tracker)
    graph = build_agent_graph(llm, tools)

    messages = [
        SystemMessage(content=AGENT_SYSTEM_PROMPT),
        *history,
        HumanMessage(content=question),
    ]
    # Each step is two graph nodes (agent + tools), plus the final answer
    config = {"recursion_limit": settings.AGENT_MAX_STEPS * 2 + 1}
    try:
        state = graph.invoke({"messages": messages}, config=config)
    except GraphRecursionError:
        return AssistantAnswer(
            answer="I couldn't finish within the step limit. Try a more specific question.",
            sources=tracker.items,
            warning=f"Agent stopped after {settings.AGENT_MAX_STEPS} steps.",
        )

    new_messages = state["messages"][len(messages) :]
    ai_messages = [m for m in new_messages if isinstance(m, AIMessage)]
    tool_calls = [call["name"] for m in ai_messages for call in (m.tool_calls or [])]

    input_tokens = output_tokens = 0
    for m in ai_messages:
        usage = m.usage_metadata or {}
        input_tokens += usage.get("input_tokens", 0)
        output_tokens += usage.get("output_tokens", 0)

    final = ai_messages[-1] if ai_messages else None
    return AssistantAnswer(
        answer=(message_text(final) if final else "") or "I couldn't produce an answer.",
        sources=tracker.items,
        input_tokens=input_tokens or None,
        output_tokens=output_tokens or None,
        tool_calls=tool_calls,
    )
