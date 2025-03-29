from sqlalchemy.orm import Session
from app.database import SessionLocal

def get_db():
    """Dependency that provides a DB session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()