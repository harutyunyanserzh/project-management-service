# Project Management Service

A FastAPI backend for creating, updating, sharing, and deleting projects and their attached documents. The project demonstrates authentication, role-based project access, PostgreSQL persistence, document storage, Docker, automated tests, and GitHub Actions CI.

## Stack

- Python 3.10 + FastAPI
- PostgreSQL + SQLAlchemy ORM + Alembic migrations
- uv for Python dependency and environment management
- Docker / Docker Compose
- S3-compatible document storage through boto3
- JWT authentication + bcrypt password hashing
- pytest with SQLite and mocked S3 for automated tests
- GitHub Actions for linting, unit tests, and Docker build verification

Real AWS deployment is not required to run or test this project. The S3 and Lambda code remains in the repository as part of the requested architecture and can be demonstrated locally/mocked.

## Main functionality

Users can register and log in, create projects, see projects they can access, update project information, upload PDF/DOCX documents, replace or delete documents, and share projects with other users.

A project has two roles:

- **owner** — the creator; can edit, delete, and invite users.
- **participant** — an invited user; can view/edit project information and manage documents, but cannot delete the project or invite users.

The creator automatically receives an OWNER `ProjectAccess` row when a project is created. Documents use the access rules of their parent project.

## Data model

- `users` — login and hashed password
- `projects` — project name, description, and owner
- `project_access` — connects users to projects and stores their role
- `documents` — document metadata and storage key
- `share_tokens` — hashed, expiring, single-use invitation tokens

## Dependency management with uv

This project uses **uv** instead of pip/Poetry for dependency and virtual-environment management. Dependencies are declared in `pyproject.toml`.

Install uv by following the official uv documentation, then from the repository root run:

```bash
uv sync
```

Run application commands through uv, for example:

```bash
uv run pytest tests/ -v
uv run ruff check .
uv run black --check .
```

## Running locally with Docker

Create the local environment file first:

```bash
cp .env.example .env
```

Then run:

```bash
docker compose up --build
```

Docker Compose starts PostgreSQL, applies the existing Alembic migration with `alembic upgrade head`, and starts FastAPI.

The API is available at `http://localhost:8000` and the interactive Swagger documentation is at `http://localhost:8000/docs`.

Do **not** generate another initial migration during normal setup; the repository already contains the initial migration.

## Running tests

```bash
uv sync
uv run pytest tests/ -v
```

Tests use an isolated in-memory SQLite database and mocked S3 through `moto`, so real PostgreSQL/AWS credentials are not needed for the test suite.

## API

| Method | Path | Description | Access |
|---|---|---|---|
| POST | `/auth` | Register a user | public |
| POST | `/login` | Log in and receive JWT | public |
| POST | `/projects` | Create a project; creator becomes owner | authenticated |
| GET | `/projects` | List accessible projects with details/documents | authenticated |
| GET | `/project/{id}/info` | Get project details | owner/participant |
| PUT | `/project/{id}/info` | Update project name/description | owner/participant |
| DELETE | `/project/{id}` | Delete a project | owner only |
| POST | `/project/{id}/invite?user=<login>` | Add an existing user as participant | owner only |
| GET | `/project/{id}/share?with=<email>` | Create and send an expiring share link | owner only |
| GET | `/join?token=<token>` | Redeem a share link | authenticated |
| GET | `/project/{id}/documents` | List project documents | owner/participant |
| POST | `/project/{id}/documents` | Upload PDF/DOCX document(s) | owner/participant |
| GET | `/document/{id}` | Download a document | owner/participant |
| PUT | `/document/{id}` | Replace a document | owner/participant |
| DELETE | `/document/{id}` | Delete a document | owner/participant |

## Document storage limit

`MAX_PROJECT_STORAGE_BYTES` controls the maximum storage allowed for one project (100 MB by default). The API checks the projected size before accepting an upload or replacement. This prevents a database document record from being created for a file that exceeds the limit.

The `lambda_functions/size_limit` implementation remains as an additional architecture example/defense-in-depth mechanism. It is not required for local development or automated tests.

## Sharing

There are two sharing approaches in the project:

1. `/project/{id}/invite?user=<login>` immediately gives an existing registered user participant access.
2. `/project/{id}/share?with=<email>` creates a hashed, expiring, single-use token and sends/logs a join URL. The user must be authenticated before redeeming the token.

When SMTP is not configured, the development email service logs the invitation instead of sending a real email.

## CI

`.github/workflows/ci.yml` runs on **every branch push**, including feature branches, and on pull requests to `main`.

The pipeline performs:

1. Ruff lint check
2. Black formatting check
3. Unit tests with pytest
4. Docker image build verification

There is intentionally no cloud deployment step because deployment to AWS or another cloud provider is outside the current project scope.

## Commit convention

This repository uses **Conventional Commits**. New commits should follow the form:

```text
<type>: <short description>
```

Common examples:

```text
feat: add project sharing endpoint
fix: reject files above project storage limit
test: add document upload unit tests
docs: update setup instructions
ci: run tests on feature branches
build: migrate dependency management to uv
```

Typical types are `feat`, `fix`, `test`, `docs`, `ci`, `build`, `refactor`, and `chore`.

## License

This project is released under the MIT License. See the `LICENSE` file.

## Project status

- [x] User registration and JWT login
- [x] Project create/read/update/delete
- [x] Owner and participant permissions
- [x] Direct user invitation
- [x] Expiring single-use share-link flow
- [x] PDF/DOCX upload, download, replacement, and deletion
- [x] Project storage-limit checks
- [x] PostgreSQL models and Alembic migration
- [x] Docker / Docker Compose setup
- [x] uv dependency management
- [x] Automated tests with mocked external storage
- [x] CI unit tests on every feature-branch push
- [x] Conventional Commits documented
- [x] MIT open-source license
- [x] Lambda examples retained for the required architecture
