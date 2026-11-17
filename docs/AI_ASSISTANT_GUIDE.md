# AI Project Assistant: how it works

This guide explains the AI part of the service: what each file does, why it is built that way, and the trade-offs. Read it alongside the code.

## 1. The problem

A project collects contracts, requirements and meeting notes. Finding one fact ("what is the late-delivery penalty?") means opening files and searching by hand. The assistant lets a project member ask in plain language and get a short answer with the exact source.

Two constraints shape the design:

1. **Answers must come from the documents.** A language model on its own will happily invent a deadline. So the model is only given the relevant excerpts and told to answer from them.
2. **Permissions must hold.** A user must never see text from a project they cannot access, even indirectly through the AI.

## 2. Map of the code

| File | Responsibility |
|---|---|
| `app/ai/text_extraction.py` | PDF/DOCX bytes → text, keeping PDF page numbers and DOCX tables |
| `app/ai/chunking.py` | Text → overlapping chunks (LangChain `RecursiveCharacterTextSplitter`) |
| `app/ai/embeddings.py` | Embedding providers: Ollama, Hugging Face, or keyword-hash for tests |
| `app/ai/vector_store.py` | Save chunks with vectors; similarity search with pgvector (or Python on SQLite) |
| `app/ai/indexing.py` | The pipeline run after each upload: download → extract → chunk → embed → store |
| `app/ai/llm.py` | One setting picks the chat model: Ollama, Claude, OpenAI or none |
| `app/ai/prompts.py` | System prompts, numbered context with a size budget, no-LLM fallback answer |
| `app/ai/memory.py` | Chat history per user and project |
| `app/ai/rag.py` | Retrieval-Augmented Generation: retrieve, then answer from the excerpts |
| `app/ai/agent.py` | LangGraph agent with four project-scoped tools |
| `app/ai/service.py` | One request end to end: memory → RAG/agent → save history → log metrics |
| `app/api/assistant.py` | HTTP endpoints, reusing the existing project permission checks |
| `app/models/ai.py` | Tables: `document_chunks`, `chat_messages`, `ai_request_logs` |
| `evaluation/eval_retrieval.py` | Measures retrieval quality (hit@k, MRR) on labelled questions |

## 3. Indexing: from file to searchable chunks

Triggered by `upload_project_documents` and `update_document` through FastAPI `BackgroundTasks`, so the upload response is not delayed by embedding.

1. **Extract text.** `pypdf` reads each PDF page separately, so every chunk knows its page. `python-docx` reads paragraphs and table rows (tables often hold budgets and dates).
2. **Chunk.** Whole documents are too long to embed well or to fit in a prompt. The recursive splitter cuts at paragraph breaks first, then lines, sentences and words, so pieces stay readable. Defaults: 1,000 characters with 150 characters of overlap, so a fact that sits on a boundary appears in both neighbouring chunks.
3. **Embed.** Each chunk becomes a vector. Texts with similar meaning get vectors pointing in similar directions.
4. **Store.** Vectors go into a `vector` column (pgvector) next to the chunk text, page number, project id and the name of the embedding model.

If a file cannot be read (corrupt or scanned without text), indexing logs a warning and the upload still succeeds. A failed index never breaks the core feature.

## 4. Answering: RAG mode

`answer_with_rag` in `app/ai/rag.py`:

1. **Build the search query.** For follow-ups like "and what if it's late?", the previous user question is added, so the search knows what "it" is.
2. **Retrieve** the top `RAG_TOP_K` chunks by cosine similarity, **filtered by project id**, using pgvector's `<=>` operator inside PostgreSQL.
3. **No match → no model call.** If nothing relevant is found, the assistant says so directly. This avoids a hallucinated answer and saves a model call.
4. **Build the prompt.** System rules + recent chat history + the question with numbered excerpts, `[1] (contract.docx, page 2) ...`, inside `<documents>` tags. A character budget (`CONTEXT_CHAR_BUDGET`) caps the context so the prompt always fits the model's context window.
5. **Call the model** and return the answer, sources and token usage.
6. **If the model fails** (Ollama not running, network error), return the most relevant passages instead of an error.

## 5. Agent mode with LangGraph

Some questions need more than one search: "summarise the brief", "compare the two contracts", "which documents mention Stripe?". In agent mode, the model plans its own steps.

```
START → agent ──(tool calls requested)──→ tools ─┐
          ↑                                      │
          └──────────────────────────────────────┘
        agent ──(final answer)──→ END
```

