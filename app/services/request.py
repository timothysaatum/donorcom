from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from sqlalchemy import and_, or_
from fastapi import HTTPException
from uuid import UUID, uuid4
from typing import List, Optional, Tuple
import asyncio
from app.models.request import BloodRequest, RequestStatus
from app.models.health_facility import Facility
from app.schemas.request import (
    BloodRequestCreate, 
    BloodRequestUpdate, 
    BloodRequestGroupResponse,
    BloodRequestBulkCreateResponse
)
import logging

logger = logging.getLogger(__name__)


class BloodRequestService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_bulk_request(self, data: BloodRequestCreate, requester_id: UUID) -> BloodRequestBulkCreateResponse:
        """Create requests to multiple facilities with intelligent grouping"""
        
        # Validate facilities exist
        await self._validate_facilities(data.facility_ids)
        
        # Generate group ID for related requests
        request_group_id = uuid4()
        
        # Create requests for each facility
        created_requests = []
        
        try:
            for idx, facility_id in enumerate(data.facility_ids):
                is_master = idx == 0  # First request is the master
                
                new_request = BloodRequest(
                    requester_id=requester_id,
                    facility_id=facility_id,
                    request_group_id=request_group_id,
                    is_master_request=is_master,
                    blood_type=data.blood_type,
                    blood_product=data.blood_product,
                    quantity_requested=data.quantity_requested,
                    notes=data.notes,
                    status=RequestStatus.pending
                )
                
                self.db.add(new_request)
                created_requests.append(new_request)
            
            await self.db.commit()
            
            # Refresh all requests to get IDs
            for request in created_requests:
                await self.db.refresh(request)
            
            logger.info(f"Created {len(created_requests)} blood requests with group ID: {request_group_id}")
            
            return BloodRequestBulkCreateResponse(
                request_group_id=request_group_id,
                total_requests_created=len(created_requests),
                requests=created_requests,
                message=f"Successfully created requests to {len(created_requests)} facilities"
            )
            
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error creating bulk requests: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to create blood requests")

    async def _validate_facilities(self, facility_ids: List[UUID]) -> None:
        """Validate that all facilities exist"""
        result = await self.db.execute(
            select(Facility.id).where(Facility.id.in_(facility_ids))
        )
        existing_ids = {row[0] for row in result.fetchall()}
        
        missing_ids = set(facility_ids) - existing_ids
        if missing_ids:
            raise HTTPException(
                status_code=404, 
                detail=f"Facilities not found: {list(missing_ids)}"
            )

    async def get_request(self, request_id: UUID) -> Optional[BloodRequest]:
        """Get a single request by ID"""
        result = await self.db.execute(
            select(BloodRequest)
            .options(joinedload(BloodRequest.facility))
            .where(BloodRequest.id == request_id)
        )
        return result.scalar_one_or_none()

    async def get_request_group(self, request_group_id: UUID) -> Optional[BloodRequestGroupResponse]:
        """Get all requests in a group with summary information"""
        result = await self.db.execute(
            select(BloodRequest)
            .options(joinedload(BloodRequest.facility))
            .where(BloodRequest.request_group_id == request_group_id)
            .order_by(BloodRequest.is_master_request.desc(), BloodRequest.created_at)
        )
        requests = result.scalars().all()
        
        if not requests:
            return None
        
        master_request = next((r for r in requests if r.is_master_request), requests[0])
        related_requests = [r for r in requests if not r.is_master_request]
        
        # Calculate status counts
        status_counts = {
            'pending': sum(1 for r in requests if r.status == RequestStatus.pending),
            'approved': sum(1 for r in requests if r.status == RequestStatus.approved),
            'rejected': sum(1 for r in requests if r.status == RequestStatus.rejected),
            'fulfilled': sum(1 for r in requests if r.status == RequestStatus.fulfilled),
            'cancelled': sum(1 for r in requests if r.status == RequestStatus.cancelled)
        }
        
        return BloodRequestGroupResponse(
            request_group_id=request_group_id,
            blood_type=master_request.blood_type,
            blood_product=master_request.blood_product,
            quantity_requested=master_request.quantity_requested,
            notes=master_request.notes,
            master_request=master_request,
            related_requests=related_requests,
            total_facilities=len(requests),
            pending_count=status_counts['pending'],
            approved_count=status_counts['approved'],
            rejected_count=status_counts['rejected'],
            fulfilled_count=status_counts['fulfilled'],
            cancelled_count=status_counts['cancelled'],
            created_at=master_request.created_at,
            updated_at=max(r.updated_at for r in requests)
        )

    async def update_request(self, request_id: UUID, data: BloodRequestUpdate) -> BloodRequest:
        """Update a request and handle intelligent cancellation"""
        request = await self.get_request(request_id)
        if not request:
            raise HTTPException(status_code=404, detail="Blood request not found")
        
        # Check if status is being changed to approved/fulfilled
        old_status = request.status
        new_status = data.status if data.status is not None else old_status
        
        # Update request fields
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(request, field, value)
        
        await self.db.commit()
        await self.db.refresh(request)
        
        # Handle intelligent cancellation if request is approved/fulfilled
        if (old_status in [RequestStatus.pending, RequestStatus.approved] and 
            new_status in [RequestStatus.approved, RequestStatus.fulfilled]):
            
            # Cancel related requests in the same group
            await self._cancel_related_requests(request.request_group_id, request.id)
        
        return request

    async def _cancel_related_requests(self, request_group_id: UUID, exclude_request_id: UUID) -> None:
        """Cancel all related requests in a group except the specified one"""
        try:
            # Get all pending/approved requests in the group except the current one
            result = await self.db.execute(
                select(BloodRequest).where(
                    and_(
                        BloodRequest.request_group_id == request_group_id,
                        BloodRequest.id != exclude_request_id,
                        BloodRequest.status.in_([RequestStatus.pending, RequestStatus.approved])
                    )
                )
            )
            related_requests = result.scalars().all()
            
            # Cancel each related request
            for req in related_requests:
                req.status = RequestStatus.cancelled
                req.cancellation_reason = "Automatically cancelled - request fulfilled by another facility"
            
            await self.db.commit()
            
            logger.info(f"Cancelled {len(related_requests)} related requests for group {request_group_id}")
            
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error cancelling related requests: {str(e)}")
            raise

    async def delete_request(self, request_id: UUID) -> None:
        """Delete a request (only if pending)"""
        request = await self.get_request(request_id)
        if not request:
            raise HTTPException(status_code=404, detail="Blood request not found")
        
        if request.status not in [RequestStatus.pending, RequestStatus.cancelled]:
            raise HTTPException(
                status_code=400, 
                detail="Cannot delete request that is not pending or cancelled"
            )
        
        await self.db.delete(request)
        await self.db.commit()

    async def list_requests_by_user(self, user_id: UUID) -> List[BloodRequest]:
        """List all requests by user"""
        result = await self.db.execute(
            select(BloodRequest)
            .options(joinedload(BloodRequest.facility))
            .where(BloodRequest.requester_id == user_id)
            .order_by(BloodRequest.created_at.desc())
        )
        return result.scalars().all()

    async def list_request_groups_by_user(self, user_id: UUID) -> List[BloodRequestGroupResponse]:
        """List request groups by user (more efficient for multi-facility requests)"""
        # Get all group IDs for the user
        result = await self.db.execute(
            select(BloodRequest.request_group_id)
            .where(BloodRequest.requester_id == user_id)
            .distinct()
            .order_by(BloodRequest.request_group_id.desc())
        )
        group_ids = [row[0] for row in result.fetchall()]
        
        # Get group details for each group
        groups = []
        for group_id in group_ids:
            group = await self.get_request_group(group_id)
            if group:
                groups.append(group)
        
        return groups

    async def list_requests_by_facility(self, facility_id: UUID) -> List[BloodRequest]:
        """List all requests for a specific facility"""
        result = await self.db.execute(
            select(BloodRequest)
            .options(joinedload(BloodRequest.requester))
            .where(BloodRequest.facility_id == facility_id)
            .order_by(BloodRequest.created_at.desc())
        )
        return result.scalars().all()

    async def list_requests_by_status(self, status: RequestStatus) -> List[BloodRequest]:
        """List requests by status"""
        result = await self.db.execute(
            select(BloodRequest)
            .options(joinedload(BloodRequest.facility))
            .where(BloodRequest.status == status)
            .order_by(BloodRequest.created_at.desc())
        )
        return result.scalars().all()

    async def get_request_statistics(self, user_id: UUID) -> dict:
        """Get request statistics for a user"""
        result = await self.db.execute(
            select(BloodRequest.status, BloodRequest.request_group_id)
            .where(BloodRequest.requester_id == user_id)
        )
        requests = result.fetchall()
        
        # Count unique groups by status
        groups_by_status = {}
        for status, group_id in requests:
            if status not in groups_by_status:
                groups_by_status[status] = set()
            groups_by_status[status].add(group_id)
        
        return {
            'total_request_groups': len(set(group_id for _, group_id in requests)),
            'total_individual_requests': len(requests),
            'pending_groups': len(groups_by_status.get(RequestStatus.pending, set())),
            'approved_groups': len(groups_by_status.get(RequestStatus.approved, set())),
            'fulfilled_groups': len(groups_by_status.get(RequestStatus.fulfilled, set())),
            'rejected_groups': len(groups_by_status.get(RequestStatus.rejected, set())),
            'cancelled_groups': len(groups_by_status.get(RequestStatus.cancelled, set()))
        }