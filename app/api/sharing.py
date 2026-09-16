from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import EmailStr
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_owner
from app.core.config import settings
from app.core.security import generate_share_token, hash_share_token
from app.db.session import get_db
from app.models.base import ProjectRole
from app.models.project import ProjectAccess
from app.models.share_token import ShareToken
from app.models.user import User
from app.services.email import send_email

router = APIRouter(tags=["sharing"])


@router.get("/project/{project_id}/share")
def share_project(
    email: EmailStr = Query(alias="with"),
    access: ProjectAccess = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Email a single-use, expiring join link for this project. Owner-only.

    The spec names the query parameter `with`, which is a Python reserved
    word, so it is exposed to clients under that name via an alias while
    binding to `email` internally.
    """
    raw_token, token_hash = generate_share_token()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.SHARE_TOKEN_EXPIRE_MINUTES)

    share_token = ShareToken(
        project_id=access.project_id,
        invited_email=str(email),
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(share_token)
    db.commit()

    join_url = f"{settings.FRONTEND_BASE_URL}/join?token={raw_token}"
    send_email(
        to=str(email),
        subject=f"You've been invited to the project '{access.project.name}'",
        body=(
            f"You have been invited to collaborate on '{access.project.name}'.\n\n"
            f"Open this link to accept (valid for "
            f"{settings.SHARE_TOKEN_EXPIRE_MINUTES // 60} hours):\n\n{join_url}\n"
        ),
    )

    return {"detail": f"Invitation sent to {email}"}


@router.get("/join")
def join_project(
    token: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Redeem a share token, granting the logged-in user participant access.

    The caller must be authenticated: the token proves *that* an invitation
    was issued, but the JWT proves *who* is redeeming it, so access is
    granted to a real account rather than to whoever holds the link.
    """
    share_token = (
        db.query(ShareToken).filter(ShareToken.token_hash == hash_share_token(token)).first()
    )

    if share_token is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid invitation link")

    if share_token.used:
        raise HTTPException(
            status_code=status.HTTP_410_GONE, detail="This invitation has already been used"
        )

    expires_at = share_token.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="This invitation has expired")

    existing = (
        db.query(ProjectAccess)
        .filter(
            ProjectAccess.project_id == share_token.project_id,
            ProjectAccess.user_id == current_user.id,
        )
        .first()
    )
    if existing is not None:
        share_token.used = True
        db.commit()
        return {"detail": "You already have access to this project"}

    db.add(
        ProjectAccess(
            project_id=share_token.project_id,
            user_id=current_user.id,
            role=ProjectRole.PARTICIPANT,
        )
    )
    share_token.used = True
    db.commit()

    return {"detail": "Access granted", "project_id": str(share_token.project_id)}
