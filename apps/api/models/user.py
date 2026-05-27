"""
User account model + auth request/response schemas.

Users own meetings (see ``Meeting.owner_id``); per-user row-level
isolation is enforced in the meeting endpoints.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.core.database import Base


class User(Base):
    """A registered user."""

    __tablename__ = "users"
    __table_args__ = {"schema": "doc_intel"}

    id: Mapped[str] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    email: Mapped[str] = mapped_column(
        String(320), unique=True, nullable=False, index=True
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email='{self.email}')>"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class UserRegister(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str = Field(default="", max_length=255)


class UserLogin(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    full_name: str = ""
    is_active: bool = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
