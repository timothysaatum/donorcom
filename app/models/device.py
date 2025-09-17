"""
Device Trust and Registration Models

This module defines the database models for device identification,
trust management, and proof of ownership.
"""

import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from sqlalchemy import String, Boolean, DateTime, Integer, Text, JSON, Index
from sqlalchemy.dialects.postgresql import UUID as PGUUID, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import ForeignKey, func

from app.db.base import Base


class DeviceTrust(Base):
    """Device trust and identification model"""

    __tablename__ = "device_trust"

    # Primary identification
    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )

    # User association
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Device identification
    device_fingerprint: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    device_fingerprint_v2: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True  # For future fingerprint upgrades
    )

    # Device information
    device_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    device_type: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )  # mobile, desktop, tablet
    operating_system: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    browser_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    browser_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Trust metrics
    trust_score: Mapped[int] = mapped_column(
        Integer, default=30, nullable=False
    )  # 0-100
    trust_level: Mapped[str] = mapped_column(
        String(20),
        default="low",
        nullable=False,  # untrusted, low, medium, high, verified
    )
    is_trusted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_registered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Usage statistics
    total_sessions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    successful_logins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    suspicious_activities: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )

    # Verification statistics
    verification_challenges_passed: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    verification_challenges_failed: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )

    # Risk assessment
    risk_score: Mapped[int] = mapped_column(
        Integer, default=30, nullable=False
    )  # 0-100
    risk_factors: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # JSON array of risk factors

    # Location and network
    first_seen_ip: Mapped[Optional[str]] = mapped_column(
        String(45), nullable=True, index=True
    )
    first_seen_country: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    first_seen_city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    last_seen_ip: Mapped[Optional[str]] = mapped_column(
        String(45), nullable=True, index=True
    )
    last_seen_country: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    last_seen_city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    location_consistency_score: Mapped[int] = mapped_column(
        Integer, default=100, nullable=False
    )

    # Device capabilities (stored as JSON)
    capabilities: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    hardware_fingerprint: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )

    # Verification and ownership
    verification_method: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )
    verification_token: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    verification_expires_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    # Timing
    first_seen: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    last_trust_update: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    verified_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    registered_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    # Status management
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    revoked_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Relationships
    user = relationship("User", back_populates="trusted_devices")
    registrations = relationship(
        "DeviceRegistration",
        back_populates="device_trust",
        cascade="all, delete-orphan",
    )
    security_events = relationship(
        "DeviceSecurityEvent",
        back_populates="device_trust",
        cascade="all, delete-orphan",
    )

    # Indexes for performance
    __table_args__ = (
        Index("ix_device_trust_user_fingerprint", "user_id", "device_fingerprint"),
        Index("ix_device_trust_trust_level", "trust_level"),
        Index("ix_device_trust_last_seen", "last_seen"),
        Index("ix_device_trust_risk_score", "risk_score"),
    )

    def __repr__(self):
        return f"<DeviceTrust(id={self.id}, user_id={self.user_id}, trust_level={self.trust_level})>"

    @property
    def is_expired_verification(self) -> bool:
        """Check if verification token is expired"""
        if not self.verification_expires_at:
            return True
        return datetime.now(timezone.utc) > self.verification_expires_at

    @property
    def days_since_first_seen(self) -> int:
        """Get days since device was first seen"""
        return (datetime.now(timezone.utc) - self.first_seen).days

    @property
    def success_rate(self) -> float:
        """Calculate login success rate"""
        total = self.successful_logins + self.failed_attempts
        if total == 0:
            return 0.0
        return self.successful_logins / total

    def update_trust_score(self) -> int:
        """Recalculate and update trust score"""
        from app.utils.device_identification import AdvancedDeviceIdentifier
        from app.utils.device_identification import DeviceTrustData

        # Convert to DeviceTrustData for calculation
        trust_data = DeviceTrustData(
            device_id=self.device_fingerprint,
            trust_score=self.trust_score,
            registration_time=self.first_seen,
            last_seen=self.last_seen,
            total_sessions=self.total_sessions,
            successful_logins=self.successful_logins,
            failed_attempts=self.failed_attempts,
            suspicious_activities=self.suspicious_activities,
            verification_challenges_passed=self.verification_challenges_passed,
            verification_challenges_failed=self.verification_challenges_failed,
            is_trusted=self.is_trusted,
            trust_level=self.trust_level,
            location_consistency_score=self.location_consistency_score,
        )

        new_score = AdvancedDeviceIdentifier.calculate_trust_score(trust_data)
        self.trust_score = new_score
        self.trust_level = AdvancedDeviceIdentifier.determine_trust_level(new_score)
        self.is_trusted = new_score >= 50
        self.last_trust_update = datetime.now(timezone.utc)

        return new_score

    def record_successful_login(
        self, ip_address: str = None, location_data: dict = None
    ):
        """Record a successful login"""
        self.successful_logins += 1
        self.total_sessions += 1
        self.last_seen = datetime.now(timezone.utc)

        if ip_address:
            self.last_seen_ip = ip_address

        if location_data:
            self.last_seen_country = location_data.get("country")
            self.last_seen_city = location_data.get("city")

        self.update_trust_score()

    def record_failed_attempt(self, ip_address: str = None, suspicious: bool = False):
        """Record a failed login attempt"""
        self.failed_attempts += 1
        self.last_seen = datetime.now(timezone.utc)

        if suspicious:
            self.suspicious_activities += 1

        if ip_address:
            self.last_seen_ip = ip_address

        self.update_trust_score()

    def revoke_device(self, reason: str = "user_request"):
        """Revoke device access"""
        self.is_revoked = True
        self.is_active = False
        self.revoked_at = datetime.now(timezone.utc)
        self.revoked_reason = reason
        self.trust_score = 0
        self.trust_level = "untrusted"
        self.is_trusted = False