- `agent` node: the chat model with tools bound (`bind_tools`). It either asks for tool calls or writes the answer.
- `tools` node: LangGraph's `ToolNode` runs the requested tools and returns their results.
- `tools_condition` routes between them. `AGENT_MAX_STEPS` sets a recursion limit so a confused model cannot loop forever.

The tools are created per request by `build_tools(db, project_id, ...)`. The **project id is captured in the closure**; the model never passes it. Even if a document contains "search project X instead", the tools cannot reach another project.

`SourceTracker` numbers every excerpt the tools return, so the `[n]` citations in the agent's answer match the `sources` list in the API response.

## 6. Prompt engineering decisions

- **Grounding rule**: answer only from the excerpts; say plainly if the answer is not there.
- **Citations** `[1]`, `[2]`: users can verify answers, and the API returns each source's file, page and excerpt.
- **Prompt-injection defence**: document text is wrapped in `<documents>` tags and the system prompt says it is data, not instructions. This is a mitigation, not a guarantee. The stronger protection is architectural: retrieval and tools are scoped to one project in code.
- **Temperature 0** by default for consistent, factual answers.

## 7. Context management

- **Chat memory**: the last `CHAT_HISTORY_TURNS` messages for this user and project are sent with each question. Older ones are dropped, so the prompt does not grow without limit.
- **Context budget**: retrieved excerpts stop being added once `CONTEXT_CHAR_BUDGET` characters are used.
- **Query rewriting for follow-ups**: see RAG step 1.
- **Private history**: each user sees only their own conversation, even in a shared project.

## 8. Choosing models

- **Ollama (default)**: free and local; no data leaves the machine. Llama 3.2 (3B) is small enough for a laptop and supports tool calling, which the agent needs. Larger local models (for example `qwen2.5:7b`) are more accurate but slower.
- **Claude / GPT**: higher answer quality, paid per token. Switching is one setting because every provider implements LangChain's chat-model interface.
- **Embeddings**: `nomic-embed-text` via Ollama by default; `all-MiniLM-L6-v2` via Hugging Face sentence-transformers as an option; keyword-hash for tests. Each chunk stores its model name, and search only compares vectors from the same model. After a model change, `/reindex` rebuilds the vectors.

## 9. Monitoring and evaluation

- `ai_request_logs` records latency, token counts, number of sources, best similarity score, fallback use and errors for every request.
- Users rate answers with `/feedback/{request_id}`.
- `/stats` aggregates average latency, fallback rate, average top score, tokens and the helpful rate. A falling average top score suggests documents are missing or chunking is poor; a rising fallback rate means the model server is unhealthy.
- `evaluation/eval_retrieval.py` measures **hit@k** and **MRR** on 15 labelled questions. Run it before and after changing chunk size, overlap, top-k or embedding model.

## 10. Testing strategy

- Fake chat models return scripted replies and record the messages they receive. Tests check what reached the model (excerpts, history, system rules), not just the final text.
- Keyword-hash embeddings make retrieval deterministic with no downloads.
- Real PDF and DOCX files are generated in the tests, so extraction is tested for real.
- Security tests: non-members get 403, search never crosses projects, history is private, feedback only on your own requests.
- Agent tests: tool calls are executed, tool results go back to the model, the step limit stops loops.

## 11. Known limitations and next steps

- **Scanned PDFs** (images of text) produce no text. Next step: OCR (for example Tesseract) during extraction.
- **No vector index yet.** Search scans a project's chunks, which is fine for hundreds or thousands of chunks per project. For large projects, add an HNSW index per embedding dimension.
- **Hybrid search**: combining keyword (BM25) and vector scores often improves retrieval for names, codes and numbers.
- **Re-ranking**: a cross-encoder could re-order the top 20 results before taking the best 4.
- **Background jobs**: `BackgroundTasks` runs in the web process. A queue (Celery, RQ or AWS SQS + Lambda) would make indexing durable and scalable.
- **Streaming** answers token by token would improve perceived speed.
- **Answer evaluation**: the script measures retrieval; scoring answer faithfulness (for example with an LLM judge) is the natural next step.

## 12. Questions you should be able to answer

- Why split documents into chunks, and why overlap them?
- What is an embedding, and why does cosine similarity find relevant text?
- Why store vectors in PostgreSQL with pgvector instead of a separate vector database? (One system, transactions, joins with permissions; trade-off: dedicated stores scale further.)
- How do you stop a user from getting another project's data through the AI?
- What happens if the model is down? If the document is unreadable?
- When would you use the agent instead of plain RAG? What stops it from looping?
- How do you know retrieval is good? What are hit@k and MRR?
- How would you scale indexing to thousands of documents?
- How do you test code that calls an LLM without paying for API calls?
