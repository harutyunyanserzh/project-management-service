import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.base import ProjectRole
from app.models.document import Document
from app.models.project import Project, ProjectAccess
from app.models.user import User

# HTTPBearer renders as a plain "paste your token" field in Swagger UI's
# Authorize dialog -- appropriate here since POST /login takes JSON, not
# OAuth2 form-encoded credentials.
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the JWT bearer token into a User, or raise 401.

    Every business-logic route depends on this (directly or via a further
    permission-checking dependency) so that all requests are authorized via
    the JWT issued by POST /login, per the project spec.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise credentials_exception

    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise credentials_exception

    user_id_raw = payload.get("sub")
    if user_id_raw is None:
        raise credentials_exception

    try:
        user_id = uuid.UUID(user_id_raw)
    except (ValueError, TypeError):
        raise credentials_exception

    user = db.get(User, user_id)
    if user is None:
        raise credentials_exception

    return user


def get_project_or_404(project_id: uuid.UUID, db: Session = Depends(get_db)) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


def get_project_access_or_403(
    project: Project = Depends(get_project_or_404),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectAccess:
    """Resolve the current user's ProjectAccess row for this project.

    Raises 403 if the user has no access at all. Use this directly when a
    route just needs "any access" (owner or participant); use
    require_owner below when a route needs owner-only access.
    """
    access = (
        db.query(ProjectAccess)
        .filter(ProjectAccess.project_id == project.id, ProjectAccess.user_id == current_user.id)
        .first()
    )
    if access is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this project",
        )
    return access


def require_owner(
    access: ProjectAccess = Depends(get_project_access_or_403),
) -> ProjectAccess:
    """Use for routes that only the project owner may perform (delete, invite)."""
    if access.role != ProjectRole.OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the project owner can perform this action",
        )
    return access


def get_document_or_404(document_id: uuid.UUID, db: Session = Depends(get_db)) -> Document:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return document


def get_document_access_or_403(
    document: Document = Depends(get_document_or_404),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Document:
    """A user may act on a document iff they have access to its parent project.
    Returns the document (not the access row) since document routes need the
    document itself, not the requester's role."""
    access = (
        db.query(ProjectAccess)
        .filter(
            ProjectAccess.project_id == document.project_id,
            ProjectAccess.user_id == current_user.id,
        )
        .first()
    )
    if access is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this document's project",
        )
    return document
