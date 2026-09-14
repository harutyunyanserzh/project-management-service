# Project Management Service

A FastAPI backend for creating, sharing, and managing projects and their
documents. Built as a final project: JWT-authenticated REST API, PostgreSQL
via SQLAlchemy, document storage on AWS S3, a Lambda function enforcing
per-project storage limits, Dockerized for local dev, tested with pytest,
and wired into a GitHub Actions CI/CD pipeline.

## Stack

- Python 3.10, FastAPI
- PostgreSQL + SQLAlchemy (ORM) + Alembic (migrations)
- Docker / Docker Compose
- AWS S3 (document storage) + AWS Lambda (storage size limit enforcement)
- JWT auth (1-hour expiry), bcrypt password hashing
- pytest (32 tests, mocked S3 via `moto`, isolated SQLite per test)
- GitHub Actions (lint → test → build → push → deploy)

## Architecture

Two access levels per project, per spec:

- **owner** — the project's creator. Full control: edit, delete, invite others.
- **participant** — an invited user. Can view/edit project info and manage
  documents, but cannot delete the project or invite further users.

Every route resolves the requester's access via a chain of FastAPI
dependencies (`app/api/deps.py`):

```
JWT bearer token → get_current_user → get_project_access_or_403 → require_owner (where needed)
```

Documents inherit their access rules from their parent project
(`get_document_access_or_403`), so a document route never checks permissions
independently of the project it belongs to.

### Data model

- `users` — login/hashed_password
- `projects` — name/description/owner_id (denormalized convenience pointer;
  source of truth for membership is `project_access`)
- `project_access` — join table: (project_id, user_id, role)
- `documents` — file_name/content_type/size_bytes/s3_key, scoped to a project
- `share_tokens` — backs the optional email-invite-link flow

## Running locally

```bash
cp .env.example .env
docker compose up --build
```

App runs at `http://localhost:8000`. Interactive docs at
`http://localhost:8000/docs`.

On first run, generate and apply the initial migration:

```bash
docker compose run --rm app alembic revision --autogenerate -m "initial tables"
docker compose up
```

## Running tests

```bash
poetry install --with dev
poetry run pytest tests/ -v
```

Tests use an isolated in-memory SQLite database and a mocked S3 (via
`moto`) — no real database or AWS credentials required to run the suite.

## API

| Method | Path | Description | Access |
|---|---|---|---|
| POST | `/auth` | Register a user | public |
| POST | `/login` | Log in, get a JWT (1h expiry) | public |
| POST | `/projects` | Create a project (creator becomes owner) | authenticated |
| GET | `/projects` | List accessible projects (full info + documents) | authenticated |
| GET | `/project/{id}/info` | Get project details | owner/participant |
| PUT | `/project/{id}/info` | Update name/description | owner/participant |
| DELETE | `/project/{id}` | Delete project (+ its documents, DB and S3) | owner only |
| POST | `/project/{id}/invite?user=<login>` | Grant participant access | owner only |
| GET | `/project/{id}/documents` | List a project's documents | owner/participant |
| POST | `/project/{id}/documents` | Upload document(s) (pdf/docx only) | owner/participant |
| GET | `/document/{id}` | Download a document | owner/participant |
| PUT | `/document/{id}` | Replace a document's file | owner/participant |
| DELETE | `/document/{id}` | Delete a document | owner/participant |

## AWS deployment (S3 + Lambda)

See `lambda_functions/README.md` for step-by-step CLI instructions to
create the S3 bucket, deploy the size-limit Lambda, and wire up the S3
event trigger.

## CI/CD

`.github/workflows/ci.yml` runs on every push/PR to `main`:

1. **lint** — `ruff check` + `black --check`
2. **test** — full pytest suite
3. **build-and-push** — builds the Docker image, pushes to GitHub Container
   Registry (`ghcr.io/<repo>`) — only on merge to `main`
4. **deploy** — placeholder step; wire up to your actual deploy target
   (AWS ECS/App Runner, a VM, etc.) once decided

## Project status

- [x] Auth (register/login, JWT)
- [x] Project CRUD + owner/participant permissions + invite
- [x] Documents (upload/download/update/delete via S3)
- [x] Lambda: per-project storage size limit enforcement
- [x] Automated tests (pytest, 32 passing)
- [x] CI/CD pipeline
- [ ] Optional: email share-link flow (`GET /project/{id}/share?with=<email>`)
- [ ] Optional: image thumbnail Lambda (scaffolded, not wired to a real use case)