class DeviceRegistration(Base):
    """Device registration and verification process tracking"""

    __tablename__ = "device_registrations"

    # Primary identification
    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )

    # Associations
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    device_trust_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("device_trust.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Registration details
    registration_token: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    device_fingerprint: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )

    # Challenge and verification
    challenge_id: Mapped[str] = mapped_column(String(255), nullable=False)
    challenge_data: Mapped[str] = mapped_column(Text, nullable=False)
    challenge_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verification_method: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # email, sms, app, hardware

    # Device information
    device_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    device_data: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    capabilities: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Status tracking
    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        nullable=False,  # pending, verified, failed, expired
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)

    # Network information
    registration_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    registration_country: Mapped[Optional[str]] = mapped_column(
        String(3), nullable=True
    )
    registration_city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Timing
    initiated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    # Relationships
    user = relationship("User")
    device_trust = relationship("DeviceTrust", back_populates="registrations")

    def __repr__(self):
        return f"<DeviceRegistration(id={self.id}, status={self.status}, user_id={self.user_id})>"

    @property
    def is_expired(self) -> bool:
        """Check if registration has expired"""
        return datetime.now(timezone.utc) > self.expires_at

    @property
    def is_completed(self) -> bool:
        """Check if registration is completed"""
        return self.status in ["verified", "failed"]

    @property
    def attempts_remaining(self) -> int:
        """Get remaining verification attempts"""
        return max(0, self.max_attempts - self.attempts)

    def record_attempt(self, success: bool, response: str = None):
        """Record a verification attempt"""
        self.attempts += 1
        self.last_attempt_at = datetime.now(timezone.utc)

        if response:
            self.challenge_response = response

        if success:
            self.status = "verified"
            self.completed_at = datetime.now(timezone.utc)
        elif self.attempts >= self.max_attempts:
            self.status = "failed"
            self.completed_at = datetime.now(timezone.utc)


class DeviceSecurityEvent(Base):
    """Security events related to device activity"""

    __tablename__ = "device_security_events"

    # Primary identification
    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )

    # Associations
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    device_trust_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("device_trust.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("user_sessions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Event information
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    event_category: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True
    )  # security, trust, verification
    severity: Mapped[str] = mapped_column(
        String(10), nullable=False, index=True
    )  # low, medium, high, critical
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Event data
    event_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    risk_score_impact: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    trust_score_impact: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Network information
    ip_address: Mapped[Optional[str]] = mapped_column(
        String(45), nullable=True, index=True
    )
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Timing
    occurred_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    # Status
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    resolution_action: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Relationships
    user = relationship("User")
    device_trust = relationship("DeviceTrust", back_populates="security_events")
    session = relationship("UserSession")

    # Indexes
    __table_args__ = (
        Index("ix_device_security_events_user_occurred", "user_id", "occurred_at"),
        Index("ix_device_security_events_type_severity", "event_type", "severity"),
        Index("ix_device_security_events_category", "event_category"),
    )

    def __repr__(self):
        return f"<DeviceSecurityEvent(id={self.id}, type={self.event_type}, severity={self.severity})>"

    @classmethod
    def create_security_event(
        cls,
        user_id: uuid.UUID,
        event_type: str,
        description: str,
        severity: str = "medium",
        category: str = "security",
        device_trust_id: uuid.UUID = None,
        session_id: uuid.UUID = None,
        event_data: dict = None,
        risk_impact: int = 0,
        trust_impact: int = 0,
        ip_address: str = None,
        user_agent: str = None,
    ) -> "DeviceSecurityEvent":
        """Create a new security event"""

        return cls(
            user_id=user_id,
            device_trust_id=device_trust_id,
            session_id=session_id,
            event_type=event_type,
            event_category=category,
            severity=severity,
            description=description,
            event_data=event_data or {},
            risk_score_impact=risk_impact,
            trust_score_impact=trust_impact,
            ip_address=ip_address,
            user_agent=user_agent,
        )
