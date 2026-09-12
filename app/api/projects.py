import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user, get_project_access_or_403, require_owner
from app.db.session import get_db
from app.models.base import ProjectRole
from app.models.project import Project, ProjectAccess
from app.models.user import User
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate
from app.services import storage

router = APIRouter(tags=["projects"])


def _to_project_read(project: Project, role: ProjectRole) -> ProjectRead:
    return ProjectRead(
        id=project.id,
        name=project.name,
        description=project.description,
        owner_id=project.owner_id,
        created_at=project.created_at,
        updated_at=project.updated_at,
        my_role=role,
        documents=list(project.documents),
    )


@router.post("/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectRead:
    """Create a project. The creator automatically becomes its OWNER."""
    project = Project(name=payload.name, description=payload.description, owner_id=current_user.id)
    db.add(project)
    db.flush()  # populate project.id before creating the access row

    access = ProjectAccess(project_id=project.id, user_id=current_user.id, role=ProjectRole.OWNER)
    db.add(access)
    db.commit()
    db.refresh(project)

    return _to_project_read(project, ProjectRole.OWNER)


@router.get("/projects", response_model=list[ProjectRead])
def list_projects(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ProjectRead]:
    """List every project the current user has access to (owner or participant),
    with full details (info + documents)."""
    accesses = (
        db.query(ProjectAccess)
        .filter(ProjectAccess.user_id == current_user.id)
        .options(joinedload(ProjectAccess.project).joinedload(Project.documents))
        .all()
    )
    return [_to_project_read(a.project, a.role) for a in accesses]


@router.get("/project/{project_id}/info", response_model=ProjectRead)
def get_project_info(
    access: ProjectAccess = Depends(get_project_access_or_403),
) -> ProjectRead:
    return _to_project_read(access.project, access.role)


@router.put("/project/{project_id}/info", response_model=ProjectRead)
def update_project_info(
    payload: ProjectUpdate,
    access: ProjectAccess = Depends(get_project_access_or_403),
    db: Session = Depends(get_db),
) -> ProjectRead:
    """Update name/description. Both owner and participant may edit project info."""
    project = access.project
    if payload.name is not None:
        project.name = payload.name
    if payload.description is not None:
        project.description = payload.description

    db.add(project)
    db.commit()
    db.refresh(project)

    return _to_project_read(project, access.role)


@router.delete("/project/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    access: ProjectAccess = Depends(require_owner),
    db: Session = Depends(get_db),
) -> None:
    """Delete a project. Owner-only. Cascades to delete its documents (DB rows
    and their underlying S3 objects) and access rows."""
    for document in access.project.documents:
        storage.delete_file(document.s3_key)

    db.delete(access.project)
    db.commit()


@router.post("/project/{project_id}/invite", response_model=ProjectRead)
def invite_user_to_project(
    user: str,
    access: ProjectAccess = Depends(require_owner),
    db: Session = Depends(get_db),
) -> ProjectRead:
    """Grant PARTICIPANT access to another user by login. Owner-only."""
    invitee = db.query(User).filter(User.login == user).first()
    if invitee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if invitee.id == access.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="User already has owner access"
        )

    existing = (
        db.query(ProjectAccess)
        .filter(ProjectAccess.project_id == access.project_id, ProjectAccess.user_id == invitee.id)
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="User already has access to this project"
        )

    new_access = ProjectAccess(
        project_id=access.project_id, user_id=invitee.id, role=ProjectRole.PARTICIPANT
    )
    db.add(new_access)
    db.commit()
    db.refresh(access.project)

    return _to_project_read(access.project, access.role)
