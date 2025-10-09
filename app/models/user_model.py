from datetime import datetime, timezone, timedelta
import uuid
from typing import Optional
from sqlalchemy import String, Boolean, DateTime, ForeignKey, func, Integer, Index
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
from .rbac_model import user_roles
from sqlalchemy.dialects.postgresql import TIMESTAMP


class User(Base):
    __tablename__ = "users"

    # --- Columns ---
    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        index=True,
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    email: Mapped[str] = mapped_column(
        String(100), unique=True, index=True, nullable=False
    )
    password: Mapped[str] = mapped_column(String(255), nullable=False)

    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    status: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    # --- Relationships ---
    work_facility_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("facilities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    work_facility = relationship(
        "Facility",
        back_populates="users",
        foreign_keys=[work_facility_id],
    )

    facility = relationship(
        "Facility",
        back_populates="facility_manager",
        primaryjoin="User.id == foreign(remote(Facility.facility_manager_id))",
        uselist=False,
    )

    blood_bank = relationship("BloodBank", back_populates="manager_user", uselist=False)
    added_blood_units = relationship("BloodInventory", back_populates="added_by")
    notifications = relationship(
        "Notification", back_populates="user", cascade="all, delete-orphan"
    )
    refresh_tokens = relationship(
        "RefreshToken", back_populates="user", cascade="all, delete-orphan"
    )

    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_suspended: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    verification_token: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, index=True
    )
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, index=True
    )
    locked_until: Mapped[Optional[DateTime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True, index=True
    )

    created_at: Mapped[DateTime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[DateTime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_login: Mapped[Optional[DateTime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True, index=True
    )

    # --- RBAC Relationship ---
    roles = relationship("Role", secondary=user_roles, back_populates="users")
    sessions = relationship(
        "UserSession", back_populates="user", cascade="all, delete-orphan"
    )
    trusted_devices = relationship(
        "DeviceTrust", back_populates="user", cascade="all, delete-orphan"
    )

    # --- Methods ---
    def __str__(self) -> str:
        return f"{self.last_name} ({self.email})"

    def update_login_time(self):
        """Call this method when user logs in"""
        self.last_login = func.now()

    def has_permission(self, perm_name: str) -> bool:
        """Check if user has a given permission"""
        return any(
            perm.name == perm_name for role in self.roles for perm in role.permissions
        )

    def has_role(self, role_name: str) -> bool:
        """Check if user has a given role"""
        return any(role.name == role_name for role in self.roles)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def role(self) -> str:
        """Return the role name as a string."""
        if not self.roles:
            return "staff"  # Default role name
        return self.roles[0].name

    # --- Authentication Security Methods ---
    @property
    def is_locked(self) -> bool:
        """Check if account is currently locked"""
        if self.locked_until is None:
            return False
        # Handle both timezone-aware and naive datetimes stored in DB
        locked = self.locked_until
        if getattr(locked, "tzinfo", None) is None:
            locked = locked.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) < locked

    def increment_failed_attempts(
        self, max_attempts: int = 5, lockout_duration_minutes: int = 15
    ):
        """Increment failed login attempts and lock account if threshold reached"""
        self.failed_login_attempts += 1
        if self.failed_login_attempts >= max_attempts:
            self.locked_until = datetime.now(timezone.utc) + timedelta(
                minutes=lockout_duration_minutes
            )

    def reset_failed_attempts(self):
        """Reset failed login attempts and unlock account"""
        self.failed_login_attempts = 0
        self.locked_until = None
        self.last_login = datetime.now(timezone.utc)

    def can_login(self) -> tuple[bool, Optional[str]]:
        """Check if user can login and return reason if not"""
        if not self.is_active:
            return False, "Account is deactivated"
        if not self.status:
            return False, "Account is disabled"
        if self.is_locked:
            return False, f"Account is locked until {self.locked_until}"

        if self.is_suspended:
            return False, "Account is suspended contact support"

        if self.is_banned:
            return False, "Account is banned"

        return True, None

    async def revoke_all_refresh_tokens(self, session=None):
        """Revoke all refresh tokens for this user (useful for logout all devices)"""
        from sqlalchemy import select

        if session is None:
            # If no session provided, try to get refresh_tokens directly
            # This assumes the relationship is already loaded
            if hasattr(self, "_sa_instance_state") and self._sa_instance_state.session:
                session = self._sa_instance_state.session

        if session:
            # Use session to explicitly load refresh tokens
            stmt = select(RefreshToken).where(RefreshToken.user_id == self.id)
            result = await session.execute(stmt)
            tokens = result.scalars().all()

            for token in tokens:
                if not token.revoked:
                    token.revoke()
        else:
            # Fallback: try to access already loaded tokens
            try:
                for token in self.refresh_tokens:
                    if not token.revoked:
                        token.revoke()
            except Exception:
                # If we can't access tokens, skip revocation
                pass

    # Session Management
    async def get_active_sessions(self, session=None):
        """Get all active sessions for this user"""
        from sqlalchemy import select

        if session:
            # Use session to explicitly load sessions
            stmt = select(UserSession).where(
                UserSession.user_id == self.id, UserSession.is_active == True
            )
            result = await session.execute(stmt)
            return result.scalars().all()
        
        else:
            # Fallback: try to access already loaded sessions
            try:
                return [session for session in self.sessions if session.is_valid]
            except Exception:
                return []

    async def terminate_all_sessions(
        self, except_session_id: uuid.UUID = None, session=None
    ):
        """Terminate all sessions except the specified one"""
        from sqlalchemy import update

        if session:
            # Use session to update sessions directly
            stmt = update(UserSession).where(
                UserSession.user_id == self.id, UserSession.is_active == True
            )
            if except_session_id:
                stmt = stmt.where(UserSession.id != except_session_id)

            stmt = stmt.values(is_active=False, terminated_at=func.now())
            await session.execute(stmt)
        else:
            # Fallback: try to access already loaded sessions
            try:
                for user_session in self.sessions:
                    if user_session.is_active and user_session.id != except_session_id:
                        user_session.terminate("user_logout_all")
            except Exception:
                pass

    async def get_concurrent_sessions_count(self, session=None) -> int:
        """Get count of active sessions"""
        active_sessions = await self.get_active_sessions(session)
        return len(active_sessions)

    def has_suspicious_activity(self) -> bool:
        """Check if user has any suspicious sessions"""
        return any(session.is_suspicious for session in self.get_active_sessions())

    def ban_immediate_other_device_attempts_from_user(self):
        pass


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    # --- Columns ---
    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )

    # Foreign key to users
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Token fields
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    expires_at: Mapped[DateTime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, index=True
    )
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Audit fields
    created_at: Mapped[DateTime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[DateTime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    absolute_expires_at: Mapped[DateTime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc) + timedelta(days=30),
    )
    usage_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_used_at: Mapped[DateTime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )

    # Optional metadata for tracking
    device_info: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)

    # --- Relationships ---
    user = relationship("User", back_populates="refresh_tokens")

    def __init__(self, **kwargs):
        """Initialize RefreshToken with automatic absolute_expires_at default"""
        if "absolute_expires_at" not in kwargs and "expires_at" in kwargs:
            # Default absolute expiration to 30 days from creation or same as expires_at
            kwargs["absolute_expires_at"] = kwargs["expires_at"]
        elif "absolute_expires_at" not in kwargs:
            # Fallback default
            kwargs["absolute_expires_at"] = datetime.now(timezone.utc) + timedelta(
                days=30
            )
        super().__init__(**kwargs)

    def __repr__(self):
        return f"<RefreshToken(id={self.id}, user_id={self.user_id}, expires_at={self.expires_at})>"

    def is_absolutely_expired(self) -> bool:
        """Check if refresh token has passed its absolute expiration"""
        return datetime.now(timezone.utc) > self.absolute_expires_at

    @property
    def is_expired(self) -> bool:
        """Check if token is expired"""
        expires = self.expires_at
        # If expires_at is missing, treat as expired
        if expires is None:
            return True
        # If stored datetime is naive, assume UTC
        if getattr(expires, "tzinfo", None) is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > expires

    @property
    def is_valid(self) -> bool:
        """Check if token is valid (not expired and not revoked)"""
        return (not self.is_expired) and (not self.revoked)

    def revoke(self):
        """Revoke the token"""
        self.revoked = True
        self.updated_at = datetime.now(timezone.utc)


class UserSession(Base):
    __tablename__ = "user_sessions"

    # --- Columns ---
    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )

    # Foreign key to users
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Session identification
    session_token: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )

    # Device and network information
    device_fingerprint: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )
    user_agent: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    user_agent_hash: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    ip_address: Mapped[Optional[str]] = mapped_column(
        String(45), nullable=True, index=True
    )

    # Geographic and network info (optional)
    country: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    isp: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    # Session status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_suspicious: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # Session timing
    created_at: Mapped[DateTime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), index=True
    )
    last_activity: Mapped[DateTime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), index=True
    )
    expires_at: Mapped[DateTime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, index=True
    )
    terminated_at: Mapped[Optional[DateTime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    # Security tracking
    login_method: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )  # password, 2fa, oauth
    risk_score: Mapped[int] = mapped_column(Integer, default=0)  # 0-100 risk score
    total_requests: Mapped[int] = mapped_column(Integer, default=0)

    # --- Relationships ---
    user = relationship("User", back_populates="sessions")

    def __repr__(self):
        return f"<UserSession(id={self.id}, user_id={self.user_id}, active={self.is_active})>"

    @property
    def is_expired(self) -> bool:
        """Check if session is expired"""
        expires = self.expires_at
        if expires is None:
            return True
        if getattr(expires, "tzinfo", None) is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > expires

    @property
    def is_valid(self) -> bool:
        """Check if session is valid"""
        return self.is_active and not self.is_expired and self.terminated_at is None

    @property
    def duration_minutes(self) -> int:
        """Get session duration in minutes"""
        if self.terminated_at:
            end_time = self.terminated_at
        else:
            end_time = datetime.now(timezone.utc)

        start_time = self.created_at
        if getattr(start_time, "tzinfo", None) is None:
            start_time = start_time.replace(tzinfo=timezone.utc)

        return int((end_time - start_time).total_seconds() / 60)

    def update_activity(self, ip_address: str = None):
        """Update last activity timestamp and optionally IP"""
        self.last_activity = datetime.now(timezone.utc)
        self.total_requests += 1
        if ip_address and ip_address != self.ip_address:
            # Log IP change but don't block
            self.risk_score = min(100, self.risk_score + 10)

    def terminate(self, reason: str = None):
        """Terminate the session"""
        self.is_active = False
        self.terminated_at = datetime.now(timezone.utc)

    def mark_suspicious(self, reason: str = None):
        """Mark session as suspicious"""
        self.is_suspicious = True
        self.risk_score = min(100, self.risk_score + 25)

    def extend_session(self, minutes: int = 30):
        """Extend session expiry"""
        self.expires_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)

    # --- Table Configuration for Performance ---
    __table_args__ = (
        # Composite indexes for common query patterns in hospital user sessions
        Index("idx_session_user_active", "user_id", "is_active"),
        Index("idx_session_device_user", "device_fingerprint", "user_id"),
        Index("idx_session_token_active", "session_token", "is_active"),
        Index("idx_session_ip_user", "ip_address", "user_id"),
        Index("idx_session_created_active", "created_at", "is_active"),
        Index("idx_session_suspicious", "is_suspicious", "risk_score"),
    )
