from app.models.tracking_model import TrackState
from app.schemas.tracking_schema import TrackStateStatus
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import and_, or_, func, update
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
    BloodRequestResponse,
)
from app.schemas.inventory import PaginatedResponse
from app.utils.notification_util import notify
import logging
from app.utils.performance_monitor import performance_monitor

logger = logging.getLogger(__name__)


class BloodRequestService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self._facility_name_cache: Dict[str, str] = {}

    def _get_empty_paginated_response(
        self, page: int, page_size: int
    ) -> PaginatedResponse[BloodRequestResponse]:
        """Reusable empty response generator"""
        return PaginatedResponse(
            items=[],
            total_items=0,
            total_pages=0,
            current_page=page,
            page_size=page_size,
            has_next=False,
            has_prev=False,
        )

    async def get_facility_request_patterns(
        self, source_facility_id: UUID, days_back: int = 30
    ) -> Dict[str, Any]:
        """Get request patterns between facilities for analytics and caching."""
        from datetime import datetime, timedelta

        cutoff_date = datetime.now() - timedelta(days=days_back)

        # Query for request patterns with optimized joins
        result = await self.db.execute(
            select(
                BloodRequest.facility_id.label("target_facility_id"),
                func.count(BloodRequest.id).label("request_count"),
                func.avg(BloodRequest.quantity_requested).label("avg_quantity"),
                BloodRequest.blood_type,
                BloodRequest.blood_product,
            )
            .where(
                and_(
                    BloodRequest.source_facility_id == source_facility_id,
                    BloodRequest.created_at >= cutoff_date,
                )
            )
            .group_by(
                BloodRequest.facility_id,
                BloodRequest.blood_type,
                BloodRequest.blood_product,
            )
            .order_by(func.count(BloodRequest.id).desc())
        )

        patterns = result.fetchall()
        return {
            "source_facility_id": str(source_facility_id),
            "analysis_period_days": days_back,
            "patterns": [
                {
                    "target_facility_id": str(row.target_facility_id),
                    "request_count": row.request_count,
                    "avg_quantity": float(row.avg_quantity or 0),
                    "blood_type": row.blood_type,
                    "blood_product": row.blood_product,
                }
                for row in patterns
            ],
        }

    async def get_facility_collaboration_stats(
        self, facility_id: UUID
    ) -> Dict[str, Any]:
        """Get comprehensive facility collaboration statistics."""

        # Outgoing requests (as source facility)
        outgoing_result = await self.db.execute(
            select(
                func.count(BloodRequest.id).label("total_sent"),
                func.count(
                    func.nullif(
                        BloodRequest.request_status == RequestStatus.ACCEPTED, False
                    )
                ).label("accepted_sent"),
                func.count(
                    func.nullif(
                        BloodRequest.request_status == RequestStatus.PENDING, False
                    )
                ).label("pending_sent"),
            ).where(BloodRequest.source_facility_id == facility_id)
        )
        outgoing_stats = outgoing_result.first()

        # Incoming requests (as target facility)
        incoming_result = await self.db.execute(
            select(
                func.count(BloodRequest.id).label("total_received"),
                func.count(
                    func.nullif(
                        BloodRequest.request_status == RequestStatus.ACCEPTED, False
                    )
                ).label("accepted_received"),
                func.count(
                    func.nullif(
                        BloodRequest.request_status == RequestStatus.PENDING, False
                    )
                ).label("pending_received"),
            ).where(BloodRequest.facility_id == facility_id)
        )
        incoming_stats = incoming_result.first()

        return {
            "facility_id": str(facility_id),
            "outgoing": {
                "total_sent": outgoing_stats.total_sent or 0,
                "accepted_sent": outgoing_stats.accepted_sent or 0,
                "pending_sent": outgoing_stats.pending_sent or 0,
            },
            "incoming": {
                "total_received": incoming_stats.total_received or 0,
                "accepted_received": incoming_stats.accepted_received or 0,
                "pending_received": incoming_stats.pending_received or 0,
            },
        }

    def _build_facility_query_conditions(
        self, option: str, facility_id: UUID, user_id: UUID
    ) -> Optional[Any]:
        """Build query conditions efficiently"""
        not_cancelled = BloodRequest.request_status != RequestStatus.CANCELLED
        if option == "received":
            return and_(
                BloodRequest.facility_id == facility_id,
                BloodRequest.requester_id != user_id,
                not_cancelled,
            )
        elif option == "sent":
            return and_(
                BloodRequest.requester_id == user_id,
                BloodRequest.option == "sent",
                not_cancelled,
            )
        else:  # "all"
            return or_(
                and_(
                    BloodRequest.facility_id == facility_id,
                    BloodRequest.requester_id != user_id,
                ),
                and_(
                    BloodRequest.requester_id == user_id, BloodRequest.option == "sent"
                ),
                not_cancelled,
            )

    def _validate_and_add_status_filters(
        self,
        conditions: List,
        request_status: Optional[str],
        processing_status: Optional[str],
    ) -> bool:
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
        if request.target_facility and request.target_facility.facility_name:
            facility_key = str(request.facility_id)
            if facility_key in self._facility_name_cache:
                receiving_facility_name = self._facility_name_cache[facility_key]
            else:
                name = request.target_facility.facility_name.strip()
                receiving_facility_name = name if name else "Unknown Facility"
                self._facility_name_cache[facility_key] = receiving_facility_name

        # Fast requester facility name resolution
        requester_facility_name = None
        if request.requester:
            if request.requester.facility and request.requester.facility.facility_name:
                name = request.requester.facility.facility_name.strip()
                requester_facility_name = name if name else None
            elif (
                request.requester.work_facility
                and request.requester.work_facility.facility_name
            ):
                name = request.requester.work_facility.facility_name.strip()
                requester_facility_name = name if name else None

        # Fast source facility name resolution with caching
        source_facility_name = "Unknown Facility"
        if request.source_facility and request.source_facility.facility_name:
            source_key = str(request.source_facility_id)
            if source_key in self._facility_name_cache:
                source_facility_name = self._facility_name_cache[source_key]
            else:
                name = request.source_facility.facility_name.strip()
                source_facility_name = name if name else "Unknown Facility"
                self._facility_name_cache[source_key] = source_facility_name


        return BloodRequestResponse(
            id=request.id,
            requester_id=request.requester_id,
            facility_id=request.facility_id,
            source_facility_id=request.source_facility_id,
            receiving_facility_name=receiving_facility_name,
            source_facility_name=source_facility_name,
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
            requester_name=request.full_name,
            created_at=request.created_at,
            updated_at=request.updated_at,
        )

    @performance_monitor
    async def create_bulk_request(
        self, data: BloodRequestCreate, requester_id: UUID
    ) -> BloodRequestBulkCreateResponse:
        """Create requests to multiple facilities with intelligent grouping - OPTIMIZED"""

        # Get requester with facility relationships
        requester_result = await self.db.execute(
            select(User)
            .options(selectinload(User.facility), selectinload(User.work_facility))
            .where(User.id == requester_id)
        )
        requester = requester_result.scalar_one_or_none()
        if not requester:
            raise HTTPException(status_code=404, detail="Requester not found")

        # Identify requester's facility (source facility)
        source_facility_id = (
            requester.facility.id
            if requester.facility
            else (requester.work_facility.id if requester.work_facility else None)
        )

        if not source_facility_id:
            raise HTTPException(
                status_code=400,
                detail="User must be associated with a facility to make requests.",
            )

        # Self-request prevention - compare with source facility instead of inferring
        if source_facility_id:
            original_count = len(data.facility_ids)
            data.facility_ids = [
                fid for fid in data.facility_ids if fid != source_facility_id
            ]
            if len(data.facility_ids) != original_count:
                logger.warning(
                    f"Removed requester's own facility from request list. "
                    f"Original: {original_count}, After: {len(data.facility_ids)}"
                )

        if not data.facility_ids:
            raise HTTPException(
                status_code=400,
                detail="Cannot send requests to your own facility. Please select other facilities.",
            )

        # Validate facilities exist & fetch their names
        facilities_result = await self.db.execute(
            select(Facility.id, Facility.facility_name).where(
                Facility.id.in_(data.facility_ids)
            )
        )
        facility_map = {row.id: row.facility_name for row in facilities_result}
        if len(facility_map) != len(data.facility_ids):
            raise HTTPException(
                status_code=400, detail="One or more facilities not found"
            )

        # Generate group ID
        request_group_id = uuid4()
        created_requests = []

        try:
            for idx, facility_id in enumerate(data.facility_ids):
                is_master = idx == 0

                # Create blood request with explicit source facility
                new_request = BloodRequest(
                    requester_id=requester_id,
                    facility_id=facility_id,  # Target facility
                    source_facility_id=source_facility_id,  # Source facility
                    request_group_id=request_group_id,
                    is_master_request=is_master,
                    blood_type=data.blood_type,
                    blood_product=data.blood_product,
                    quantity_requested=data.quantity_requested,
                    notes=data.notes,
                    request_status=RequestStatus.PENDING,
                    priority=data.priority,
                )
                self.db.add(new_request)
                await self.db.flush()  # ensures new_request.id is available

                # Create initial track state
                track_state = TrackState(
                    blood_request_id=new_request.id,
                    status=TrackStateStatus.PENDING_RECEIVE,
                    location=facility_map[facility_id],
                    notes="Request created, awaiting processing",
                    created_by_id=requester_id,
                )
                self.db.add(track_state)
                created_requests.append(new_request)

            # Final commit
            await self.db.commit()

            # Send notification using the utility function
            facility_names = ", ".join([facility_map[fid] for fid in data.facility_ids])
            await notify(
                self.db,
                requester_id,
                "Blood Requests Created",
                f"Successfully created requests for {data.blood_product} ({data.blood_type}) - {data.quantity_requested} units to {len(data.facility_ids)} facilities: {facility_names}",
            )

            # Reload all created requests with relationships
            request_ids = [req.id for req in created_requests]
            result = await self.db.execute(
                select(BloodRequest)
                .options(
                    selectinload(BloodRequest.target_facility),
                    selectinload(BloodRequest.source_facility),
                    selectinload(BloodRequest.requester).selectinload(User.facility),
                    selectinload(BloodRequest.requester).selectinload(
                        User.work_facility
                    ),
                )
                .where(BloodRequest.id.in_(request_ids))
            )
            refreshed_requests = result.scalars().all()

            logger.info(
                f"Created {len(created_requests)} blood requests with group ID: {request_group_id}"
            )

            return BloodRequestBulkCreateResponse(
                request_group_id=request_group_id,
                total_requests_created=len(created_requests),
                requests=[
                    self._fast_convert_to_response(r) for r in refreshed_requests
                ],
                message=f"Successfully created requests to {len(created_requests)} facilities",
            )

        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error creating bulk requests: {str(e)}")
            raise HTTPException(
                status_code=500, detail="Failed to create blood requests"
            )

    async def _validate_facilities(self, facility_ids: List[UUID]) -> None:
        """Validate that all facilities exist"""
        result = await self.db.execute(
            select(Facility.id).where(Facility.id.in_(facility_ids))
        )
        existing_ids = {row[0] for row in result.fetchall()}

        missing_ids = set(facility_ids) - existing_ids
        if missing_ids:
            raise HTTPException(
                status_code=404, detail=f"Facilities not found: {list(missing_ids)}"
            )

    async def get_request(self, request_id: UUID):
        result = await self.db.execute(
            select(BloodRequest)
            .options(
                selectinload(BloodRequest.requester).selectinload(User.facility),
                selectinload(BloodRequest.requester).selectinload(User.work_facility),
                selectinload(BloodRequest.target_facility),
                selectinload(BloodRequest.source_facility),
                selectinload(BloodRequest.distributions),
            )
            .where(BloodRequest.id == request_id)
        )
        return result.scalar_one_or_none()

    @performance_monitor
    async def get_request_group(
        self, request_group_id: UUID
    ) -> Optional[BloodRequestGroupResponse]:
        """Get all requests in a group with summary information - OPTIMIZED"""
        result = await self.db.execute(
            select(BloodRequest)
            .options(
                selectinload(BloodRequest.target_facility),
                selectinload(BloodRequest.source_facility),
            )
            .where(BloodRequest.request_group_id == request_group_id)
            .order_by(BloodRequest.is_master_request.desc(), BloodRequest.created_at)
        )
        requests = result.scalars().all()

        if not requests:
            return None

        master_request = next((r for r in requests if r.is_master_request), requests[0])
        related_requests = [r for r in requests if not r.is_master_request]

        if not master_request:
            raise HTTPException(
                status_code=404, detail="Master request not found in group"
            )

        # OPTIMIZATION: Count statuses in single pass - FIXED
        status_counts = {
            "pending": 0,
            "approved": 0,  # Changed from 'accepted'
            "rejected": 0,
            "fulfilled": 0,  # Added missing count
            "cancelled": 0,
        }

        unique_facilities = set()

        for r in requests:
            # Fix: Get the actual status value
            status = (
                r.request_status.value
                if hasattr(r.request_status, "value")
                else str(r.request_status).lower()
            )

        # Count statuses
        if status in status_counts:
            status_counts[status] += 1

        # Track unique facilities
        unique_facilities.add(r.facility_id)

        # Convert ORM objects to response models
        master_request_response = BloodRequestResponse.model_validate(master_request)
        related_requests_response = [
            BloodRequestResponse.model_validate(r) for r in related_requests
        ]

        return BloodRequestGroupResponse(
            request_group_id=request_group_id,
            blood_type=master_request.blood_type,
            blood_product=master_request.blood_product,
            quantity_requested=sum(
                r.quantity_requested for r in requests
            ),  # Sum all requests
            notes=master_request.notes,
            master_request=master_request_response,  # Convert to response model
            related_requests=related_requests_response,  # Convert to response models
            total_facilities=len(unique_facilities),  # Count unique facilities
            pending_count=status_counts["pending"],
            approved_count=status_counts["approved"],
            rejected_count=status_counts["rejected"],
            fulfilled_count=status_counts["fulfilled"],
            cancelled_count=status_counts["cancelled"],
            created_at=master_request.created_at,
            updated_at=max(r.updated_at for r in requests),
        )

    async def update_request(
        self, request_id: UUID, data: BloodRequestUpdate
    ) -> BloodRequest:
        """Update a request and handle intelligent cancellation - FIXED"""
        request = await self.get_request(request_id)
        if not request:
            raise HTTPException(status_code=404, detail="Blood request not found")

        old_status = request.request_status

        # Apply updates
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(request, field, value)

        new_status = request.request_status

        try:
            # Commit update
            await self.db.commit()
            await self.db.refresh(request)

            # Track state logging if status changed
            if old_status != new_status:
                # Map request status to TrackStateStatus safely
                status_mapping = {
                    "pending": TrackStateStatus.PENDING_RECEIVE,
                    "accepted": TrackStateStatus.DISPATCHED,
                    "fulfilled": TrackStateStatus.FULFILLED,
                    "returned": TrackStateStatus.RETURNED,
                    "rejected": TrackStateStatus.REJECTED,
                    "cancelled": TrackStateStatus.CANCELLED,
                }
                mapped_status = status_mapping.get(
                    new_status.value, TrackStateStatus.PENDING_RECEIVE
                )

                track_state = TrackState(
                    blood_request_id=request.id,
                    status=mapped_status,
                    location=(
                        request.target_facility.facility_name
                        if request.target_facility
                        else None
                    ),
                    notes=f"Request status changed from {old_status.value} to {new_status.value}",
                    created_by_id=request.requester_id,
                )
                self.db.add(track_state)
                await self.db.commit()

                # Send notification using the utility function
                await notify(
                    self.db,
                    request.requester_id,
                    "Request Status Updated",
                    f"Your blood request for {request.blood_product} ({request.blood_type}) has been updated from {old_status.value} to {new_status.value}",
                )

            # Handle intelligent cancellation if request is accepted
            if (
                old_status == RequestStatus.PENDING
                and new_status == RequestStatus.ACCEPTED
            ):
                cancelled_count = await self._cancel_related_requests(
                    request.request_group_id, request.id
                )
                logger.info(
                    f"Cancelled {cancelled_count} related requests after acceptance of request {request.id}"
                )

        except Exception as e:
            await self.db.rollback()
            logger.error(f"Failed to update request {request_id}: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to update request")

        return request

    async def _cancel_related_requests(
        self, request_group_id: UUID, exclude_request_id: UUID
    ) -> int:
        """Cancel all related requests in a group except the specified one - FIXED"""
        try:
            # First, get the requests that will be cancelled for logging
            check_query = select(BloodRequest.id, BloodRequest.request_status).where(
                and_(
                    BloodRequest.request_group_id == request_group_id,
                    BloodRequest.id != exclude_request_id,
                    BloodRequest.request_status.in_(
                        [RequestStatus.PENDING, RequestStatus.ACCEPTED]
                    ),
                )
            )
            check_result = await self.db.execute(check_query)
            requests_to_cancel = check_result.fetchall()

            if not requests_to_cancel:
                logger.info(
                    f"No related requests to cancel for group {request_group_id}"
                )
                return 0

            logger.info(
                f"Found {len(requests_to_cancel)} requests to cancel in group {request_group_id}"
            )

            update_stmt = (
                update(BloodRequest)
                .where(
                    and_(
                        BloodRequest.request_group_id == request_group_id,
                        BloodRequest.id != exclude_request_id,
                        BloodRequest.request_status.in_(
                            [RequestStatus.PENDING, RequestStatus.ACCEPTED]
                        ),
                    )
                )
                .values(
                    request_status=RequestStatus.CANCELLED,
                    cancellation_reason="Automatically cancelled - request fulfilled by another facility",
                    updated_at=func.now(),
                )
            )

            result = await self.db.execute(update_stmt)
            cancelled_count = result.rowcount

            # Commit the cancellation updates
            await self.db.commit()

            logger.info(
                f"Successfully cancelled {cancelled_count} related requests for group {request_group_id}"
            )
            return cancelled_count

        except Exception as e:
            await self.db.rollback()
            logger.error(
                f"Error cancelling related requests for group {request_group_id}: {str(e)}"
            )
            raise HTTPException(
                status_code=500, detail="Failed to cancel related requests"
            )

    async def delete_request(self, request_id: UUID) -> None:
        """Delete a request (only if pending)"""
        request = await self.get_request(request_id)
        if not request:
            raise HTTPException(status_code=404, detail="Blood request not found")

        if request.request_status not in [
            RequestStatus.PENDING,
            RequestStatus.CANCELLED,
        ]:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete request that is not pending or cancelled",
            )

        # Send notification before deletion
        await notify(
            self.db,
            request.requester_id,
            "Request Deleted",
            f"Your blood request for {request.blood_product} ({request.blood_type}) - {request.quantity_requested} units has been deleted",
        )

        await self.db.delete(request)
        await self.db.commit()

        logger.info(f"Request {request_id} deleted successfully")

    @performance_monitor
    async def list_requests_by_user(self, user_id: UUID) -> List[BloodRequest]:
        """List all requests by user - OPTIMIZED"""
        result = await self.db.execute(
            select(BloodRequest)
            .options(
                selectinload(BloodRequest.target_facility),
                selectinload(BloodRequest.source_facility),
            )
            .where(BloodRequest.requester_id == user_id)
            .order_by(BloodRequest.created_at.desc())
        )
        return result.scalars().all()

    @performance_monitor
    async def list_request_groups_by_user(
        self, user_id: UUID
    ) -> List[BloodRequestGroupResponse]:
        """List request groups by user - OPTIMIZED"""
        # OPTIMIZATION: Single query to get all requests for user, then group in memory
        result = await self.db.execute(
            select(BloodRequest)
            .options(
                selectinload(BloodRequest.target_facility),
                selectinload(BloodRequest.source_facility),
            )
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
            master_request = next(
                (r for r in group_requests if r.is_master_request), group_requests[0]
            )
            related_requests = [r for r in group_requests if not r.is_master_request]

            # FIXED: Count statuses efficiently with correct field names
            status_counts = {
                "pending": 0,
                "approved": 0,  # Changed from 'accepted'
                "rejected": 0,
                "fulfilled": 0,  # Added missing field
                "cancelled": 0,
            }

            unique_facilities = set()

            for r in group_requests:
                # Get status value properly
                status = (
                    r.request_status.value.lower()
                    if hasattr(r.request_status, "value")
                    else str(r.request_status).lower()
                )

                # Count statuses (handle mapping if needed)
                if status == "pending":
                    status_counts["pending"] += 1
                elif status in ["approved", "accepted"]:  # Handle both possibilities
                    status_counts["approved"] += 1
                elif status == "rejected":
                    status_counts["rejected"] += 1
                elif status == "fulfilled":
                    status_counts["fulfilled"] += 1
                elif status == "cancelled":
                    status_counts["cancelled"] += 1

                # Track unique facilities
                unique_facilities.add(r.facility_id)

            # Convert ORM objects to response models
            master_request_response = BloodRequestResponse.model_validate(
                master_request
            )
            related_requests_response = [
                BloodRequestResponse.model_validate(r) for r in related_requests
            ]

            group_response = BloodRequestGroupResponse(
                request_group_id=group_id,
                blood_type=master_request.blood_type,
                blood_product=master_request.blood_product,
                quantity_requested=sum(r.quantity_requested for r in group_requests),
                notes=master_request.notes,
                master_request=master_request_response,
                related_requests=related_requests_response,
                total_facilities=len(unique_facilities),
                pending_count=status_counts["pending"],
                approved_count=status_counts["approved"],
                rejected_count=status_counts["rejected"],
                fulfilled_count=status_counts["fulfilled"],
                cancelled_count=status_counts["cancelled"],
                created_at=master_request.created_at,
                updated_at=max(r.updated_at for r in group_requests),
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
        page_size: int = 10,
    ) -> PaginatedResponse[BloodRequestResponse]:
        """List requests made by and/or received by facilities - HEAVILY OPTIMIZED"""

        user_result = await self.db.execute(
            select(User)
            .options(selectinload(User.facility), selectinload(User.work_facility))
            .where(User.id == user_id)
        )
        user = user_result.scalar_one_or_none()

        if not user:
            return self._get_empty_paginated_response(page, page_size)

        # Determine facility efficiently
        facility_id = (
            user.facility.id
            if user.facility
            else user.work_facility.id if user.work_facility else None
        )

        if not facility_id:
            return self._get_empty_paginated_response(page, page_size)

        # Build conditions efficiently
        conditions = [
            self._build_facility_query_conditions(option, facility_id, user_id)
        ]

        # Validate and add status filters
        if not self._validate_and_add_status_filters(
            conditions, request_status, processing_status
        ):
            return self._get_empty_paginated_response(page, page_size)

        # Combine conditions
        final_condition = and_(*conditions) if len(conditions) > 1 else conditions[0]

        # OPTIMIZATION: Use a single query with window functions for count and data
        offset = (page - 1) * page_size

        # Use a more efficient query structure
        query = (
            select(BloodRequest)
            .options(
                selectinload(BloodRequest.target_facility),
                selectinload(BloodRequest.source_facility),
                selectinload(BloodRequest.requester).selectinload(User.facility),
                selectinload(BloodRequest.requester).selectinload(User.work_facility),
                selectinload(BloodRequest.fulfilled_by),
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
                logger.error(
                    f"Error converting request {request.id} to response: {str(e)}"
                )
                continue

        # Calculate pagination
        total_pages = ceil(total_items / page_size) if total_items > 0 else 0

        logger.info(
            f"Fetched {len(response_items)} requests for user {user_id}, option: {option}"
        )

        return PaginatedResponse(
            items=response_items,
            total_items=total_items,
            total_pages=total_pages,
            current_page=page,
            page_size=page_size,
            has_next=page < total_pages,
            has_prev=page > 1,
        )

    async def list_requests_by_status(
        self, request_status: RequestStatus
    ) -> List[BloodRequest]:
        """List requests by status - OPTIMIZED"""
        result = await self.db.execute(
            select(BloodRequest)
            .options(
                selectinload(BloodRequest.target_facility),
                selectinload(BloodRequest.source_facility),
            )
            .where(BloodRequest.request_status == request_status)
            .order_by(BloodRequest.created_at.desc())
        )
        return result.scalars().all()

    @performance_monitor
    async def get_request_statistics(self, user_id: UUID) -> dict:
        """Get request statistics for a user - OPTIMIZED"""
        # OPTIMIZATION: Single query to get all data needed for statistics
        result = await self.db.execute(
            select(BloodRequest.request_status, BloodRequest.request_group_id).where(
                BloodRequest.requester_id == user_id
            )
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
            "total_request_groups": len(all_groups),
            "total_individual_requests": len(requests),
            "pending_groups": len(groups_by_status.get(RequestStatus.PENDING, set())),
            "approved_groups": len(groups_by_status.get(RequestStatus.ACCEPTED, set())),
            "fulfilled_groups": len(
                groups_by_status.get(ProcessingStatus.COMPLETED, set())
            ),
            "rejected_groups": len(groups_by_status.get(RequestStatus.REJECTED, set())),
            "cancelled_groups": len(
                groups_by_status.get(RequestStatus.CANCELLED, set())
            ),
        }

    @performance_monitor
    async def cancel_request(
        self,
        request_id: UUID,
        cancellation_reason: Optional[str] = None,
        user_id: Optional[UUID] = None,
    ) -> BloodRequest:
        """Cancel a blood request - only allowed for pending requests"""

        # Get the request with all necessary relationships
        request = await self.get_request(request_id)
        if not request:
            raise HTTPException(status_code=404, detail="Blood request not found")

        # Check if request can be cancelled (only pending requests)
        if request.request_status != RequestStatus.PENDING:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel request with status '{request.request_status.value}'. Only pending requests can be cancelled.",
            )

        # Verify ownership if user_id is provided
        if user_id and request.requester_id != user_id:
            raise HTTPException(
                status_code=403, detail="Not authorized to cancel this request"
            )

        old_status = request.request_status

        try:
            # Update request status
            request.request_status = RequestStatus.CANCELLED
            request.cancellation_reason = (
                cancellation_reason or "Cancelled by requester"
            )

            # Commit the cancellation
            await self.db.commit()
            await self.db.refresh(request)

            # Create track state for cancellation
            track_state = TrackState(
                blood_request_id=request.id,
                status=TrackStateStatus.CANCELLED,
                location=(
                    request.target_facility.facility_name
                    if request.target_facility
                    else "Unknown Location"
                ),
                notes=f"Request cancelled by requester. Reason: {request.cancellation_reason}",
                created_by_id=request.requester_id,
            )
            self.db.add(track_state)
            await self.db.commit()

            # Send notification using the utility function
            await notify(
                self.db,
                request.requester_id,
                "Request Cancelled",
                f"Your blood request for {request.blood_product} ({request.blood_type}) - {request.quantity_requested} units has been cancelled. Reason: {request.cancellation_reason}",
            )

            logger.info(
                f"Request {request_id} cancelled successfully by user {user_id}. "
                f"Reason: {request.cancellation_reason}"
            )

            return request

        except Exception as e:
            await self.db.rollback()
            logger.error(f"Failed to cancel request {request_id}: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to cancel request")

    # =============================================================================
    # OPTIMIZED FACILITY-TO-FACILITY QUERY METHODS
    # =============================================================================

    async def get_requests_between_facilities(
        self,
        source_facility_id: UUID,
        target_facility_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> List[BloodRequest]:
        """Optimized query for requests between specific facilities."""
        result = await self.db.execute(
            select(BloodRequest)
            .options(
                selectinload(BloodRequest.source_facility),
                selectinload(BloodRequest.target_facility),
                selectinload(BloodRequest.requester),
            )
            .where(
                and_(
                    BloodRequest.source_facility_id == source_facility_id,
                    BloodRequest.facility_id == target_facility_id,
                )
            )
            .order_by(BloodRequest.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    async def get_facility_request_summary(
        self, facility_id: UUID, as_source: bool = True
    ) -> Dict[str, Any]:
        """Get summarized request data for a facility (as source or target)."""

        if as_source:
            # Requests sent by this facility
            condition = BloodRequest.source_facility_id == facility_id
        else:
            # Requests received by this facility
            condition = BloodRequest.facility_id == facility_id

        result = await self.db.execute(
            select(
                BloodRequest.request_status,
                BloodRequest.blood_type,
                BloodRequest.blood_product,
                func.count(BloodRequest.id).label("count"),
                func.sum(BloodRequest.quantity_requested).label("total_quantity"),
            )
            .where(condition)
            .group_by(
                BloodRequest.request_status,
                BloodRequest.blood_type,
                BloodRequest.blood_product,
            )
        )

        summary = {}
        for row in result:
            key = f"{row.blood_type}_{row.blood_product}_{row.request_status}"
            summary[key] = {
                "blood_type": row.blood_type,
                "blood_product": row.blood_product,
                "status": row.request_status,
                "count": row.count,
                "total_quantity": row.total_quantity or 0,
            }

        return {
            "facility_id": str(facility_id),
            "role": "source" if as_source else "target",
            "summary": list(summary.values()),
        }
