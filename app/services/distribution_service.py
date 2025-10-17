import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, and_, desc
from sqlalchemy.orm import joinedload, selectinload
from fastapi import HTTPException
from uuid import UUID
from datetime import datetime, timedelta
from typing import Optional, List
from app.models.distribution_model import BloodDistribution
from app.models.inventory_model import BloodInventory
from app.schemas.distribution_schema import (
    BloodDistributionUpdate,
    DistributionStats,
    DistributionStatus,
)
from app.models.tracking_model import TrackState
from app.schemas.tracking_schema import TrackStateStatus
from app.schemas.request_schema import ProcessingStatus
from app.utils.generators import (
    calculate_expiry_date,
    generate_batch_number,
    generate_tracking_number,
)
import logging

logger = logging.getLogger(__name__)


class BloodDistributionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_distribution(
        self,
        request_id: UUID,
        blood_bank_id: UUID,
        created_by_id: UUID,
        notes: Optional[str] = None,
    ) -> BloodDistribution:
        """
        Create a new blood distribution record and update inventory.
        Auto-fills data from blood request if request_id is provided.
        """
        # Import here to avoid circular imports
        from app.models.request_model import BloodRequest

        # Fetch the blood request to auto-fill data
        request_result = await self.db.execute(
            select(BloodRequest).where(BloodRequest.id == request_id)
        )
        blood_request = request_result.scalar_one_or_none()

        if not blood_request:
            raise HTTPException(
                status_code=404,
                detail=f"Blood request {request_id} not found",
            )

        # Validate request status - only fulfill pending or approved requests
        from app.schemas.request_schema import RequestStatus

        if blood_request.request_status not in [
            RequestStatus.ACCEPTED,
        ]:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot fulfill request with status '{blood_request.request_status}'. Request must be 'accepted'.",
            )

        # Auto-fill ALL data from the blood request
        blood_product = blood_request.blood_product
        blood_type = blood_request.blood_type
        quantity = blood_request.quantity_requested
        dispatched_to_id = blood_request.source_facility_id

        # Try to find matching inventory automatically (FIFO - First In First Out)
        inventory_result = await self.db.execute(
            select(BloodInventory)
            .where(
                and_(
                    BloodInventory.blood_bank_id == blood_bank_id,
                    BloodInventory.blood_product == blood_product,
                    BloodInventory.blood_type == blood_type,
                    BloodInventory.quantity >= quantity,
                )
            )
            .order_by(BloodInventory.expiry_date.asc())  # Use oldest inventory first
        )
        inventory_item = inventory_result.scalars().first()

        if inventory_item:
            # Deduct from inventory
            inventory_item.quantity -= quantity
            blood_product_id = inventory_item.id
        else:
            # No matching inventory found - try to resolve an existing inventory record
            # for the same product/type in this blood bank. If none exists, create a
            # placeholder inventory record with zero quantity so that distributions
            # always have a referenceable product id.
            from sqlalchemy.future import select as _select

            lookup_result = await self.db.execute(
                _select(BloodInventory)
                .where(
                    and_(
                        BloodInventory.blood_bank_id == blood_bank_id,
                        BloodInventory.blood_product == blood_product,
                        BloodInventory.blood_type == blood_type,
                    )
                )
                .limit(1)
            )
            resolved_inventory = lookup_result.scalars().first()

            if resolved_inventory:
                # Use the existing inventory record even if quantity is insufficient
                blood_product_id = resolved_inventory.id
            else:
                # Create a placeholder inventory entry (quantity 0). This ensures
                # downstream responses always include a product id even when the
                # physical stock was not found in inventory.
                placeholder_inventory = BloodInventory(
                    blood_product=blood_product,
                    blood_type=blood_type,
                    quantity=0,
                    expiry_date=calculate_expiry_date(blood_product),
                    blood_bank_id=blood_bank_id,
                    added_by_id=created_by_id,
                )
                self.db.add(placeholder_inventory)
                await self.db.flush()
                blood_product_id = placeholder_inventory.id

                import logging

                logging.getLogger(__name__).warning(
                    f"No matching inventory found for request {request_id}. "
                    f"Created placeholder inventory id={blood_product_id} for product {blood_product} ({blood_type})"
                )

        # Create distribution record
        new_distribution = BloodDistribution(
            blood_product_id=blood_product_id,
            request_id=request_id,
            dispatched_from_id=blood_bank_id,
            dispatched_to_id=dispatched_to_id,
            created_by_id=created_by_id,
            blood_product=blood_product,
            blood_type=blood_type,
            quantity=quantity,
            notes=notes if notes else "Blood issued for request, pending dispatch",
            batch_number=generate_batch_number(),  # Auto-generated
            expiry_date=calculate_expiry_date(
                blood_product
            ),  # Auto-calculated based on product type
            temperature_maintained=True,  # Default to True
            tracking_number=generate_tracking_number(),
        )

        self.db.add(new_distribution)

        # Let the caller handle the commit if needed
        await self.db.flush()
        await self.db.refresh(new_distribution)

        # Load relationships
        await self.db.refresh(
            new_distribution,
            attribute_names=[
                "dispatched_from",
                "dispatched_to",
                "created_by",
                "inventory_item",
            ],
        )

        track_state = TrackState(
            blood_distribution_id=new_distribution.id,
            blood_request_id=new_distribution.request_id,  # Use request_id instead of blood_product_id
            status=TrackStateStatus.PENDING_RECEIVE,
            location=new_distribution.dispatched_from.blood_bank_name,
            notes="Distribution created, awaiting dispatch",
            created_by_id=created_by_id,
        )
        # Add the tracking state
        self.db.add(track_state)

        # Update related blood request processing status to "initiated"
        await self._update_request_processing_status(new_distribution)

        await self.db.commit()

        # Send instant notification to BOTH facilities
        try:
            from app.utils.notification_util import notify_facility

            # Notify RECEIVING facility (dispatched_to)
            if new_distribution.dispatched_to_id:
                await notify_facility(
                    self.db,
                    [new_distribution.dispatched_to_id],
                    "Blood Shipment In Transit",
                    f"Blood shipment en route: {blood_product} ({blood_type}) - {quantity} units from {new_distribution.dispatched_from.blood_bank_name}",
                    extra_data={
                        "type": "distribution_incoming",
                        "distribution_id": str(new_distribution.id),
                        "tracking_number": new_distribution.tracking_number,
                        "blood_product": blood_product,
                        "blood_type": blood_type,
                        "quantity": quantity,
                        "from_facility": new_distribution.dispatched_from.blood_bank_name,
                    },
                )

            # 🔥 ALSO notify SENDING facility (dispatched_from's facility)
            if (
                new_distribution.dispatched_from
                and new_distribution.dispatched_from.facility_id
            ):
                await notify_facility(
                    self.db,
                    [new_distribution.dispatched_from.facility_id],
                    "Blood Shipment Dispatched",
                    f"Your facility dispatched: {blood_product} ({blood_type}) - {quantity} units to {new_distribution.dispatched_to.facility_name if new_distribution.dispatched_to else 'facility'}",
                    extra_data={
                        "type": "distribution_outgoing",
                        "distribution_id": str(new_distribution.id),
                        "tracking_number": new_distribution.tracking_number,
                        "blood_product": blood_product,
                        "blood_type": blood_type,
                        "quantity": quantity,
                        "to_facility": (
                            new_distribution.dispatched_to.facility_name
                            if new_distribution.dispatched_to
                            else None
                        ),
                    },
                )
        except Exception as notify_error:
            import logging

            logging.getLogger(__name__).error(
                f"Failed to send distribution notification: {str(notify_error)}"
            )

        # Refresh dashboard metrics asynchronously for both facilities (non-blocking)
        try:
            from app.services.dashboard_service import (
                async_refresh_facility_dashboard_metrics,
            )

            # Refresh for the facility that dispatched (their stock decreased)
            if (
                new_distribution.dispatched_from
                and new_distribution.dispatched_from.facility_id
            ):
                asyncio.create_task(
                    async_refresh_facility_dashboard_metrics(
                        new_distribution.dispatched_from.facility_id
                    )
                )
            # Refresh for the facility that received (their transferred count increased)
            if new_distribution.dispatched_to_id:
                asyncio.create_task(
                    async_refresh_facility_dashboard_metrics(
                        new_distribution.dispatched_to_id
                    )
                )
        except Exception as dashboard_error:
            # Don't fail the operation if dashboard refresh scheduling fails
            import logging

            logging.getLogger(__name__).warning(
                f"Failed to schedule dashboard refresh: {dashboard_error}"
            )

        return new_distribution

    async def get_distribution(
        self, distribution_id: UUID
    ) -> Optional[BloodDistribution]:
        """
        Get a distribution by ID with all related data
        """
        result = await self.db.execute(
            select(BloodDistribution)
            .options(
                joinedload(BloodDistribution.dispatched_from),
                joinedload(BloodDistribution.dispatched_to),
                joinedload(BloodDistribution.created_by),
                joinedload(BloodDistribution.inventory_item),
            )
            .where(BloodDistribution.id == distribution_id)
        )
        return result.scalar_one_or_none()

    async def update_distribution(
        self, distribution_id: UUID, update_data: BloodDistributionUpdate
    ) -> BloodDistribution:
        """
        Update a blood distribution record
        """
        distribution = await self.get_distribution(distribution_id)
        if not distribution:
            raise HTTPException(status_code=404, detail="Distribution not found")

        update_dict = update_data.model_dump(exclude_unset=True)

        # Save the old status before any changes
        old_status = distribution.status

        # Special handling for status changes
        if "status" in update_dict:
            new_status = update_dict["status"]

            # Validate status transition using model validation
            try:
                # Store the current status before attempting change
                original_status = distribution.status
                # Set the new status to trigger validation
                distribution.status = new_status
                # If we get here, validation passed
            except ValueError as e:
                # Reset to original status and raise HTTP exception
                distribution.status = original_status
                raise HTTPException(status_code=400, detail=str(e))

            # Auto-update date_dispatched when status changes to in_transit (only if not provided)
            if (
                new_status == DistributionStatus.IN_TRANSIT
                and old_status == DistributionStatus.PENDING_RECEIVE
                and "date_dispatched" not in update_dict
            ):
                distribution.date_dispatched = datetime.now()

            # Auto-update date_delivered when status changes to delivered (only if not provided)
            if (
                new_status == DistributionStatus.DELIVERED
                and old_status != DistributionStatus.DELIVERED
                and "date_delivered" not in update_dict
            ):
                distribution.date_delivered = datetime.now()

            # Update related request processing status if request exists
            if distribution.request_id:
                await self._update_request_processing_status(distribution)

            # Handle returns - add back to inventory if marked as returned
            if (
                new_status == DistributionStatus.RETURNED
                and distribution.blood_product_id
            ):
                inventory_result = await self.db.execute(
                    select(BloodInventory).where(
                        BloodInventory.id == distribution.blood_product_id
                    )
                )
                inventory_item = inventory_result.scalar_one_or_none()

                if inventory_item:
                    inventory_item.quantity += distribution.quantity
                else:
                    # Create a new inventory entry if the original was deleted
                    new_inventory = BloodInventory(
                        blood_product=distribution.blood_product,
                        blood_type=distribution.blood_type,
                        quantity=distribution.quantity,
                        blood_bank_id=distribution.dispatched_from_id,
                        added_by_id=distribution.created_by_id,
                        expiry_date=distribution.expiry_date,
                    )
                    self.db.add(new_inventory)

        # Update fields in the correct order to avoid validation conflicts
        # First update status if it's being changed
        if "status" in update_dict:
            setattr(distribution, "status", update_dict["status"])

        # Then update other allowed fields (notes, etc.)
        for field, value in update_dict.items():
            if field != "status":  # Skip status as it's already updated
                setattr(distribution, field, value)
        # Map distribution status to track state status
        status_mapping = {
            "pending receive": TrackStateStatus.PENDING_RECEIVE,
            "in transit": TrackStateStatus.DISPATCHED,
            "delivered": TrackStateStatus.RECEIVED,
            "returned": TrackStateStatus.RETURNED,
            "cancelled": TrackStateStatus.CANCELLED,
        }

        track_state = None
        if old_status != distribution.status:
            mapped_status = status_mapping.get(
                distribution.status.value, TrackStateStatus.PENDING_RECEIVE
            )

            # Choose location based on status
            if mapped_status in [
                TrackStateStatus.PENDING_RECEIVE,
                TrackStateStatus.DISPATCHED,
            ]:
                location = (
                    distribution.dispatched_from.blood_bank_name
                    if distribution.dispatched_from
                    else None
                )
            else:
                location = (
                    distribution.dispatched_to.facility_name
                    if distribution.dispatched_to
                    else None
                )

            track_state = TrackState(
                blood_distribution_id=distribution.id,
                blood_request_id=distribution.request_id,  # Use request_id instead of blood_product_id
                status=mapped_status,
                location=location,
                notes=f"Distribution status changed from {old_status.value} to {distribution.status.value}",
                created_by_id=distribution.created_by_id,
            )
            self.db.add(track_state)
        await self.db.commit()
        await self.db.refresh(distribution)

        # IMPORTANT: Refresh dashboard metrics when status changes to DELIVERED
        # This ensures the "transferred" count updates immediately
        if (
            new_status == DistributionStatus.DELIVERED
            and old_status != DistributionStatus.DELIVERED
        ):
            try:
                from app.services.dashboard_service import (
                    async_refresh_facility_dashboard_metrics,
                )

                # Refresh for the facility that dispatched (their transferred count increased)
                if (
                    distribution.dispatched_from
                    and distribution.dispatched_from.facility_id
                ):
                    asyncio.create_task(
                        async_refresh_facility_dashboard_metrics(
                            distribution.dispatched_from.facility_id
                        )
                    )
                # Refresh for the facility that received (they got new stock)
                if distribution.dispatched_to_id:
                    asyncio.create_task(
                        async_refresh_facility_dashboard_metrics(
                            distribution.dispatched_to_id
                        )
                    )
            except Exception as dashboard_error:
                # Don't fail the operation if dashboard refresh scheduling fails
                logger.warning(
                    f"Failed to schedule dashboard refresh after delivery: {dashboard_error}"
                )

        return distribution

    async def delete_distribution(self, distribution_id: UUID) -> bool:
        """
        Delete a distribution and restore inventory if necessary
        """
        distribution = await self.get_distribution(distribution_id)
        if not distribution:
            raise HTTPException(status_code=404, detail="Distribution not found")

        # Only allow deletion of pending distributions
        if distribution.status != DistributionStatus.PENDING_RECEIVE:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete distribution with status: {distribution.status.value}. Only pending distributions can be deleted.",
            )

        # If linked to inventory, restore the quantity
        if distribution.blood_product_id:
            inventory_result = await self.db.execute(
                select(BloodInventory).where(
                    BloodInventory.id == distribution.blood_product_id
                )
            )
            inventory_item = inventory_result.scalar_one_or_none()

            if inventory_item:
                inventory_item.quantity += distribution.quantity

        await self.db.delete(distribution)
        await self.db.commit()
        return True

    async def get_all_distributions(self) -> List[BloodDistribution]:
        """
        Get all distributions with their relationships
        """
        result = await self.db.execute(
            select(BloodDistribution)
            .options(
                joinedload(BloodDistribution.dispatched_from),
                joinedload(BloodDistribution.dispatched_to),
                joinedload(BloodDistribution.created_by),
                joinedload(BloodDistribution.inventory_item),
            )
            .order_by(desc(BloodDistribution.created_at))
        )
        return result.scalars().all()

    async def get_distributions_by_blood_bank(
        self, blood_bank_id: UUID
    ) -> List[BloodDistribution]:
        """
        Get all distributions from a specific blood bank
        """
        result = await self.db.execute(
            select(BloodDistribution)
            .options(
                joinedload(BloodDistribution.dispatched_from),
                joinedload(BloodDistribution.dispatched_to),
                joinedload(BloodDistribution.created_by),
                joinedload(BloodDistribution.inventory_item),
            )
            .where(BloodDistribution.dispatched_from_id == blood_bank_id)
            .order_by(desc(BloodDistribution.created_at))
        )
        return result.scalars().all()

    async def get_distributions_by_facility(
        self, facility_id: UUID
    ) -> List[BloodDistribution]:
        """
        Get all distributions to a specific facility
        """
        result = await self.db.execute(
            select(BloodDistribution)
            .options(
                joinedload(BloodDistribution.dispatched_from),
                joinedload(BloodDistribution.dispatched_to),
                joinedload(BloodDistribution.created_by),
                joinedload(BloodDistribution.inventory_item),
            )
            .where(BloodDistribution.dispatched_to_id == facility_id)
            .order_by(desc(BloodDistribution.created_at))
        )
        return result.scalars().all()

    async def get_distributions_by_status(
        self, status: DistributionStatus
    ) -> List[BloodDistribution]:
        """
        Get all distributions with a specific status
        """
        result = await self.db.execute(
            select(BloodDistribution)
            .options(
                joinedload(BloodDistribution.dispatched_from),
                joinedload(BloodDistribution.dispatched_to),
                joinedload(BloodDistribution.created_by),
                joinedload(BloodDistribution.inventory_item),
            )
            .where(BloodDistribution.status == status)
            .order_by(desc(BloodDistribution.created_at))
        )
        return result.scalars().all()

    async def get_recent_distributions(self, days: int = 7) -> List[BloodDistribution]:
        """
        Get distributions created in the past X days
        """
        date_threshold = datetime.now() - timedelta(days=days)

        result = await self.db.execute(
            select(BloodDistribution)
            .options(
                joinedload(BloodDistribution.dispatched_from),
                joinedload(BloodDistribution.dispatched_to),
                joinedload(BloodDistribution.created_by),
                joinedload(BloodDistribution.inventory_item),
            )
            .where(BloodDistribution.created_at >= date_threshold)
            .order_by(desc(BloodDistribution.created_at))
        )
        return result.scalars().all()

    async def get_distribution_stats(
        self, blood_bank_id: Optional[UUID] = None
    ) -> DistributionStats:
        """
        Get distribution statistics, optionally filtered by blood bank
        """
        query = select(
            func.count().label("total"),
            func.sum(
                BloodDistribution.status == DistributionStatus.PENDING_RECEIVE
            ).label("pending"),
            func.sum(BloodDistribution.status == DistributionStatus.IN_TRANSIT).label(
                "in_transit"
            ),
            func.sum(BloodDistribution.status == DistributionStatus.DELIVERED).label(
                "delivered"
            ),
            func.sum(BloodDistribution.status == DistributionStatus.CANCELLED).label(
                "cancelled"
            ),
            func.sum(BloodDistribution.status == DistributionStatus.RETURNED).label(
                "returned"
            ),
        )

        if blood_bank_id:
            query = query.where(BloodDistribution.dispatched_from_id == blood_bank_id)

        result = await self.db.execute(query)
        stats = result.one()

        return DistributionStats(
            total_distributions=stats.total or 0,
            pending_count=stats.pending or 0,
            in_transit_count=stats.in_transit or 0,
            delivered_count=stats.delivered or 0,
            cancelled_count=stats.cancelled or 0,
            returned_count=stats.returned or 0,
        )

    async def validate_distribution_safety(
        self, distribution: BloodDistribution
    ) -> bool:
        """Validate that a distribution is safe to proceed."""
        if not distribution.is_product_safe_for_distribution():
            return False
        return True

    async def get_distributions_by_request(
        self, request_id: UUID
    ) -> List[BloodDistribution]:
        """Get all distributions for a specific blood request."""
        result = await self.db.execute(
            select(BloodDistribution)
            .options(
                joinedload(BloodDistribution.dispatched_from),
                joinedload(BloodDistribution.dispatched_to),
                joinedload(BloodDistribution.created_by),
            )
            .where(BloodDistribution.request_id == request_id)
            .order_by(desc(BloodDistribution.created_at))
        )
        return result.scalars().all()

    async def get_expiring_distributions(
        self, days_ahead: int = 7, blood_bank_id: Optional[UUID] = None
    ) -> List[BloodDistribution]:
        """Get distributions with products expiring within specified days."""
        from datetime import date, timedelta

        cutoff_date = date.today() + timedelta(days=days_ahead)

        query = (
            select(BloodDistribution)
            .options(
                joinedload(BloodDistribution.dispatched_from),
                joinedload(BloodDistribution.dispatched_to),
            )
            .where(
                and_(
                    BloodDistribution.expiry_date <= cutoff_date,
                    BloodDistribution.status.in_(
                        [
                            DistributionStatus.PENDING_RECEIVE,
                            DistributionStatus.IN_TRANSIT,
                        ]
                    ),
                )
            )
        )

        if blood_bank_id:
            query = query.where(BloodDistribution.dispatched_from_id == blood_bank_id)

        result = await self.db.execute(query)
        return result.scalars().all()

    async def _update_request_processing_status(self, distribution: BloodDistribution):
        """Update the related blood request's processing status when distribution is created/updated."""
        if not distribution.request_id:
            return

        # Import here to avoid circular imports
        from app.models.request_model import BloodRequest

        # Get the related blood request
        result = await self.db.execute(
            select(BloodRequest)
            .options(selectinload(BloodRequest.distributions))
            .where(BloodRequest.id == distribution.request_id)
        )
        blood_request = result.scalar_one_or_none()

        if not blood_request:
            return

        # Determine the new processing status based on distribution status
        old_status = blood_request.processing_status

        if distribution.status == DistributionStatus.PENDING_RECEIVE:
            new_status = ProcessingStatus.INITIATED
        elif distribution.status == DistributionStatus.IN_TRANSIT:
            new_status = ProcessingStatus.DISPATCHED
        elif distribution.status == DistributionStatus.DELIVERED:
            new_status = ProcessingStatus.COMPLETED
        elif distribution.status in [
            DistributionStatus.CANCELLED,
            DistributionStatus.RETURNED,
        ]:
            new_status = ProcessingStatus.PENDING
        else:
            return  # No status change needed

        # Only update if status is actually changing
        if old_status != new_status:
            blood_request.processing_status = new_status

            # Create tracking record for the status change
            track_state = TrackState(
                blood_request_id=blood_request.id,
                blood_distribution_id=distribution.id,
                status=self._map_processing_to_track_status(new_status),
                location=(
                    distribution.dispatched_to.facility_name
                    if distribution.dispatched_to
                    else "Unknown Location"
                ),
                notes=f"Processing status automatically updated from {old_status.value} to {new_status.value}",
                created_by_id=distribution.created_by_id,
            )
            self.db.add(track_state)

    def _map_processing_to_track_status(self, processing_status):
        """Map processing status to track state status."""
        mapping = {
            ProcessingStatus.PENDING: TrackStateStatus.PENDING_RECEIVE,
            ProcessingStatus.INITIATED: TrackStateStatus.PENDING_RECEIVE,
            ProcessingStatus.DISPATCHED: TrackStateStatus.DISPATCHED,
            ProcessingStatus.COMPLETED: TrackStateStatus.RECEIVED,
        }
        return mapping.get(processing_status, TrackStateStatus.PENDING_RECEIVE)
