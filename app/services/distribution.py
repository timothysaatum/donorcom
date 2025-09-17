from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, and_, desc
from sqlalchemy.orm import joinedload, selectinload
from fastapi import HTTPException
from uuid import UUID
from datetime import datetime, timedelta
from typing import Optional, List
import random
import string
from app.models.distribution import BloodDistribution
from app.models.inventory import BloodInventory
from app.schemas.distribution import (
    BloodDistributionCreate,
    BloodDistributionUpdate,
    DistributionStats,
    DistributionStatus,
)
from app.models.tracking_model import TrackState
from app.schemas.tracking_schema import TrackStateStatus
from app.schemas.request import ProcessingStatus


def generate_tracking_number(length=12):
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


def generate_batch_number():
    """Generate a unique batch number in format YYYYMMDD-XXXX"""
    date_part = datetime.now().strftime("%Y%m%d")
    random_part = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"{date_part}-{random_part}"


def calculate_expiry_date(blood_product: str) -> datetime.date:
    """Calculate expiry date based on blood product type"""
    # Standard shelf life for different blood products (in days)
    shelf_life_days = {
        "whole blood": 35,
        "red blood cells": 42,
        "packed red blood cells": 42,
        "platelets": 5,
        "plasma": 365,
        "fresh frozen plasma": 365,
        "cryoprecipitate": 365,
    }

    # Default to 35 days if product type not found
    days = shelf_life_days.get(blood_product.lower(), 35)
    return (datetime.now() + timedelta(days=days)).date()


class BloodDistributionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_distribution(
        self,
        distribution_data: BloodDistributionCreate,
        blood_bank_id: UUID,
        created_by_id: UUID,
    ) -> BloodDistribution:
        """
        Create a new blood distribution record and update inventory
        """
        # If blood_product_id is provided, verify it exists and belongs to this blood bank
        if distribution_data.blood_product_id:
            inventory_result = await self.db.execute(
                select(BloodInventory).where(
                    and_(
                        BloodInventory.id == distribution_data.blood_product_id,
                        BloodInventory.blood_bank_id == blood_bank_id,
                    )
                )
            )
            inventory_item = inventory_result.scalar_one_or_none()

            if not inventory_item:
                raise HTTPException(
                    status_code=404,
                    detail="Blood inventory item not found or does not belong to your blood bank",
                )

            # Check if there's enough quantity
            if inventory_item.quantity < distribution_data.quantity:
                raise HTTPException(
                    status_code=400,
                    detail=f"Insufficient quantity available. Requested: {distribution_data.quantity}, Available: {inventory_item.quantity}",
                )

            # Update inventory quantity
            inventory_item.quantity -= distribution_data.quantity

            # Use blood product and type from inventory
            blood_product = inventory_item.blood_product
            blood_type = inventory_item.blood_type
        else:
            # Using the values provided in the request
            blood_product = distribution_data.blood_product
            blood_type = distribution_data.blood_type

        # Create distribution record
        new_distribution = BloodDistribution(
            blood_product_id=distribution_data.blood_product_id,
            request_id=distribution_data.request_id,
            dispatched_from_id=blood_bank_id,
            dispatched_to_id=distribution_data.dispatched_to_id,
            created_by_id=created_by_id,
            blood_product=blood_product,
            blood_type=blood_type,
            quantity=distribution_data.quantity,
            notes=distribution_data.notes,
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
            status=TrackStateStatus.pending_receive,
            location=new_distribution.dispatched_from.blood_bank_name,
            notes="Distribution created, awaiting dispatch",
            created_by_id=created_by_id,
        )
        # Add the tracking state
        self.db.add(track_state)

        # Update related blood request processing status to "initiated"
        await self._update_request_processing_status(new_distribution)

        await self.db.commit()

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
                new_status == DistributionStatus.in_transit
                and old_status == DistributionStatus.pending_receive
                and "date_dispatched" not in update_dict
            ):
                distribution.date_dispatched = datetime.now()

            # Auto-update date_delivered when status changes to delivered (only if not provided)
            if (
                new_status == DistributionStatus.delivered
                and old_status != DistributionStatus.delivered
                and "date_delivered" not in update_dict
            ):
                distribution.date_delivered = datetime.now()

            # Update related request processing status if request exists
            if distribution.request_id:
                await self._update_request_processing_status(distribution)

            # Handle returns - add back to inventory if marked as returned
            if (
                new_status == DistributionStatus.returned
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
                        # Set a reasonable expiry date
                        expiry_date=(datetime.now() + timedelta(days=30)).date(),
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

        # await self.db.commit()
        # await self.db.refresh(distribution)

        status_mapping = {
            "pending receive": TrackStateStatus.pending_receive,
            "in transit": TrackStateStatus.dispatched,
            "delivered": TrackStateStatus.received,
            "returned": TrackStateStatus.returned,
            "cancelled": TrackStateStatus.cancelled,
        }

        track_state = None
        if old_status != distribution.status:
            mapped_status = status_mapping.get(
                distribution.status.value, TrackStateStatus.pending_receive
            )

            # Choose location based on status
            if mapped_status in [
                TrackStateStatus.pending_receive,
                TrackStateStatus.dispatched,
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

        return distribution

    async def delete_distribution(self, distribution_id: UUID) -> bool:
        """
        Delete a distribution and restore inventory if necessary
        """
        distribution = await self.get_distribution(distribution_id)
        if not distribution:
            raise HTTPException(status_code=404, detail="Distribution not found")

        # Only allow deletion of pending distributions
        if distribution.status != DistributionStatus.pending_receive:
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
                BloodDistribution.status == DistributionStatus.pending_receive
            ).label("pending"),
            func.sum(BloodDistribution.status == DistributionStatus.in_transit).label(
                "in_transit"
            ),
            func.sum(BloodDistribution.status == DistributionStatus.delivered).label(
                "delivered"
            ),
            func.sum(BloodDistribution.status == DistributionStatus.cancelled).label(
                "cancelled"
            ),
            func.sum(BloodDistribution.status == DistributionStatus.returned).label(
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
                            DistributionStatus.pending_receive,
                            DistributionStatus.in_transit,
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
        from app.models.request import BloodRequest

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

        if distribution.status == DistributionStatus.pending_receive:
            new_status = ProcessingStatus.initiated
        elif distribution.status == DistributionStatus.in_transit:
            new_status = ProcessingStatus.dispatched
        elif distribution.status == DistributionStatus.delivered:
            new_status = ProcessingStatus.completed
        elif distribution.status in [
            DistributionStatus.cancelled,
            DistributionStatus.returned,
        ]:
            new_status = ProcessingStatus.pending
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
            ProcessingStatus.pending: TrackStateStatus.pending_receive,
            ProcessingStatus.initiated: TrackStateStatus.pending_receive,
            ProcessingStatus.dispatched: TrackStateStatus.dispatched,
            ProcessingStatus.completed: TrackStateStatus.received,
        }
        return mapping.get(processing_status, TrackStateStatus.pending_receive)
