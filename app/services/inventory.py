from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from sqlalchemy import distinct, func, and_, or_
from fastapi import HTTPException, status
from uuid import UUID
from app.models.inventory import BloodInventory
from app.models.health_facility import Facility
from app.models.blood_bank import BloodBank
from app.schemas.inventory import (
    BloodInventoryCreate, 
    BloodInventoryUpdate, 
    PaginationParams,
    PaginatedResponse,
    FacilityWithBloodAvailability
)
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import asyncio
from contextlib import asynccontextmanager


class BloodInventoryService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.batch_size = 1000  # Default batch size for operations

    @asynccontextmanager
    async def batch_transaction(self):
        """Context manager for batch operations with proper transaction handling"""
        try:
            yield
            await self.db.commit()
        except Exception as e:
            await self.db.rollback()
            raise e

    async def create_blood_unit(
            self, 
            blood_data: BloodInventoryCreate, 
            blood_bank_id: UUID, 
            added_by_id: UUID
        ) -> BloodInventory:

        """Create a new blood unit inventory entry"""
        # expiry_date = date.today() + timedelta(days=blood_data.expires_in_days)
        new_blood_unit = BloodInventory(
            **blood_data.model_dump(),#exclude={"expires_in_days"}),
            # expiry_date=expiry_date,
            blood_bank_id=blood_bank_id,
            added_by_id=added_by_id
        )

        self.db.add(new_blood_unit)
        await self.db.commit()
        await self.db.refresh(new_blood_unit)
        
        # Load relationships efficiently
        await self.db.refresh(new_blood_unit, attribute_names=["blood_bank", "added_by"])
        
        return new_blood_unit
        
    async def get_facilities_with_available_blood(
        self,
        blood_type: str,
        blood_product: str,
        pagination: PaginationParams
    ) -> PaginatedResponse[FacilityWithBloodAvailability]:
        """
        Get paginated list of unique facilities with available blood inventory
        matching the specified type and product.
        """
        # Validate blood type and product
        self._validate_blood_attributes(blood_type, blood_product)

        # Build base query for counting total items
        count_query = select(func.count(distinct(Facility.id)))\
            .select_from(Facility)\
            .join(BloodBank, Facility.id == BloodBank.facility_id)\
            .join(BloodInventory, BloodBank.id == BloodInventory.blood_bank_id)\
            .where(
                BloodInventory.blood_type == blood_type,
                BloodInventory.blood_product == blood_product,
                BloodInventory.quantity > 0,
                BloodInventory.expiry_date >= datetime.now().date()
            )

        # Get total count
        total_result = await self.db.execute(count_query)
        total_items = total_result.scalar()

        # Build main query with pagination
        query = select(
            Facility.id.label("facility_id"),
            Facility.facility_name
        ).distinct()\
         .select_from(Facility)\
         .join(BloodBank, Facility.id == BloodBank.facility_id)\
         .join(BloodInventory, BloodBank.id == BloodInventory.blood_bank_id)\
         .where(
             BloodInventory.blood_type == blood_type,
             BloodInventory.blood_product == blood_product,
             BloodInventory.quantity > 0,
             BloodInventory.expiry_date >= datetime.now().date()
         )

        # Apply sorting
        if pagination.sort_by and hasattr(Facility, pagination.sort_by):
            sort_field = getattr(Facility, pagination.sort_by)
            query = query.order_by(
                sort_field.desc() if pagination.sort_order.lower() == "desc" 
                else sort_field.asc()
            )
        else:
            query = query.order_by(Facility.facility_name.asc())

        # Apply pagination
        offset = (pagination.page - 1) * pagination.page_size
        query = query.offset(offset).limit(pagination.page_size)

        # Execute query
        result = await self.db.execute(query)
        facilities = result.mappings().all()

        # Calculate pagination metadata
        total_pages = (total_items + pagination.page_size - 1) // pagination.page_size
        has_next = pagination.page < total_pages
        has_prev = pagination.page > 1

        return PaginatedResponse(
            items=[FacilityWithBloodAvailability(**facility) for facility in facilities],
            total_items=total_items,
            total_pages=total_pages,
            current_page=pagination.page,
            page_size=pagination.page_size,
            has_next=has_next,
            has_prev=has_prev
        )

    def _validate_blood_attributes(self, blood_type: str, blood_product: str):
        """Helper method to validate blood type and product"""
        try:
            BloodInventoryCreate(
                blood_type=blood_type,
                blood_product=blood_product,
                quantity=1,
                expiry_date=datetime.now().date()
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e)
            )

    async def batch_create_blood_units(
            self,
            blood_units_data: List[BloodInventoryCreate],
            blood_bank_id: UUID,
            added_by_id: UUID
        ) -> List[BloodInventory]:
        """
        Batch create multiple blood units with optimized performance
        Uses bulk operations and chunked processing for large datasets
        """
        if not blood_units_data:
            return []

        created_units = []
        
        async with self.batch_transaction():
            # Process in chunks to avoid memory issues and optimize performance
            for i in range(0, len(blood_units_data), self.batch_size):
                chunk = blood_units_data[i:i + self.batch_size]
                
                # Create BloodInventory objects
                blood_units = [
                    BloodInventory(
                        **unit_data.model_dump(),
                        blood_bank_id=blood_bank_id,
                        added_by_id=added_by_id
                    )
                    for unit_data in chunk
                ]
                
                # Bulk insert for better performance
                self.db.add_all(blood_units)
                await self.db.flush()  # Flush to get IDs without committing
                
                # Collect created units
                created_units.extend(blood_units)
                
                # Optional: Add a small delay between chunks for very large batches
                if len(blood_units_data) > 5000:
                    await asyncio.sleep(0.01)
        
        return created_units

    async def batch_update_blood_units(
            self,
            updates: List[Dict[str, Any]]
        ) -> List[BloodInventory]:
        """
        Batch update multiple blood units
        Each update dict should contain 'id' and the fields to update
        """
        if not updates:
            return []

        updated_units = []
        
        async with self.batch_transaction():
            for update_batch in [
                
                updates[i:i + self.batch_size] 
                for i in range(0, len(updates), self.batch_size)
                
                ]:
                
                # Get all units to update in this batch
                unit_ids = [update['id'] for update in update_batch]
                result = await self.db.execute(
                    select(BloodInventory)
                    .options(joinedload(BloodInventory.blood_bank), 
                           joinedload(BloodInventory.added_by))
                    .where(BloodInventory.id.in_(unit_ids))
                )
                units = {unit.id: unit for unit in result.scalars().all()}
                
                # Apply updates
                for update_data in update_batch:
                    unit_id = update_data.pop('id')
                    if unit_id in units:
                        unit = units[unit_id]
                        for field, value in update_data.items():
                            setattr(unit, field, value)
                        updated_units.append(unit)
                
                await self.db.flush()

        return updated_units

    async def batch_delete_blood_units(self, unit_ids: List[UUID]) -> int:
        """
        Batch delete multiple blood units
        Returns the number of deleted units
        """
        if not unit_ids:
            return 0

        deleted_count = 0
        
        async with self.batch_transaction():
            for batch_ids in [

                unit_ids[i:i + self.batch_size] 
                for i in range(0, len(unit_ids), self.batch_size)
                
                ]:
                
                # Delete in batches
                result = await self.db.execute(
                    select(BloodInventory).where(BloodInventory.id.in_(batch_ids))
                )
                units_to_delete = result.scalars().all()
                
                for unit in units_to_delete:
                    await self.db.delete(unit)
                    deleted_count += 1

        return deleted_count

    async def get_blood_unit(self, blood_unit_id: UUID) -> Optional[BloodInventory]:
        """Get a blood unit by ID with optimized loading"""
        result = await self.db.execute(
            select(BloodInventory)
            .options(
                joinedload(BloodInventory.blood_bank),
                joinedload(BloodInventory.added_by)
            )
            .where(BloodInventory.id == blood_unit_id)
        )
        return result.scalar_one_or_none()

    async def update_blood_unit(self, blood_unit_id: UUID, blood_data: BloodInventoryUpdate) -> BloodInventory:
        """Update a blood unit"""
        blood_unit = await self.get_blood_unit(blood_unit_id)
        if not blood_unit:
            raise HTTPException(status_code=404, detail="Blood unit not found")

        update_data = blood_data.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            setattr(blood_unit, field, value)

        await self.db.commit()
        await self.db.refresh(blood_unit)

        return blood_unit

    async def delete_blood_unit(self, blood_unit_id: UUID) -> bool:
        """Delete a blood unit"""
        blood_unit = await self.get_blood_unit(blood_unit_id)
        if not blood_unit:
            raise HTTPException(status_code=404, detail="Blood unit not found")

        await self.db.delete(blood_unit)
        await self.db.commit()
        return True

    async def get_paginated_blood_units(
            
            self,
            pagination: PaginationParams,
            blood_bank_id: Optional[UUID] = None,
            blood_type: Optional[str] = None,
            blood_product: Optional[str] = None,
            expiry_date_from: Optional[datetime] = None,
            expiry_date_to: Optional[datetime] = None,
            search_term: Optional[str] = None

        ) -> PaginatedResponse[BloodInventory]:
        """
        Get paginated blood units with comprehensive filtering and sorting
        """
        # Build base query with optimized joins
        query = select(BloodInventory).options(
            joinedload(BloodInventory.blood_bank),
            joinedload(BloodInventory.added_by)
        )

        # Apply filters
        conditions = []
        
        if blood_bank_id:
            conditions.append(BloodInventory.blood_bank_id == blood_bank_id)
        
        if blood_type:
            conditions.append(BloodInventory.blood_type == blood_type)
            
        if blood_product:
            conditions.append(BloodInventory.blood_product == blood_product)
            
        if expiry_date_from:
            conditions.append(BloodInventory.expiry_date >= expiry_date_from.date())
            
        if expiry_date_to:
            conditions.append(BloodInventory.expiry_date <= expiry_date_to.date())
            
        if search_term:
            search_conditions = [
                BloodInventory.blood_type.ilike(f"%{search_term}%"),
                BloodInventory.blood_product.ilike(f"%{search_term}%")
            ]
            conditions.append(or_(*search_conditions))

        if conditions:
            query = query.where(and_(*conditions))

        # Apply sorting
        if pagination.sort_by:
            sort_column = getattr(BloodInventory, pagination.sort_by, None)
            if sort_column:
                if pagination.sort_order.lower() == 'desc':
                    query = query.order_by(sort_column.desc())
                else:
                    query = query.order_by(sort_column.asc())
        else:
            # Default sort by creation date
            query = query.order_by(BloodInventory.created_at.desc())

        # Get total count for pagination metadata
        count_query = select(func.count()).select_from(
            query.subquery()
        )
        total_result = await self.db.execute(count_query)
        total_items = total_result.scalar()

        # Apply pagination
        offset = (pagination.page - 1) * pagination.page_size
        query = query.offset(offset).limit(pagination.page_size)

        # Execute query
        result = await self.db.execute(query)
        items = result.scalars().all()

        # Calculate pagination metadata
        total_pages = (total_items + pagination.page_size - 1) // pagination.page_size
        has_next = pagination.page < total_pages
        has_prev = pagination.page > 1

        return PaginatedResponse(
            items=items,
            total_items=total_items,
            total_pages=total_pages,
            current_page=pagination.page,
            page_size=pagination.page_size,
            has_next=has_next,
            has_prev=has_prev
        )

    async def get_blood_units_by_bank(
            self, 
            blood_bank_id: UUID,
            pagination: Optional[PaginationParams] = None
        ) -> List[BloodInventory] | PaginatedResponse[BloodInventory]:
        """Get blood units by bank with optional pagination"""
        if pagination:
            return await self.get_paginated_blood_units(
                pagination=pagination,
                blood_bank_id=blood_bank_id
            )
        
        # Non-paginated version for backward compatibility
        result = await self.db.execute(
            select(BloodInventory)
            .options(joinedload(BloodInventory.blood_bank), joinedload(BloodInventory.added_by))
            .where(BloodInventory.blood_bank_id == blood_bank_id)
            .order_by(BloodInventory.created_at.desc())
        )
        return result.scalars().all()
    
    async def get_expiring_blood_units(
            self, 
            days: int = 7,
            pagination: Optional[PaginationParams] = None
            ) -> List[BloodInventory] | PaginatedResponse[BloodInventory]:
        """Get blood units expiring in the next X days with optional pagination"""
        expiry_threshold = datetime.now().date() + timedelta(days=days)
        
        if pagination:
            return await self.get_paginated_blood_units(
                pagination=pagination,
                expiry_date_to=datetime.combine(expiry_threshold, datetime.min.time())
            )
        
        # Non-paginated version
        result = await self.db.execute(
            select(BloodInventory)
            .options(joinedload(BloodInventory.blood_bank), joinedload(BloodInventory.added_by))
            .where(BloodInventory.expiry_date <= expiry_threshold)
            .order_by(BloodInventory.expiry_date)
        )
        return result.scalars().all()

    async def get_blood_units_by_type(self, 
                                    blood_type: str,
                                    pagination: Optional[PaginationParams] = None) -> List[BloodInventory] | PaginatedResponse[BloodInventory]:
        """Get blood units by type with optional pagination"""
        if pagination:
            return await self.get_paginated_blood_units(
                pagination=pagination,
                blood_type=blood_type
            )
        
        # Non-paginated version
        result = await self.db.execute(
            select(BloodInventory)
            .options(joinedload(BloodInventory.blood_bank), joinedload(BloodInventory.added_by))
            .where(BloodInventory.blood_type == blood_type)
            .order_by(BloodInventory.created_at.desc())
        )
        return result.scalars().all()

    async def get_inventory_statistics(self, blood_bank_id: Optional[UUID] = None) -> Dict[str, Any]:
        """
        Get comprehensive inventory statistics with efficient aggregation
        """
        base_query = select(BloodInventory)
        
        if blood_bank_id:
            base_query = base_query.where(BloodInventory.blood_bank_id == blood_bank_id)

        # Total units and quantity
        total_stats = await self.db.execute(
            select(
                func.count(BloodInventory.id).label('total_units'),
                func.sum(BloodInventory.quantity).label('total_quantity')
            ).select_from(base_query.subquery())
        )
        total_result = total_stats.first()

        # Blood type distribution
        blood_type_stats = await self.db.execute(
            select(
                BloodInventory.blood_type,
                func.count(BloodInventory.id).label('units'),
                func.sum(BloodInventory.quantity).label('quantity')
            )
            .select_from(base_query.subquery())
            .group_by(BloodInventory.blood_type)
            .order_by(BloodInventory.blood_type)
        )

        # Blood product distribution
        product_stats = await self.db.execute(
            select(
                BloodInventory.blood_product,
                func.count(BloodInventory.id).label('units'),
                func.sum(BloodInventory.quantity).label('quantity')
            )
            .select_from(base_query.subquery())
            .group_by(BloodInventory.blood_product)
            .order_by(BloodInventory.blood_product)
        )

        # Expiring units (next 7 days)
        expiry_threshold = datetime.now().date() + timedelta(days=7)
        expiring_stats = await self.db.execute(
            select(
                func.count(BloodInventory.id).label('expiring_units'),
                func.sum(BloodInventory.quantity).label('expiring_quantity')
            ).select_from(
                base_query.where(BloodInventory.expiry_date <= expiry_threshold).subquery()
            )
        )
        expiring_result = expiring_stats.first()

        return {
            'total_units': total_result.total_units or 0,
            'total_quantity': total_result.total_quantity or 0,
            'blood_type_distribution': [
                {
                    'blood_type': row.blood_type,
                    'units': row.units,
                    'quantity': row.quantity
                }
                for row in blood_type_stats.all()
            ],
            'product_distribution': [
                {
                    'product': row.blood_product,
                    'units': row.units,  
                    'quantity': row.quantity
                }
                for row in product_stats.all()
            ],
            'expiring_soon': {
                'units': expiring_result.expiring_units or 0,
                'quantity': expiring_result.expiring_quantity or 0
            }
        }