from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from fastapi import HTTPException
from uuid import UUID
from typing import List, Optional
from app.models.request import BloodRequest, RequestStatus
from app.schemas.request import BloodRequestCreate, BloodRequestUpdate



class BloodRequestService:
    def __init__(self, db: AsyncSession):
        self.db = db


    async def create_request(self, data: BloodRequestCreate, requester_id: UUID) -> BloodRequest:
        new_request = BloodRequest(**data.model_dump(), requester_id=requester_id)
        self.db.add(new_request)
        await self.db.commit()
        await self.db.refresh(new_request)
        return new_request


    async def get_request(self, request_id: UUID) -> Optional[BloodRequest]:
        result = await self.db.execute(
            select(BloodRequest).where(BloodRequest.id == request_id)
        )
        return result.scalar_one_or_none()


    async def update_request(self, request_id: UUID, data: BloodRequestUpdate) -> BloodRequest:
        request = await self.get_request(request_id)
        if not request:
            raise HTTPException(status_code=404, detail="Blood request not found")
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(request, field, value)
        await self.db.commit()
        await self.db.refresh(request)
        return request


    async def delete_request(self, request_id: UUID) -> None:
        request = await self.get_request(request_id)
        if not request:
            raise HTTPException(status_code=404, detail="Blood request not found")
        await self.db.delete(request)
        await self.db.commit()


    async def list_requests_by_user(self, user_id: UUID) -> List[BloodRequest]:
        result = await self.db.execute(
            select(BloodRequest)
            .where(BloodRequest.requester_id == user_id)
            .order_by(BloodRequest.created_at.desc())
        )
        return result.scalars().all()


    async def list_requests_by_status(self, status: RequestStatus) -> List[BloodRequest]:
        result = await self.db.execute(
            select(BloodRequest)
            .where(BloodRequest.status == status)
            .order_by(BloodRequest.created_at.desc())
        )
        return result.scalars().all()