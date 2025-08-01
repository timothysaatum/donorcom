from typing import List, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.models.tracking_model import TrackState#, TrackStateStatus
from app.models.distribution import BloodDistribution
# from app.models.user import User
from app.schemas.tracking_schema import TrackStateCreate#, TrackStateResponse
# from datetime import datetime


class TrackStateService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_track_state(self, track_data: TrackStateCreate, created_by_id: Optional[UUID] = None) -> TrackState:
        """Create a new tracking state entry"""
        db_track = TrackState(
            blood_distribution_id=track_data.blood_distribution_id,
            status=track_data.status,
            location=track_data.location,
            notes=track_data.notes,
            created_by_id=created_by_id
        )
        
        self.db.add(db_track)
        await self.db.commit()
        await self.db.refresh(db_track)
        return db_track


    async def get_track_state(self, track_state_id: UUID) -> Optional[TrackState]:
        """Get a single tracking state by ID"""
        result = await self.db.execute(
            select(TrackState).where(TrackState.id == track_state_id)
        )
        return result.scalar_one_or_none()


    async def get_track_states_for_distribution(self, tracking_number: str) -> List[TrackState]:
        """Get all tracking states for a specific distribution using tracking number"""
        result = await self.db.execute(
            select(TrackState)
            .join(TrackState.blood_distribution)
            .where(BloodDistribution.tracking_number == tracking_number)
            .options(selectinload(TrackState.created_by))  # Optional: eager-load related user
            .order_by(TrackState.timestamp.desc())
        )
        return result.scalars().all()


    async def get_latest_state_for_distribution(self, distribution_id: UUID) -> Optional[TrackState]:
        """Get the most recent tracking state for a distribution"""
        result = await self.db.execute(
            select(TrackState)
            .where(TrackState.blood_distribution_id == distribution_id)
            .order_by(TrackState.timestamp.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


    async def update_track_state(self, track_state_id: UUID, update_data: dict) -> Optional[TrackState]:
        """Update a tracking state"""
        track_state = await self.get_track_state(track_state_id)
        if not track_state:
            return None
            
        for field, value in update_data.items():
            setattr(track_state, field, value)
            
        await self.db.commit()
        await self.db.refresh(track_state)
        return track_state


    async def delete_track_state(self, track_state_id: UUID) -> bool:
        """Delete a tracking state"""
        track_state = await self.get_track_state(track_state_id)
        if not track_state:
            return False
            
        await self.db.delete(track_state)
        await self.db.commit()
        return True