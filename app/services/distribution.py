# from sqlalchemy.ext.asyncio import AsyncSession
# from sqlalchemy.future import select
# from sqlalchemy import func, and_, or_, desc
# from sqlalchemy.orm import selectinload, joinedload
# from fastapi import HTTPException
# from uuid import UUID
# from datetime import datetime, timedelta
# from typing import Optional, List, Dict, Any, Tuple

# from app.models.distribution import BloodDistribution, BloodDistributionStatus
# from app.models.inventory import BloodInventory
# from app.schemas.distribution import BloodDistributionCreate, BloodDistributionUpdate, DistributionStats


# class BloodDistributionService:
#     def __init__(self, db: AsyncSession):
#         self.db = db

#     async def create_distribution(self,
#                                 distribution_data: BloodDistributionCreate,
#                                 blood_bank_id: UUID,
#                                 created_by_id: UUID) -> BloodDistribution:
#         """
#         Create a new blood distribution record and update inventory
#         """
#         # Start a transaction
#         async with self.db.begin():
#             # If blood_product_id is provided, verify it exists and belongs to this blood bank
#             if distribution_data.blood_product_id:
#                 inventory_result = await self.db.execute(
#                     select(BloodInventory).where(
#                         and_(
#                             BloodInventory.id == distribution_data.blood_product_id,
#                             BloodInventory.blood_bank_id == blood_bank_id
#                         )
#                     )
#                 )
#                 inventory_item = inventory_result.scalar_one_or_none()
                
#                 if not inventory_item:
#                     raise HTTPException(status_code=404, detail="Blood inventory item not found or does not belong to your blood bank")
                
#                 # Check if there's enough quantity
#                 if inventory_item.quantity < distribution_data.quantity:
#                     raise HTTPException(status_code=400, detail=f"Insufficient quantity available. Requested: {distribution_data.quantity}, Available: {inventory_item.quantity}")
                
#                 # Update inventory quantity
#                 inventory_item.quantity -= distribution_data.quantity
                
#                 # Use blood product and type from inventory
#                 blood_product = inventory_item.blood_product
#                 blood_type = inventory_item.blood_type
#             else:
#                 # Using the values provided in the request
#                 blood_product = distribution_data.blood_product
#                 blood_type = distribution_data.blood_type
            
#             # Create distribution record
#             new_distribution = BloodDistribution(
#                 blood_product_id=distribution_data.blood_product_id,
#                 dispatched_from_id=blood_bank_id,
#                 dispatched_to_id=distribution_data.dispatched_to_id,
#                 created_by_id=created_by_id,
#                 blood_product=blood_product,
#                 blood_type=blood_type,
#                 quantity=distribution_data.quantity,
#                 notes=distribution_data.notes,
#                 tracking_number=distribution_data.tracking_number,
#                 # Status starts as pending by default
#             )
            
#             self.db.add(new_distribution)
        
#         # Transaction is automatically committed here if no exceptions
#         await self.db.refresh(new_distribution)
        
#         # Load relationships
#         await self.db.refresh(new_distribution, attribute_names=["dispatched_from", "dispatched_to", "created_by", "inventory_item"])
        
#         return new_distribution

#     async def get_distribution(self, distribution_id: UUID) -> Optional[BloodDistribution]:
#         """
#         Get a distribution by ID with all related data
#         """
#         result = await self.db.execute(
#             select(BloodDistribution)
#             .options(
#                 joinedload(BloodDistribution.dispatched_from),
#                 joinedload(BloodDistribution.dispatched_to),
#                 joinedload(BloodDistribution.created_by),
#                 joinedload(BloodDistribution.inventory_item)
#             )
#             .where(BloodDistribution.id == distribution_id)
#         )
#         return result.scalar_one_or_none()

#     async def update_distribution(self, distribution_id: UUID, update_data: BloodDistributionUpdate) -> BloodDistribution:
#         """
#         Update a blood distribution record
#         """
#         distribution = await self.get_distribution(distribution_id)
#         if not distribution:
#             raise HTTPException(status_code=404, detail="Distribution not found")

#         update_dict = update_data.model_dump(exclude_unset=True)
        
#         # Special handling for status changes
#         if 'status' in update_dict:
#             new_status = update_dict['status']
#             old_status = distribution.status
            
#             # Auto-update date_dispatched when status changes to in_transit
#             if new_status == BloodDistributionStatus.in_transit and old_status == BloodDistributionStatus.pending:
#                 distribution.date_dispatched = datetime.now()
            
#             # Auto-update date_delivered when status changes to delivered
#             if new_status == BloodDistributionStatus.delivered and old_status != BloodDistributionStatus.delivered:
#                 distribution.date_delivered = datetime.now()
                
