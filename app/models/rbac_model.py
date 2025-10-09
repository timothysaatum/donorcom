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
    
    users: Mapped[List["User"]] = relationship("User", secondary=user_roles, back_populates="roles")

class Permission(Base):
    __tablename__ = "permissions"
    id: Mapped[int] = Column(Integer, primary_key=True, autoincrement=True, nullable=False)
    name: Mapped[str] = Column(String(96), unique=True, index=True)
    roles: Mapped[List[Role]] = relationship(secondary=role_permissions, back_populates="permissions")



class UserRoleScope(Base):
    __tablename__ = "user_role_scopes"

    role_id: Mapped[int] = Column(
        Integer,
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )

    # This can remain String if it references facility IDs that are strings
    # But if facilities.id is UUID, change this to PGUUID(as_uuid=True) as well
    facility_id: Mapped[Optional[str]] = Column(String(36), index=True, nullable=True)

    # Change from String(36) to UUID to match users.id
    user_id: Mapped[uuid.UUID] = Column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )


# --- Impersonation Sessions ---


class ImpersonationSession(Base):
    __tablename__ = "impersonation_sessions"

    # Change from String(36) to UUID type to match users.id
    id: Mapped[uuid.UUID] = Column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Change foreign key columns from String(36) to UUID type
    moderator_id: Mapped[Optional[uuid.UUID]] = Column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )

    target_user_id: Mapped[Optional[uuid.UUID]] = Column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )

    reason: Mapped[Optional[str]] = Column(String(255), nullable=True)
    started_at: Mapped[Optional[dt.datetime]] = Column(
        DateTime(timezone=True), default=dt.datetime.utcnow, nullable=True
    )
    ended_at: Mapped[Optional[dt.datetime]] = Column(
        DateTime(timezone=True), nullable=True
    )
    active: Mapped[Optional[bool]] = Column(
        Boolean, default=True, index=True, nullable=True
    )

    __table_args__ = (
        Index("ix_impersonation_active_moderator", "active", "moderator_id"),
        Index("ix_impersonation_active_target", "active", "target_user_id"),
    )
