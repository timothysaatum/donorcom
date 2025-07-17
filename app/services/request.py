from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from sqlalchemy import and_, or_, func
from fastapi import HTTPException
from uuid import UUID, uuid4
from typing import List, Optional
from math import ceil
from app.models.request import BloodRequest, RequestStatus
from app.models.health_facility import Facility
from app.models.user import User
from app.schemas.request import (
    BloodRequestCreate, 
    BloodRequestUpdate, 
    BloodRequestGroupResponse,
    BloodRequestBulkCreateResponse,
    RequestDirection,
    BloodRequestResponse
)
from app.schemas.inventory import PaginatedResponse
import logging

logger = logging.getLogger(__name__)


class BloodRequestService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_bulk_request(self, data: BloodRequestCreate, requester_id: UUID) -> BloodRequestBulkCreateResponse:
        """Create requests to multiple facilities with intelligent grouping"""

        #  Get the requester to determine their facility
        requester_result = await self.db.execute(
            select(User)
            .options(
                joinedload(User.facility),
                joinedload(User.work_facility)
            )
            .where(User.id == requester_id)
        )
        requester = requester_result.scalar_one_or_none()
    
        if not requester:
            raise HTTPException(status_code=404, detail="Requester not found")
    
        # Determine requester's facility
        requester_facility_id = None
        if requester.facility:  # For facility administrators
            requester_facility_id = requester.facility.id
        elif requester.work_facility:  # For staff/lab managers
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
                    request_status=RequestStatus.pending,
                    option="sent"  # Explicitly set option for sent requests
                )
            
                self.db.add(new_request)
                created_requests.append(new_request)
        
            await self.db.commit()

            # Refresh all requests to get IDs and load relationships
            for request in created_requests:
                await self.db.refresh(request)
        
            # Load facility relationships for proper response conversion
            refreshed_requests = []
            for request in created_requests:
                result = await self.db.execute(
                    select(BloodRequest)
                    .options(
                        joinedload(BloodRequest.facility),
                        joinedload(BloodRequest.requester).joinedload(User.facility),
                        joinedload(BloodRequest.requester).joinedload(User.work_facility)
                    )
                    .where(BloodRequest.id == request.id)
                )
                refreshed_request = result.scalar_one()
                refreshed_requests.append(refreshed_request)
        
            # Convert to response models with proper facility names
            response_requests = [
                BloodRequestResponse.from_orm_with_facility_names(request) 
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
                joinedload(BloodRequest.requester).joinedload(User.facility),
                joinedload(BloodRequest.requester).joinedload(User.work_facility),
                joinedload(BloodRequest.facility)
            )
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
            'pending': sum(1 for r in requests if r.request_status == RequestStatus.pending),
            # 'approved': sum(1 for r in requests if r.request_status == RequestStatus.approved),
            'rejected': sum(1 for r in requests if r.request_status == RequestStatus.rejected),
            # 'fulfilled': sum(1 for r in requests if r.request_status == RequestStatus.fulfilled),
            'cancelled': sum(1 for r in requests if r.request_status == RequestStatus.cancelled)
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
        old_status = request.request_status
        new_status = data.request_status if data.request_status is not None else old_status
        
        # Update request fields
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(request, field, value)
        
        await self.db.commit()
        await self.db.refresh(request)
        
        # Handle intelligent cancellation if request is approved/fulfilled
        if (old_status in [RequestStatus.pending, RequestStatus.accepted] and 
            new_status in [RequestStatus.accepted]):#RequestStatus.accepted]):
            
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
                        BloodRequest.request_status.in_([RequestStatus.pending, RequestStatus.approved])
                    )
                )
            )
            related_requests = result.scalars().all()
            
            # Cancel each related request
            for req in related_requests:
                req.request_status = RequestStatus.cancelled
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
        
        if request.request_status not in [RequestStatus.pending, RequestStatus.cancelled]:
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


    async def list_requests_by_facility(
        self, 
        user_id: UUID, 
        option: str = "all",
        request_status: Optional[str] = None,
        processing_status: Optional[str] = None,
        page: int = 1,
        page_size: int = 10
    ) -> PaginatedResponse[BloodRequestResponse]:  # Changed return type
        """List requests made by and/or received by facilities associated with the user with pagination"""

        # Get the user with their facility relationships
        user_result = await self.db.execute(
            select(User)
            .options(
                joinedload(User.facility),  # For facility_administrator
                joinedload(User.work_facility)  # For staff/lab_manager
            )
            .where(User.id == user_id)
        )
        user = user_result.scalar_one_or_none()

        if not user:
            return PaginatedResponse(
                items=[],
                total_items=0,
                total_pages=0,
                current_page=page,
                page_size=page_size,
                has_next=False,
                has_prev=False
            )

        # Determine which facility the user is associated with
        facility_id = None
        if user.facility:  # User is facility_administrator
            facility_id = user.facility.id
        elif user.work_facility:  # User is staff or lab_manager
            facility_id = user.work_facility.id

        if not facility_id:
            return PaginatedResponse(
                items=[],
                total_items=0,
                total_pages=0,
                current_page=page,
                page_size=page_size,
                has_next=False,
                has_prev=False
            )

        # Build the base query conditions
        conditions = []

        # Handle the option filter with proper logic
        if option == "received":
            # Requests received by this facility (facility_id matches and option is 'received')
            conditions.append(BloodRequest.facility_id == facility_id)
            conditions.append(BloodRequest.requester_id != user_id)
        elif option == "sent":
            # Requests sent by this user (requester_id matches and option is 'sent')
            conditions.append(BloodRequest.requester_id == user_id)
            conditions.append(BloodRequest.option == "sent")
        else:  # "all"
            # Both sent and received requests
            conditions.append(
                or_(
                    and_(
                        BloodRequest.facility_id == facility_id,
                        BloodRequest.requester_id != user_id
                    ),
                    and_(
                        BloodRequest.requester_id == user_id,
                        BloodRequest.option == "sent"
                    )
                )
            )

        # Add status filters if provided
        if request_status:
            try:
                # Validate status is a valid enum value
                status_enum = RequestStatus(request_status)
                conditions.append(BloodRequest.request_status == status_enum)
            except ValueError:
                # Invalid status provided, return empty result
                return PaginatedResponse(
                    items=[],
                    total_items=0,
                    total_pages=0,
                    current_page=page,
                    page_size=page_size,
                    has_next=False,
                    has_prev=False
                )

        # Add processing status filter if provided
        if processing_status:
            try:
                # Import ProcessingStatus here to avoid circular imports
                from app.models.request import ProcessingStatus
                # Validate processing status is a valid enum value
                processing_enum = ProcessingStatus(processing_status)
                conditions.append(BloodRequest.processing_status == processing_enum)
            except ValueError:
                # Invalid processing status provided, return empty result
                return PaginatedResponse(
                    items=[],
                    total_items=0,
                    total_pages=0,
                    current_page=page,
                    page_size=page_size,
                    has_next=False,
                    has_prev=False
                )

        # Combine all conditions
        final_condition = and_(*conditions) if len(conditions) > 1 else conditions[0]

        # Count total items
        count_query = select(func.count(BloodRequest.id)).where(final_condition)
        total_items_result = await self.db.execute(count_query)
        total_items = total_items_result.scalar() or 0

        # Calculate pagination info
        total_pages = ceil(total_items / page_size) if total_items > 0 else 0
        offset = (page - 1) * page_size

        # Build the main query with pagination and include requester's facility information
        query = (
        select(BloodRequest)
        .options(
            joinedload(BloodRequest.facility),  # Target facility (where request is sent to)
            joinedload(BloodRequest.requester).joinedload(User.facility),  # Requester's facility (admin)
            joinedload(BloodRequest.requester).joinedload(User.work_facility),  # Requester's work facility (staff/lab_manager)
            joinedload(BloodRequest.fulfilled_by)
        )
        .where(final_condition)
        .order_by(BloodRequest.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )

        result = await self.db.execute(query)
        blood_requests = result.scalars().unique().all()

        # Convert SQLAlchemy objects to response objects with proper facility names
        response_items = []
        for request in blood_requests:
            try:
                response_obj = BloodRequestResponse.from_orm_with_facility_names(request)
                response_items.append(response_obj)
            except Exception as e:
                logger.error(f"Error converting request {request.id} to response: {str(e)}")
                # Log the problematic request details for debugging
                logger.error(f"Request details: facility={request.facility}, requester={request.requester}")
                continue

        logger.info(f"Fetched {len(response_items)} requests for user {user_id}, option: {option}, request_status: {request_status}, processing_status: {processing_status}")

        return PaginatedResponse(
            items=response_items,  # Return converted response objects
        total_items=total_items,
        total_pages=total_pages,
        current_page=page,
        page_size=page_size,
        has_next=page < total_pages,
        has_prev=page > 1
    )

    # async def list_requests_by_facility(
    #     self, 
    #     user_id: UUID, 
    #     option: str = "all",
    #     request_status: Optional[str] = None,
    #     page: int = 1,
    #     page_size: int = 10
    # ) -> PaginatedResponse[BloodRequest]:
    #     """List requests made by and/or received by facilities associated with the user with pagination"""
        
    #     # Get the user with their facility relationships
    #     user_result = await self.db.execute(
    #         select(User)
    #         .options(
    #             joinedload(User.facility),  # For facility_administrator
    #             joinedload(User.work_facility)  # For staff/lab_manager
    #         )
    #         .where(User.id == user_id)
    #     )
    #     user = user_result.scalar_one_or_none()
        
    #     if not user:
    #         return PaginatedResponse(
    #             items=[],
    #             total_items=0,
    #             total_pages=0,
    #             current_page=page,
    #             page_size=page_size,
    #             has_next=False,
    #             has_prev=False
    #         )
        
    #     # Determine which facility the user is associated with
    #     facility_id = None
    #     if user.facility:  # User is facility_administrator
    #         facility_id = user.facility.id
    #     elif user.work_facility:  # User is staff or lab_manager
    #         facility_id = user.work_facility.id
        
    #     if not facility_id:
    #         return PaginatedResponse(
    #             items=[],
    #             total_items=0,
    #             total_pages=0,
    #             current_page=page,
    #             page_size=page_size,
    #             has_next=False,
    #             has_prev=False
    #         )
        
    #     # Build the base query conditions
    #     conditions = []
        
    #     # Handle the option filter with proper logic
    #     if option == "received":
    #         # Requests received by this facility (facility_id matches and option is 'received')
    #         conditions.append(BloodRequest.facility_id == facility_id)
    #         conditions.append(BloodRequest.option == "received")
    #     elif option == "sent":
    #         # Requests sent by this user (requester_id matches and option is 'sent')
    #         conditions.append(BloodRequest.requester_id == user_id)
    #         conditions.append(BloodRequest.option == "sent")
    #     else:  # "all"
    #         # Both sent and received requests
    #         conditions.append(
    #             or_(
    #                 and_(
    #                     BloodRequest.facility_id == facility_id,
    #                     BloodRequest.option == "received"
    #                 ),
    #                 and_(
    #                     BloodRequest.requester_id == user_id,
    #                     BloodRequest.option == "sent"
    #                 )
    #             )
    #         )
        
    #     # Add status filter if provided
    #     if request_status:
    #         try:
    #             # Validate status is a valid enum value
    #             status_enum = RequestStatus(request_status)
    #             conditions.append(BloodRequest.request_status == status_enum)
    #         except ValueError:
    #             # Invalid status provided, return empty result
    #             return PaginatedResponse(
    #                 items=[],
    #                 total_items=0,
    #                 total_pages=0,
    #                 current_page=page,
    #                 page_size=page_size,
    #                 has_next=False,
    #                 has_prev=False
    #             )
        
    #     # Combine all conditions
    #     final_condition = and_(*conditions) if len(conditions) > 1 else conditions[0]
        
    #     # Count total items
    #     count_query = select(func.count(BloodRequest.id)).where(final_condition)
    #     total_items_result = await self.db.execute(count_query)
    #     total_items = total_items_result.scalar() or 0
        
    #     # Calculate pagination info
    #     total_pages = ceil(total_items / page_size) if total_items > 0 else 0
    #     offset = (page - 1) * page_size
        
    #     # Build the main query with pagination
    #     query = (
    #         select(BloodRequest)
    #         .options(
    #             joinedload(BloodRequest.facility),
    #             joinedload(BloodRequest.requester),
    #             joinedload(BloodRequest.fulfilled_by)
    #         )
    #         .where(final_condition)
    #         .order_by(BloodRequest.created_at.desc())
    #         .offset(offset)
    #         .limit(page_size)
    #     )
        
    #     result = await self.db.execute(query)
    #     items = result.scalars().unique().all()
        
    #     logger.info(f"Fetched {len(items)} requests for user {user_id}, option: {option}, status: {request_status}")
        
    #     return PaginatedResponse(
    #         items=items,
    #         total_items=total_items,
    #         total_pages=total_pages,
    #         current_page=page,
    #         page_size=page_size,
    #         has_next=page < total_pages,
    #         has_prev=page > 1
    #     )

    async def list_requests_by_status(self, request_status: RequestStatus) -> List[BloodRequest]:
        """List requests by status"""
        result = await self.db.execute(
            select(BloodRequest)
            .options(joinedload(BloodRequest.facility))
            .where(BloodRequest.request_status == request_status)
            .order_by(BloodRequest.created_at.desc())
        )
        return result.scalars().all()

    async def get_request_statistics(self, user_id: UUID) -> dict:
        """Get request statistics for a user"""
        result = await self.db.execute(
            select(BloodRequest.request_status, BloodRequest.request_group_id)
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