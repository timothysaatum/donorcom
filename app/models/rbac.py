from typing import List, Optional
import uuid
import datetime as dt
from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime, ForeignKey, Table, Index
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, relationship
from app.db.base import Base

# --- Core RBAC ---

role_permissions = Table(
    "role_permissions", Base.metadata,
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True, nullable=False),
    Column("permission_id", Integer, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True, nullable=False),
)

user_roles = Table(
    "user_roles", Base.metadata,
    Column("user_id", PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, nullable=False),
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True, nullable=False),
)

# --- Role and Permission ---

class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = Column(Integer, primary_key=True, autoincrement=True, nullable=False)
    name: Mapped[str] = Column(String(64), unique=True, index=True)
    parent_id: Mapped[Optional[int]] = Column(ForeignKey("roles.id", ondelete="SET NULL"), nullable=True)
    parent: Mapped[Optional["Role"]] = relationship(remote_side=[id])
    permissions: Mapped[List["Permission"]] = relationship(secondary=role_permissions, back_populates="roles")
    
    # ADD THIS LINE: Missing users relationship
    users: Mapped[List["User"]] = relationship("User", secondary=user_roles, back_populates="roles")

class Permission(Base):
    __tablename__ = "permissions"
    id: Mapped[int] = Column(Integer, primary_key=True, autoincrement=True, nullable=False)
    name: Mapped[str] = Column(String(96), unique=True, index=True)
    roles: Mapped[List[Role]] = relationship(secondary=role_permissions, back_populates="permissions")

# --- Optional per-facility scoping ---

class UserRoleScope(Base):
    __tablename__ = "user_role_scopes"
    role_id: Mapped[int] = Column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True, nullable=False)
    facility_id: Mapped[Optional[str]] = Column(String(36), index=True, nullable=True)
    user_id: Mapped[str] = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, nullable=False)

# --- Impersonation Sessions ---

class ImpersonationSession(Base):
    __tablename__ = "impersonation_sessions"
    id: Mapped[str] = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    moderator_id: Mapped[str] = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    target_user_id: Mapped[str] = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    reason: Mapped[str] = Column(String(255))
    started_at: Mapped[dt.datetime] = Column(DateTime(timezone=True), default=dt.datetime.utcnow)
    ended_at: Mapped[Optional[dt.datetime]] = Column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = Column(Boolean, default=True, index=True)

    __table_args__ = (
        Index("ix_impersonation_active_moderator", "active", "moderator_id"),
        Index("ix_impersonation_active_target", "active", "target_user_id"),
    )