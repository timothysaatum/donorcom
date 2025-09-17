"""Enhanced security device models

Revision ID: enhanced_device_security
Revises: 88bd785c0c06
Create Date: 2025-01-26 10:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "enhanced_device_security"
down_revision = "88bd785c0c06"
branch_labels = None
depends_on = None


def upgrade():
    # Create device_trust table
    op.create_table(
        "device_trust",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("device_fingerprint", sa.String(64), nullable=False, index=True),
        sa.Column("device_fingerprint_v2", sa.String(64), nullable=True, index=True),
        sa.Column("device_name", sa.String(100), nullable=True),
        sa.Column("device_type", sa.String(50), nullable=True),
        sa.Column("operating_system", sa.String(100), nullable=True),
        sa.Column("browser_name", sa.String(100), nullable=True),
        sa.Column("browser_version", sa.String(50), nullable=True),
        sa.Column("trust_score", sa.Integer, default=30, nullable=False),
        sa.Column("trust_level", sa.String(20), default="low", nullable=False),
        sa.Column("is_trusted", sa.Boolean, default=False, nullable=False),
        sa.Column("is_verified", sa.Boolean, default=False, nullable=False),
        sa.Column("is_registered", sa.Boolean, default=False, nullable=False),
        sa.Column("total_sessions", sa.Integer, default=0, nullable=False),
        sa.Column("successful_logins", sa.Integer, default=0, nullable=False),
        sa.Column("failed_attempts", sa.Integer, default=0, nullable=False),
        sa.Column("suspicious_activities", sa.Integer, default=0, nullable=False),
        sa.Column(
            "verification_challenges_passed", sa.Integer, default=0, nullable=False
        ),
        sa.Column(
            "verification_challenges_failed", sa.Integer, default=0, nullable=False
        ),
        sa.Column("risk_score", sa.Integer, default=30, nullable=False),
        sa.Column("risk_factors", sa.Text, nullable=True),
        sa.Column("first_seen_ip", sa.String(45), nullable=True, index=True),
        sa.Column("first_seen_country", sa.String(3), nullable=True),
        sa.Column("first_seen_city", sa.String(100), nullable=True),
        sa.Column("last_seen_ip", sa.String(45), nullable=True, index=True),
        sa.Column("last_seen_country", sa.String(3), nullable=True),
        sa.Column("last_seen_city", sa.String(100), nullable=True),
        sa.Column(
            "location_consistency_score", sa.Integer, default=100, nullable=False
        ),
        sa.Column("capabilities", sa.Text, nullable=True),  # JSON as TEXT for SQLite
        sa.Column("hardware_fingerprint", sa.String(64), nullable=True),
        sa.Column("verification_method", sa.String(50), nullable=True),
        sa.Column("verification_token", sa.String(255), nullable=True),
        sa.Column("verification_expires_at", sa.DateTime, nullable=True),
        sa.Column(
            "first_seen", sa.DateTime, server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "last_seen", sa.DateTime, server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "last_trust_update",
            sa.DateTime,
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("verified_at", sa.DateTime, nullable=True),
        sa.Column("registered_at", sa.DateTime, nullable=True),
        sa.Column("is_active", sa.Boolean, default=True, nullable=False),
        sa.Column("is_revoked", sa.Boolean, default=False, nullable=False),
        sa.Column("revoked_at", sa.DateTime, nullable=True),
        sa.Column("revoked_reason", sa.String(255), nullable=True),
    )

    # Create indexes for device_trust
    op.create_index(
        "ix_device_trust_user_fingerprint",
        "device_trust",
        ["user_id", "device_fingerprint"],
    )
    op.create_index("ix_device_trust_trust_level", "device_trust", ["trust_level"])
    op.create_index("ix_device_trust_last_seen", "device_trust", ["last_seen"])
    op.create_index("ix_device_trust_risk_score", "device_trust", ["risk_score"])

    # Create device_registrations table
    op.create_table(
        "device_registrations",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "device_trust_id",
            sa.String(36),
            sa.ForeignKey("device_trust.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "registration_token",
            sa.String(255),
            unique=True,
            nullable=False,
            index=True,
        ),
        sa.Column("device_fingerprint", sa.String(64), nullable=False, index=True),
        sa.Column("challenge_id", sa.String(255), nullable=False),
        sa.Column("challenge_data", sa.Text, nullable=False),
        sa.Column("challenge_response", sa.Text, nullable=True),
        sa.Column("verification_method", sa.String(50), nullable=False),
        sa.Column("device_name", sa.String(100), nullable=True),
        sa.Column("device_data", sa.Text, nullable=False),  # JSON as TEXT for SQLite
        sa.Column("capabilities", sa.Text, nullable=True),  # JSON as TEXT for SQLite
        sa.Column("status", sa.String(20), default="pending", nullable=False),
        sa.Column("attempts", sa.Integer, default=0, nullable=False),
        sa.Column("max_attempts", sa.Integer, default=3, nullable=False),
        sa.Column("registration_ip", sa.String(45), nullable=True),
        sa.Column("registration_country", sa.String(3), nullable=True),
        sa.Column("registration_city", sa.String(100), nullable=True),
        sa.Column(
            "initiated_at", sa.DateTime, server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("completed_at", sa.DateTime, nullable=True),
        sa.Column("last_attempt_at", sa.DateTime, nullable=True),
    )

    # Create device_security_events table
    op.create_table(
        "device_security_events",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "device_trust_id",
            sa.String(36),
            sa.ForeignKey("device_trust.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("user_sessions.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
        sa.Column("event_type", sa.String(50), nullable=False, index=True),
        sa.Column("event_category", sa.String(20), nullable=False, index=True),
        sa.Column("severity", sa.String(10), nullable=False, index=True),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("event_data", sa.Text, nullable=True),  # JSON as TEXT for SQLite
        sa.Column("risk_score_impact", sa.Integer, default=0, nullable=False),
        sa.Column("trust_score_impact", sa.Integer, default=0, nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True, index=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("country", sa.String(3), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime,
            server_default=sa.func.now(),
            nullable=False,
            index=True,
        ),
        sa.Column("resolved_at", sa.DateTime, nullable=True),
        sa.Column("is_resolved", sa.Boolean, default=False, nullable=False),
        sa.Column("resolution_action", sa.String(255), nullable=True),
    )

    # Create indexes for device_security_events
    op.create_index(
        "ix_device_security_events_user_occurred",
        "device_security_events",
        ["user_id", "occurred_at"],
    )
    op.create_index(
        "ix_device_security_events_type_severity",
        "device_security_events",
        ["event_type", "severity"],
    )
    op.create_index(
        "ix_device_security_events_category",
        "device_security_events",
        ["event_category"],
    )


def downgrade():
    # Drop indexes first
    op.drop_index("ix_device_security_events_category")
    op.drop_index("ix_device_security_events_type_severity")
    op.drop_index("ix_device_security_events_user_occurred")
    op.drop_index("ix_device_trust_risk_score")
    op.drop_index("ix_device_trust_last_seen")
    op.drop_index("ix_device_trust_trust_level")
    op.drop_index("ix_device_trust_user_fingerprint")

    # Drop tables
    op.drop_table("device_security_events")
    op.drop_table("device_registrations")
    op.drop_table("device_trust")