#             # Handle returns - add back to inventory if marked as returned
#             if new_status == BloodDistributionStatus.returned and distribution.blood_product_id:
#                 inventory_result = await self.db.execute(
#                     select(BloodInventory).where(BloodInventory.id == distribution.blood_product_id)
#                 )
#                 inventory_item = inventory_result.scalar_one_or_none()
                
#                 if inventory_item:
#                     inventory_item.quantity += distribution.quantity
#                 else:
#                     # Create a new inventory entry if the original was deleted
#                     new_inventory = BloodInventory(
#                         blood_product=distribution.blood_product,
#                         blood_type=distribution.blood_type,
#                         quantity=distribution.quantity,
#                         blood_bank_id=distribution.dispatched_from_id,
#                         added_by_id=distribution.created_by_id,
#                         # Set a reasonable expiry date
#                         expiry_date=(datetime.now() + timedelta(days=30)).date()
#                     )
#                     self.db.add(new_inventory)
        
#         # Update all fields
#         for field, value in update_dict.items():
#             setattr(distribution, field, value)

#         await self.db.commit()
#         await self.db.refresh(distribution)
        
#         return distribution

#     async def delete_distribution(self, distribution_id: UUID) -> bool:
#         """
#         Delete a distribution and restore inventory if necessary
#         """
#         distribution = await self.get_distribution(distribution_id)
#         if not distribution:
#             raise HTTPException(status_code=404, detail="Distribution not found")
        
#         # Only allow deletion of pending distributions
#         if distribution.status != BloodDistributionStatus.pending:
#             raise HTTPException(
#                 status_code=400, 
#                 detail=f"Cannot delete distribution with status: {distribution.status.value}. Only pending distributions can be deleted."
#             )

#         # If linked to inventory, restore the quantity
#         if distribution.blood_product_id:
#             inventory_result = await self.db.execute(
#                 select(BloodInventory).where(BloodInventory.id == distribution.blood_product_id)
#             )
#             inventory_item = inventory_result.scalar_one_or_none()
            
#             if inventory_item:
#                 inventory_item.quantity += distribution.quantity
        
#         await self.db.delete(distribution)
#         await self.db.commit()
#         return True
        
#     async def get_all_distributions(self) -> List[BloodDistribution]:
#         """
#         Get all distributions with their relationships
#         """
#         result = await self.db.execute(
#             select(BloodDistribution)
#             .options(
#                 joinedload(BloodDistribution.dispatched_from),
#                 joinedload(BloodDistribution.dispatched_to),
#                 joinedload(BloodDistribution.created_by),
#                 joinedload(BloodDistribution.inventory_item)
#             )
#             .order_by(desc(BloodDistribution.created_at))
#         )
#         return result.scalars().all()

#     async def get_distributions_by_blood_bank(self, blood_bank_id: UUID) -> List[BloodDistribution]:
#         """
#         Get all distributions from a specific blood bank
#         """
#         result = await self.db.execute(
#             select(BloodDistribution)
#             .options(
#                 joinedload(BloodDistribution.dispatched_from),
#                 joinedload(BloodDistribution.dispatched_to),
#                 joinedload(BloodDistribution.created_by),
#                 joinedload(BloodDistribution.inventory_item)
#             )
#             .where(BloodDistribution.dispatched_from_id == blood_bank_id)
#             .order_by(desc(BloodDistribution.created_at))
#         )
#         return result.scalars().all()
    
#     async def get_distributions_by_facility(self, facility_id: UUID) -> List[BloodDistribution]:
#         """
#         Get all distributions to a specific facility
#         """
#         result = await self.db.execute(
#             select(BloodDistribution)
#             .options(
#                 joinedload(BloodDistribution.dispatched_from),
#                 joinedload(BloodDistribution.dispatched_to),
#                 joinedload(BloodDistribution.created_by),
#                 joinedload(BloodDistribution.inventory_item)
#             )
#             .where(BloodDistribution.dispatched_to_id == facility_id)
#             .order_by(desc(BloodDistribution.created_at))
#         )
#         return result.scalars().all()
    
#     async def get_distributions_by_status(self, status: BloodDistributionStatus) -> List[BloodDistribution]:
#         """
#         Get all distributions with a specific status
#         """
#         result = await self.db.execute(
#             select(BloodDistribution)
#             .options(
#                 joinedload(BloodDistribution.dispatched_from),
#                 joinedload(BloodDistribution.dispatched_to),
#                 joinedload(BloodDistribution.created_by),
#                 joinedload(BloodDistribution.inventory_item)
#             )
#             .where(BloodDistribution.status == status)
#             .order_by(desc(BloodDistribution.created_at))
#         )
#         return result.scalars().all()
    
#     async def get_recent_distributions(self, days: int = 7) -> List[BloodDistribution]:
#         """
#         Get distributions created in the past X days
#         """
#         date_threshold = datetime.now() - timedelta(days=days)
        
