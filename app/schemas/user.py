import uuid

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class UserCreate(BaseModel):
    """Payload for POST /auth (register a new user)."""

    login: str
    password: str
    repeat_password: str

    @field_validator("login")
    @classmethod
    def login_not_blank(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3:
            raise ValueError("login must be at least 3 characters long")
        return v

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters long")
        return v

    @model_validator(mode="after")
    def passwords_match(self) -> "UserCreate":
        if self.password != self.repeat_password:
            raise ValueError("password and repeat_password do not match")
        return self


class UserLogin(BaseModel):
    """Payload for POST /login."""

    login: str
    password: str


class UserRead(BaseModel):
    """Public-facing representation of a user (never includes the password hash)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    login: str


class Token(BaseModel):
    """Response for a successful login."""

    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
