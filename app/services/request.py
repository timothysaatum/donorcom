from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import and_, or_, func, text
from fastapi import HTTPException
from uuid import UUID, uuid4
from typing import List, Optional, Dict, Any
from math import ceil
from app.models.request import BloodRequest, RequestStatus, ProcessingStatus
from app.models.health_facility import Facility
from app.models.user import User
from app.schemas.request import (
    BloodRequestCreate, 
    BloodRequestUpdate, 
    BloodRequestGroupResponse,
    BloodRequestBulkCreateResponse,
    BloodRequestResponse
)
from app.schemas.inventory import PaginatedResponse
import logging
import time
from functools import wraps

logger = logging.getLogger(__name__)


def performance_monitor(func):
    """Decorator to monitor function performance"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = await func(*args, **kwargs)
            execution_time = time.time() - start_time
            if execution_time > 0.1:  # Log only if > 100ms
                logger.info(f"{func.__name__} executed in {execution_time:.3f} seconds")
            return result
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"{func.__name__} failed after {execution_time:.3f} seconds: {e}")
            raise
    return wrapper


class BloodRequestService:
    def __init__(self, db: AsyncSession):
        self.db = db
        # Simple in-memory cache for facility names (cleared on service restart)
        self._facility_name_cache: Dict[str, str] = {}

    def _get_empty_paginated_response(self, page: int, page_size: int) -> PaginatedResponse[BloodRequestResponse]:
        """Reusable empty response generator"""
        return PaginatedResponse(
            items=[],
            total_items=0,
            total_pages=0,
            current_page=page,
            page_size=page_size,
            has_next=False,
            has_prev=False
        )

    def _build_facility_query_conditions(self, option: str, facility_id: UUID, user_id: UUID) -> Optional[Any]:
        """Build query conditions efficiently"""
        if option == "received":
            return and_(
                BloodRequest.facility_id == facility_id,
                BloodRequest.requester_id != user_id
            )
        elif option == "sent":
            return and_(
                BloodRequest.requester_id == user_id,
                BloodRequest.option == "sent"
            )
        else:  # "all"
            return or_(
                and_(BloodRequest.facility_id == facility_id, BloodRequest.requester_id != user_id),
                and_(BloodRequest.requester_id == user_id, BloodRequest.option == "sent")
            )

    def _validate_and_add_status_filters(self, conditions: List, request_status: Optional[str], 
                                       processing_status: Optional[str]) -> bool:
        """Validate and add status filters. Returns False if invalid status provided."""
        if request_status:
            try:
                status_enum = RequestStatus(request_status)
                conditions.append(BloodRequest.request_status == status_enum)
            except ValueError:
                return False

        if processing_status:
            try:
                processing_enum = ProcessingStatus(processing_status)
                conditions.append(BloodRequest.processing_status == processing_enum)
            except ValueError:
                return False
        
        return True

    def _fast_convert_to_response(self, request: BloodRequest) -> BloodRequestResponse:
        """Optimized conversion with minimal overhead"""
        
        # Fast facility name resolution with caching
        receiving_facility_name = "Unknown Facility"
        if request.facility and request.facility.facility_name:
            facility_key = str(request.facility_id)
            if facility_key in self._facility_name_cache:
                receiving_facility_name = self._facility_name_cache[facility_key]
            else:
                name = request.facility.facility_name.strip()
                receiving_facility_name = name if name else "Unknown Facility"
                self._facility_name_cache[facility_key] = receiving_facility_name

        # Fast requester facility name resolution
        requester_facility_name = None
        if request.requester:
            if request.requester.facility and request.requester.facility.facility_name:
                name = request.requester.facility.facility_name.strip()
                requester_facility_name = name if name else None
            elif request.requester.work_facility and request.requester.work_facility.facility_name:
                name = request.requester.work_facility.facility_name.strip()
                requester_facility_name = name if name else None

        # Fast requester name resolution
        requester_name = None
        if request.requester:
            first = request.requester.first_name or ""
            last = request.requester.last_name or ""
            if first or last:
                requester_name = f"{first} {last}".strip()

        return BloodRequestResponse(
            id=request.id,
            requester_id=request.requester_id,
            facility_id=request.facility_id,
            receiving_facility_name=receiving_facility_name,
            request_group_id=request.request_group_id,
            blood_type=request.blood_type,
            blood_product=request.blood_product,
            quantity_requested=request.quantity_requested,
            request_status=request.request_status,
            processing_status=request.processing_status,
            notes=request.notes,
            priority=request.priority,
            cancellation_reason=request.cancellation_reason,
            requester_facility_name=requester_facility_name,
            requester_name=requester_name,
            created_at=request.created_at,
            updated_at=request.updated_at
        )

    @performance_monitor
    async def create_bulk_request(self, data: BloodRequestCreate, requester_id: UUID) -> BloodRequestBulkCreateResponse:
        """Create requests to multiple facilities with intelligent grouping - OPTIMIZED"""

        # OPTIMIZATION: Use selectinload for better performance with optional relationships
        requester_result = await self.db.execute(
            select(User)
            .options(
                selectinload(User.facility),
                selectinload(User.work_facility)
            )
            .where(User.id == requester_id)
        )
        requester = requester_result.scalar_one_or_none()
    
        if not requester:
            raise HTTPException(status_code=404, detail="Requester not found")
    
        # Determine requester's facility
        requester_facility_id = None
        if requester.facility:
            requester_facility_id = requester.facility.id
        elif requester.work_facility:
            requester_facility_id = requester.work_facility.id
    
        # Filter out the requester's own facility from the request
        if requester_facility_id:
            original_count = len(data.facility_ids)
            data.facility_ids = [fid for fid in data.facility_ids if fid != requester_facility_id]
        
            if len(data.facility_ids) != original_count:
                logger.warning(f"Removed requester's own facility from request list. Original: {original_count}, After: {len(data.facility_ids)}")
    
        if not data.facility_ids:
            raise HTTPException(
                status_code=400, 
                detail="Cannot send requests to your own facility. Please select other facilities."
            )

        # Validate facilities exist
        await self._validate_facilities(data.facility_ids)

        # Generate group ID for related requests
        request_group_id = uuid4()

        # Create requests for each facility
        created_requests = []

        try:
            for idx, facility_id in enumerate(data.facility_ids):
                is_master = idx == 0

                new_request = BloodRequest(
                    requester_id=requester_id,
                    facility_id=facility_id,
                    request_group_id=request_group_id,
                    is_master_request=is_master,
                    blood_type=data.blood_type,
                    blood_product=data.blood_product,
                    quantity_requested=data.quantity_requested,
                    notes=data.notes,
                    request_status=RequestStatus.pending,
                    priority=data.priority
                )
            
                self.db.add(new_request)
                created_requests.append(new_request)
        
            await self.db.commit()

            # OPTIMIZATION: Single query to load all relationships instead of N queries
            request_ids = [req.id for req in created_requests]
            result = await self.db.execute(
                select(BloodRequest)
                .options(
                    selectinload(BloodRequest.facility),
                    selectinload(BloodRequest.requester).selectinload(User.facility),
                    selectinload(BloodRequest.requester).selectinload(User.work_facility)
                )
                .where(BloodRequest.id.in_(request_ids))
            )
            refreshed_requests = result.scalars().all()
        
            # Convert to response models with optimized conversion
            response_requests = [
                self._fast_convert_to_response(request) 
                for request in refreshed_requests
            ]
        
            logger.info(f"Created {len(created_requests)} blood requests with group ID: {request_group_id}")
        
            return BloodRequestBulkCreateResponse(
                request_group_id=request_group_id,
                total_requests_created=len(created_requests),
                requests=response_requests,
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

    async def get_request(self, request_id: UUID):
        result = await self.db.execute(
            select(BloodRequest)
            .options(
                selectinload(BloodRequest.requester).selectinload(User.facility),
                selectinload(BloodRequest.requester).selectinload(User.work_facility),
                selectinload(BloodRequest.facility)
            )
            .where(BloodRequest.id == request_id)
        )
        return result.scalar_one_or_none()

    @performance_monitor
    async def get_request_group(self, request_group_id: UUID) -> Optional[BloodRequestGroupResponse]:
        """Get all requests in a group with summary information - OPTIMIZED"""
        result = await self.db.execute(
            select(BloodRequest)
            .options(selectinload(BloodRequest.facility))
            .where(BloodRequest.request_group_id == request_group_id)
            .order_by(BloodRequest.is_master_request.desc(), BloodRequest.created_at)
        )
        requests = result.scalars().all()

        if not requests:
            return None

        master_request = next((r for r in requests if r.is_master_request), requests[0])
        related_requests = [r for r in requests if not r.is_master_request]
        
        if not master_request:
            raise HTTPException(status_code=404, detail="Master request not found in group")
        
        # OPTIMIZATION: Count statuses in single pass instead of multiple sum() calls
        status_counts = {'pending': 0, 'accepted': 0, 'rejected': 0, 'cancelled': 0}
        for r in requests:
            if r.request_status in status_counts:
                status_counts[r.request_status.value] += 1
    
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
            accepted_count=status_counts['accepted'],
            rejected_count=status_counts['rejected'],
            cancelled_count=status_counts['cancelled'],
            created_at=master_request.created_at,
            updated_at=max(r.updated_at for r in requests)
        )

    async def update_request(self, request_id: UUID, data: BloodRequestUpdate) -> BloodRequest:
        """Update a request and handle intelligent cancellation"""
        request = await self.get_request(request_id)
        if not request:
            raise HTTPException(status_code=404, detail="Blood request not found")
    
        # Check if status is being changed to accepted
        old_status = request.request_status
        new_status = data.request_status if data.request_status is not None else old_status
    
        # Update request fields
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(request, field, value)
    
        await self.db.commit()
        await self.db.refresh(request)
    
        # Handle intelligent cancellation if request is accepted
        if (old_status in [RequestStatus.pending] and 
            new_status == RequestStatus.accepted):
        
            # Cancel related requests in the same group
            await self._cancel_related_requests(request.request_group_id, request.id)
    
        return request

    async def _cancel_related_requests(self, request_group_id: UUID, exclude_request_id: UUID) -> None:
        """Cancel all related requests in a group except the specified one"""
        try:
            # OPTIMIZATION: Update in bulk instead of individual updates
            await self.db.execute(
                text("""
                UPDATE blood_requests 
                SET request_status = 'cancelled',
                    cancellation_reason = 'Automatically cancelled - request fulfilled by another facility',
                    updated_at = CURRENT_TIMESTAMP
                WHERE request_group_id = :group_id 
                AND id != :exclude_id 
                AND request_status IN ('pending', 'accepted')
                """),
                {
                    "group_id": str(request_group_id),
                    "exclude_id": str(exclude_request_id)
                }
            )
            
            await self.db.commit()
            logger.info(f"Bulk cancelled related requests for group {request_group_id}")
            
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error cancelling related requests: {str(e)}")
            raise

    async def delete_request(self, request_id: UUID) -> None:
        """Delete a request (only if pending)"""
        request = await self.get_request(request_id)
        if not request:
            raise HTTPException(status_code=404, detail="Blood request not found")
        
        if request.request_status not in [RequestStatus.pending, RequestStatus.cancelled]:
            raise HTTPException(
                status_code=400, 
                detail="Cannot delete request that is not pending or cancelled"
            )
        
        await self.db.delete(request)
        await self.db.commit()

    @performance_monitor
    async def list_requests_by_user(self, user_id: UUID) -> List[BloodRequest]:
        """List all requests by user - OPTIMIZED"""
        result = await self.db.execute(
            select(BloodRequest)
            .options(selectinload(BloodRequest.facility))
            .where(BloodRequest.requester_id == user_id)
            .order_by(BloodRequest.created_at.desc())
        )
        return result.scalars().all()

    @performance_monitor
    async def list_request_groups_by_user(self, user_id: UUID) -> List[BloodRequestGroupResponse]:
        """List request groups by user - OPTIMIZED"""
        # OPTIMIZATION: Single query to get all requests for user, then group in memory
        result = await self.db.execute(
            select(BloodRequest)
            .options(selectinload(BloodRequest.facility))
            .where(BloodRequest.requester_id == user_id)
            .order_by(BloodRequest.request_group_id.desc(), BloodRequest.created_at)
        )
        requests = result.scalars().all()
        
        # Group requests by group_id in memory
        groups_dict = {}
        for request in requests:
            group_id = request.request_group_id
            if group_id not in groups_dict:
                groups_dict[group_id] = []
            groups_dict[group_id].append(request)
        
        # Convert to group responses
        groups = []
        for group_id, group_requests in groups_dict.items():
            master_request = next((r for r in group_requests if r.is_master_request), group_requests[0])
            related_requests = [r for r in group_requests if not r.is_master_request]
            
            # Count statuses efficiently
            status_counts = {'pending': 0, 'accepted': 0, 'rejected': 0, 'cancelled': 0}
            for r in group_requests:
                if r.request_status.value in status_counts:
                    status_counts[r.request_status.value] += 1
            
            group_response = BloodRequestGroupResponse(
                request_group_id=group_id,
                blood_type=master_request.blood_type,
                blood_product=master_request.blood_product,
                quantity_requested=master_request.quantity_requested,
                notes=master_request.notes,
                master_request=master_request,
                related_requests=related_requests,
                total_facilities=len(group_requests),
                pending_count=status_counts['pending'],
                accepted_count=status_counts['accepted'],
                rejected_count=status_counts['rejected'],
                cancelled_count=status_counts['cancelled'],
                created_at=master_request.created_at,
                updated_at=max(r.updated_at for r in group_requests)
            )
            groups.append(group_response)
        
        return groups

    @performance_monitor
    async def list_requests_by_facility(
        self, 
        user_id: UUID, 
        option: str = "all",
        request_status: Optional[str] = None,
        processing_status: Optional[str] = None,
        page: int = 1,
        page_size: int = 10
    ) -> PaginatedResponse[BloodRequestResponse]:
        """List requests made by and/or received by facilities - HEAVILY OPTIMIZED"""

        # OPTIMIZATION: Use selectinload for better performance
        user_result = await self.db.execute(
            select(User)
            .options(
                selectinload(User.facility),
                selectinload(User.work_facility)
            )
            .where(User.id == user_id)
        )
        user = user_result.scalar_one_or_none()

        if not user:
            return self._get_empty_paginated_response(page, page_size)

        # Determine facility efficiently
        facility_id = (user.facility.id if user.facility else 
                      user.work_facility.id if user.work_facility else None)

        if not facility_id:
            return self._get_empty_paginated_response(page, page_size)

        # Build conditions efficiently
        conditions = [self._build_facility_query_conditions(option, facility_id, user_id)]
        
        # Validate and add status filters
        if not self._validate_and_add_status_filters(conditions, request_status, processing_status):
            return self._get_empty_paginated_response(page, page_size)

        # Combine conditions
        final_condition = and_(*conditions) if len(conditions) > 1 else conditions[0]

        # OPTIMIZATION: Use a single query with window functions for count and data
        offset = (page - 1) * page_size
        
        # Use a more efficient query structure
        query = (
            select(BloodRequest)
            .options(
                selectinload(BloodRequest.facility),
                selectinload(BloodRequest.requester).selectinload(User.facility),
                selectinload(BloodRequest.requester).selectinload(User.work_facility),
                selectinload(BloodRequest.fulfilled_by)
            )
            .where(final_condition)
            .order_by(BloodRequest.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )

        # Execute main query
        result = await self.db.execute(query)
        blood_requests = result.scalars().unique().all()

        # If no results, return empty response
        if not blood_requests:
            return self._get_empty_paginated_response(page, page_size)

        # Get total count separately (only when we have results)
        count_query = select(func.count(BloodRequest.id)).where(final_condition)
        total_items_result = await self.db.execute(count_query)
        total_items = total_items_result.scalar() or 0

        # Convert to response objects using optimized conversion
        response_items = []
        for request in blood_requests:
            try:
                response_obj = self._fast_convert_to_response(request)
                response_items.append(response_obj)
            except Exception as e:
                logger.error(f"Error converting request {request.id} to response: {str(e)}")
                continue

        # Calculate pagination
        total_pages = ceil(total_items / page_size) if total_items > 0 else 0

        logger.info(f"Fetched {len(response_items)} requests for user {user_id}, option: {option}")

        return PaginatedResponse(
            items=response_items,
            total_items=total_items,
            total_pages=total_pages,
            current_page=page,
            page_size=page_size,
            has_next=page < total_pages,
            has_prev=page > 1
        )

    async def list_requests_by_status(self, request_status: RequestStatus) -> List[BloodRequest]:
        """List requests by status - OPTIMIZED"""
        result = await self.db.execute(
            select(BloodRequest)
            .options(selectinload(BloodRequest.facility))
            .where(BloodRequest.request_status == request_status)
            .order_by(BloodRequest.created_at.desc())
        )
        return result.scalars().all()

    @performance_monitor
    async def get_request_statistics(self, user_id: UUID) -> dict:
        """Get request statistics for a user - OPTIMIZED"""
        # OPTIMIZATION: Single query to get all data needed for statistics
        result = await self.db.execute(
            select(BloodRequest.request_status, BloodRequest.request_group_id)
            .where(BloodRequest.requester_id == user_id)
        )
        requests = result.fetchall()
        
        # Process statistics in single pass
        groups_by_status = {}
        all_groups = set()
        
        for status, group_id in requests:
            all_groups.add(group_id)
            if status not in groups_by_status:
                groups_by_status[status] = set()
            groups_by_status[status].add(group_id)
        
        return {
            'total_request_groups': len(all_groups),
            'total_individual_requests': len(requests),
            'pending_groups': len(groups_by_status.get(RequestStatus.pending, set())),
            'approved_groups': len(groups_by_status.get(RequestStatus.accepted, set())),  # Fixed: was 'approved'
            'fulfilled_groups': len(groups_by_status.get(RequestStatus.completed, set())),  # Assuming completed means fulfilled
            'rejected_groups': len(groups_by_status.get(RequestStatus.rejected, set())),
            'cancelled_groups': len(groups_by_status.get(RequestStatus.cancelled, set()))
        }