#         result = await self.db.execute(
#             select(BloodDistribution)
#             .options(
#                 joinedload(BloodDistribution.dispatched_from),
#                 joinedload(BloodDistribution.dispatched_to),
#                 joinedload(BloodDistribution.created_by),
#                 joinedload(BloodDistribution.inventory_item)
#             )
#             .where(BloodDistribution.created_at >= date_threshold)
#             .order_by(desc(BloodDistribution.created_at))
#         )
#         return result.scalars().all()
    
#     async def get_distribution_stats(self, blood_bank_id: Optional[UUID] = None) -> DistributionStats:
#         """
#         Get distribution statistics, optionally filtered by blood bank
#         """
#         query = select(
#             func.count().label("total"),
#             func.sum(BloodDistribution.status == BloodDistributionStatus.pending).label("pending"),
#             func.sum(BloodDistribution.status == BloodDistributionStatus.in_transit).label("in_transit"),
#             func.sum(BloodDistribution.status == BloodDistributionStatus.delivered).label("delivered"),
#             func.sum(BloodDistribution.status == BloodDistributionStatus.cancelled).label("cancelled"),
#             func.sum(BloodDistribution.status == BloodDistributionStatus.returned).label("returned")
#         )
        
#         if blood_bank_id:
#             query = query.where(BloodDistribution.dispatched_from_id == blood_bank_id)
            
#         result = await self.db.execute(query)
#         stats = result.one()
        
#         return DistributionStats(
#             total_distributions=stats.total or 0,
#             pending_count=stats.pending or 0,
#             in_transit_count=stats.in_transit or 0,
#             delivered_count=stats.delivered or 0,
#             cancelled_count=stats.cancelled or 0,
#             returned_count=stats.returned or 0
#         )
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, and_, or_, desc
from sqlalchemy.orm import selectinload, joinedload
from fastapi import HTTPException
from uuid import UUID
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple

from app.models.distribution import BloodDistribution, BloodDistributionStatus
from app.models.inventory import BloodInventory
from app.schemas.distribution import BloodDistributionCreate, BloodDistributionUpdate, DistributionStats

class BloodDistributionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_distribution(self,  
                                distribution_data: BloodDistributionCreate,  
                                blood_bank_id: UUID,  
                                created_by_id: UUID) -> BloodDistribution:  
        """  
        Create a new blood distribution record and update inventory  
        """  
        # Removed transaction context that caused the error
        
        # If blood_product_id is provided, verify it exists and belongs to this blood bank  
        if distribution_data.blood_product_id:  
            inventory_result = await self.db.execute(  
                select(BloodInventory).where(  
                    and_(  
                        BloodInventory.id == distribution_data.blood_product_id,  
                        BloodInventory.blood_bank_id == blood_bank_id  
                    )  
                )  
            )  
            inventory_item = inventory_result.scalar_one_or_none()  
              
            if not inventory_item:  
                raise HTTPException(status_code=404, detail="Blood inventory item not found or does not belong to your blood bank")  
              
            # Check if there's enough quantity  
            if inventory_item.quantity < distribution_data.quantity:  
                raise HTTPException(status_code=400, detail=f"Insufficient quantity available. Requested: {distribution_data.quantity}, Available: {inventory_item.quantity}")  
              
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
            dispatched_from_id=blood_bank_id,  
            dispatched_to_id=distribution_data.dispatched_to_id,  
            created_by_id=created_by_id,  
            blood_product=blood_product,  
            blood_type=blood_type,  
            quantity=distribution_data.quantity,  
            notes=distribution_data.notes,  
            tracking_number=distribution_data.tracking_number,  
            # Status starts as pending by default  
        )  
          
        self.db.add(new_distribution)  
      
        # Let the caller handle the commit if needed
        await self.db.flush()  
        await self.db.refresh(new_distribution)  
          
        # Load relationships  
        await self.db.refresh(new_distribution, attribute_names=["dispatched_from", "dispatched_to", "created_by", "inventory_item"])  
          
        return new_distribution  

    async def get_distribution(self, distribution_id: UUID) -> Optional[BloodDistribution]:  
        """  
        Get a distribution by ID with all related data  
        """  
        result = await self.db.execute(  
            select(BloodDistribution)  
            .options(  
                joinedload(BloodDistribution.dispatched_from),  
                joinedload(BloodDistribution.dispatched_to),  
                joinedload(BloodDistribution.created_by),  
                joinedload(BloodDistribution.inventory_item)  
            )  
            .where(BloodDistribution.id == distribution_id)  
        )  
        return result.scalar_one_or_none()  

    async def update_distribution(self, distribution_id: UUID, update_data: BloodDistributionUpdate) -> BloodDistribution:  
        """  
        Update a blood distribution record  
        """  
        distribution = await self.get_distribution(distribution_id)  
        if not distribution:  
            raise HTTPException(status_code=404, detail="Distribution not found")  

        update_dict = update_data.model_dump(exclude_unset=True)  
          
        # Special handling for status changes  
        if 'status' in update_dict:  
            new_status = update_dict['status']  
            old_status = distribution.status  
              
            # Auto-update date_dispatched when status changes to in_transit  
            if new_status == BloodDistributionStatus.in_transit and old_status == BloodDistributionStatus.pending:  
                distribution.date_dispatched = datetime.now()  
              
            # Auto-update date_delivered when status changes to delivered  
            if new_status == BloodDistributionStatus.delivered and old_status != BloodDistributionStatus.delivered:  
                distribution.date_delivered = datetime.now()  
                  
            # Handle returns - add back to inventory if marked as returned  
            if new_status == BloodDistributionStatus.returned and distribution.blood_product_id:  
                inventory_result = await self.db.execute(  
                    select(BloodInventory).where(BloodInventory.id == distribution.blood_product_id)  
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
                        expiry_date=(datetime.now() + timedelta(days=30)).date()  
                    )  
                    self.db.add(new_inventory)  
          
        # Update all fields  
        for field, value in update_dict.items():  
            setattr(distribution, field, value)  

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
        if distribution.status != BloodDistributionStatus.pending:  
            raise HTTPException(  
                status_code=400,   
                detail=f"Cannot delete distribution with status: {distribution.status.value}. Only pending distributions can be deleted."  
            )  

        # If linked to inventory, restore the quantity  
        if distribution.blood_product_id:  
            inventory_result = await self.db.execute(  
                select(BloodInventory).where(BloodInventory.id == distribution.blood_product_id)  
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
                joinedload(BloodDistribution.inventory_item)  
            )  
            .order_by(desc(BloodDistribution.created_at))  
        )  
        return result.scalars().all()  

    async def get_distributions_by_blood_bank(self, blood_bank_id: UUID) -> List[BloodDistribution]:  
        """  
        Get all distributions from a specific blood bank  
        """  
        result = await self.db.execute(  
            select(BloodDistribution)  
            .options(  
                joinedload(BloodDistribution.dispatched_from),  
                joinedload(BloodDistribution.dispatched_to),  
                joinedload(BloodDistribution.created_by),  
                joinedload(BloodDistribution.inventory_item)  
            )  
            .where(BloodDistribution.dispatched_from_id == blood_bank_id)  
            .order_by(desc(BloodDistribution.created_at))  
        )  
        return result.scalars().all()  
      
    async def get_distributions_by_facility(self, facility_id: UUID) -> List[BloodDistribution]:  
        """  
        Get all distributions to a specific facility  
        """  
        result = await self.db.execute(  
            select(BloodDistribution)  
            .options(  
                joinedload(BloodDistribution.dispatched_from),  
                joinedload(BloodDistribution.dispatched_to),  
                joinedload(BloodDistribution.created_by),  
                joinedload(BloodDistribution.inventory_item)  
            )  
            .where(BloodDistribution.dispatched_to_id == facility_id)  
            .order_by(desc(BloodDistribution.created_at))  
        )  
        return result.scalars().all()  
      
    async def get_distributions_by_status(self, status: BloodDistributionStatus) -> List[BloodDistribution]:  
        """  
        Get all distributions with a specific status  
        """  
        result = await self.db.execute(  
            select(BloodDistribution)  
            .options(  
                joinedload(BloodDistribution.dispatched_from),  
                joinedload(BloodDistribution.dispatched_to),  
                joinedload(BloodDistribution.created_by),  
                joinedload(BloodDistribution.inventory_item)  
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
                joinedload(BloodDistribution.inventory_item)  
            )  
            .where(BloodDistribution.created_at >= date_threshold)  
            .order_by(desc(BloodDistribution.created_at))  
        )  
        return result.scalars().all()  
      
    async def get_distribution_stats(self, blood_bank_id: Optional[UUID] = None) -> DistributionStats:  
        """  
        Get distribution statistics, optionally filtered by blood bank  
        """  
        query = select(  
            func.count().label("total"),  
            func.sum(BloodDistribution.status == BloodDistributionStatus.pending).label("pending"),  
            func.sum(BloodDistribution.status == BloodDistributionStatus.in_transit).label("in_transit"),  
            func.sum(BloodDistribution.status == BloodDistributionStatus.delivered).label("delivered"),  
            func.sum(BloodDistribution.status == BloodDistributionStatus.cancelled).label("cancelled"),  
            func.sum(BloodDistribution.status == BloodDistributionStatus.returned).label("returned")  
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
            returned_count=stats.returned or 0  
        )