from sqlalchemy.orm import declarative_base
from sqlalchemy import TypeDecorator, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
import uuid as uuid_module


class UUID(TypeDecorator):
    """
    Platform-independent UUID type.

    Uses PostgreSQL's native UUID type when available,
    otherwise uses String(32) for SQLite storing as hex (no dashes).

    This ensures UUID comparisons work correctly in both dev (SQLite) and prod (PostgreSQL).
    """

    impl = String(32)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PGUUID(as_uuid=True))
        else:
            # SQLite: store as 32-char hex string (no dashes)
            return dialect.type_descriptor(String(32))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        elif dialect.name == "postgresql":
            # PostgreSQL: pass UUID object as-is
            return (
                value
                if isinstance(value, uuid_module.UUID)
                else uuid_module.UUID(value)
            )
        else:
            # SQLite: convert to hex string (no dashes)
            if isinstance(value, uuid_module.UUID):
                return value.hex
            elif isinstance(value, str):
                # Remove dashes if present
                return value.replace("-", "")
            return value

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        elif dialect.name == "postgresql":
            # PostgreSQL returns UUID object
            return (
                value
                if isinstance(value, uuid_module.UUID)
                else uuid_module.UUID(value)
            )
        else:
            # SQLite: convert hex string back to UUID object
            if isinstance(value, str) and len(value) == 32:
                return uuid_module.UUID(hex=value)
            elif isinstance(value, str):
                return uuid_module.UUID(value)
            return value


Base = declarative_base()
