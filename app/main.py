from fastapi import Depends, FastAPI

from app.api import auth
from app.api.deps import get_current_user
from app.core.config import settings
from app.models.user import User
from app.schemas.user import UserRead

app = FastAPI(title=settings.APP_NAME)

app.include_router(auth.router)


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/me", response_model=UserRead, tags=["auth"])
def read_current_user(current_user: User = Depends(get_current_user)) -> User:
    """Sanity-check route: proves the JWT bearer flow works end-to-end."""
    return current_user
