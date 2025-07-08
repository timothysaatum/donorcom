from fastapi import APIRouter, Depends, HTTPException, status, Path, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.inventory import (
    BloodInventoryCreate, BloodInventoryResponse, BloodInventoryUpdate, 
    BloodInventoryDetailResponse, BloodInventoryBatchCreate, BloodInventoryBatchUpdate,
    BloodInventoryBatchDelete, PaginationParams, PaginatedResponse, BatchOperationResponse, InventoryStatistics,
    BloodInventorySearchParams,
    PaginatedFacilityResponse
)
from app.services.inventory import BloodInventoryService
from app.models.user import User
from app.models.inventory import BloodInventory
from app.models.health_facility import Facility
from app.utils.security import get_current_user
from app.dependencies import get_db
from uuid import UUID
from typing import List, Optional, Literal
from sqlalchemy.future import select
from app.models.blood_bank import BloodBank
from datetime import datetime
from sqlalchemy import or_
from sqlalchemy.orm import joinedload
import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/blood-inventory",
    tags=["blood inventory"]
)


async def get_user_blood_bank_id(db, user_id):
    """
    Returns just the blood bank ID (UUID) for the user.
    """
    result = await db.execute(
        select(BloodBank.id)  # ← Changed this line
        .join(Facility, BloodBank.facility_id == Facility.id)
        .where(
            (Facility.facility_manager_id == user_id) |
            (Facility.id.in_(
                select(User.work_facility_id).where(User.id == user_id)
            )) |
            (BloodBank.manager_id == user_id)
        )
    )
    
    return result.scalar()

# Create pagination dependency
def get_pagination_params(
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
    sort_by: Optional[str] = Query(None, description="Field to sort by"),
    sort_order: str = Query("desc", regex="^(asc|desc)$", description="Sort order")
) -> PaginationParams:
    return PaginationParams(
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order
    )


@router.post("/", response_model=BloodInventoryResponse, status_code=status.HTTP_201_CREATED)
async def create_blood_unit(
    blood_data: BloodInventoryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Add a new blood unit to inventory.
    The blood bank and user who added it are automatically assigned.
    """
    blood_bank_id = await get_user_blood_bank_id(db, current_user.id)
    
    blood_service = BloodInventoryService(db)
    new_blood_unit = await blood_service.create_blood_unit(
        blood_data=blood_data,
        blood_bank_id=blood_bank_id,
        added_by_id=current_user.id
    )

    return BloodInventoryResponse.model_validate(new_blood_unit, from_attributes=True)


@router.post("/batch", response_model=BatchOperationResponse, status_code=status.HTTP_201_CREATED)
async def batch_create_blood_units(
    batch_data: BloodInventoryBatchCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Batch create multiple blood units for improved performance.
    Handles up to 1000 units per request with transaction safety.
    """
    blood_bank_id = await get_user_blood_bank_id(db, current_user.id)
    blood_service = BloodInventoryService(db)
    
    try:
        created_units = await blood_service.batch_create_blood_units(
            blood_units_data=batch_data.blood_units,
            blood_bank_id=blood_bank_id,
            added_by_id=current_user.id
        )
        
        logger.info(f"Batch created {len(created_units)} blood units for bank {blood_bank_id}")
        
        return BatchOperationResponse(
            success=True,
            processed_count=len(created_units),
            created_ids=[unit.id for unit in created_units]
        )
    
    except Exception as e:
        logger.error(f"Batch create failed: {str(e)}")
        return BatchOperationResponse(
            success=False,
            processed_count=0,
            failed_count=len(batch_data.blood_units),
            errors=[str(e)]
        )
        
        
# @router.get("/facilities/search-stock", response_model=PaginatedFacilityResponse)
# async def get_facilities_with_available_blood(
#     blood_type: Literal["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"] = Query(
#         ..., 
#         description="Blood type to filter by (e.g., A+, B-)"
#     ),
#     blood_product: Literal["Whole Blood", "Red Blood Cells", "Plasma", "Platelets", "Cryoprecipitate"] = Query(
#         ..., 
#         description="Blood product to filter by (e.g., Whole Blood, Plasma)"
#     ),
#     pagination: PaginationParams = Depends(get_pagination_params),
#     db: AsyncSession = Depends(get_db)
# ):
#     """
#     Get paginated list of unique facilities that have available blood inventory 
#     matching the specified type and product.
#     Returns only facility ID and name for efficient response.
#     """
#     blood_service = BloodInventoryService(db)
#     try:
#         return await blood_service.get_facilities_with_available_blood(
#             blood_type=blood_type,
#             blood_product=blood_product,
#             pagination=pagination
#         )
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error fetching facilities with available blood: {str(e)}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail="Could not fetch facility data"
#         )
@router.get("/facilities/search-stock", response_model=PaginatedFacilityResponse)
async def get_facilities_with_available_blood(
    blood_type: Optional[str] = Query(
        None, 
        description="Blood type to filter by (e.g., A+, B-). If not provided, returns all blood types."
    ),
    blood_product: Optional[str] = Query(
        None, 
        description="Blood product to filter by (e.g., Whole Blood, Plasma). If not provided, returns all products."
    ),
    pagination: PaginationParams = Depends(get_pagination_params),
    db: AsyncSession = Depends(get_db)):
    """
    Get paginated list of unique facilities that have available blood inventory.
    If blood_type and blood_product are provided, filters by those criteria.
    If not provided, returns all facilities with any available blood inventory.
    Returns only facility ID and name for efficient response.
    """
    blood_service = BloodInventoryService(db)
    try:
        return await blood_service.get_facilities_with_available_blood(
            blood_type=blood_type,
            blood_product=blood_product,
            pagination=pagination
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching facilities with available blood: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch facility data"
        )


@router.patch("/batch", response_model=BatchOperationResponse)
async def batch_update_blood_units(
    batch_data: BloodInventoryBatchUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)):
    """
    Batch update multiple blood units.
    Each update must include the unit ID and fields to update.
    """
    blood_bank_id = await get_user_blood_bank_id(db, current_user.id)
    blood_service = BloodInventoryService(db)

    try:
        # Verify all units belong to the user's blood bank
        unit_ids = [update['id'] for update in batch_data.updates]
        
        # Check ownership
        result = await db.execute(
            select(BloodInventory.id, BloodInventory.blood_bank_id)
            .where(BloodInventory.id.in_(unit_ids))
        )
        units_check = result.all()
        
        unauthorized_units = [
            unit.id for unit in units_check 
            if unit.blood_bank_id != blood_bank_id
        ]
        
        if unauthorized_units:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"You don't have permission to update units: {unauthorized_units}"
            )
        
        updated_units = await blood_service.batch_update_blood_units(batch_data.updates)
        
        logger.info(f"Batch updated {len(updated_units)} blood units for bank {blood_bank_id}")
        
        return BatchOperationResponse(
            success=True,
            processed_count=len(updated_units)
        )
    
    except Exception as e:
        logger.error(f"Batch update failed: {str(e)}")
        return BatchOperationResponse(
            success=False,
            processed_count=0,
            failed_count=len(batch_data.updates),
            errors=[str(e)]
        )


@router.delete("/batch", response_model=BatchOperationResponse)
async def batch_delete_blood_units(
    batch_data: BloodInventoryBatchDelete,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Batch delete multiple blood units.
    User must own all units being deleted.
    """
    blood_bank_id = await get_user_blood_bank_id(db, current_user.id)
    blood_service = BloodInventoryService(db)
    
    try:
        # Verify ownership
        result = await db.execute(
            select(BloodInventory.id, BloodInventory.blood_bank_id)
            .where(BloodInventory.id.in_(batch_data.unit_ids))
        )
        units_check = result.all()
        
        unauthorized_units = [
            unit.id for unit in units_check 
            if unit.blood_bank_id != blood_bank_id
        ]
        
        if unauthorized_units:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"You don't have permission to delete units: {unauthorized_units}"
            )
        
        deleted_count = await blood_service.batch_delete_blood_units(batch_data.unit_ids)
        
        logger.info(f"Batch deleted {deleted_count} blood units for bank {blood_bank_id}")
        
        return BatchOperationResponse(
            success=True,
            processed_count=deleted_count
        )
    
    except Exception as e:
        logger.error(f"Batch delete failed: {str(e)}")
        return BatchOperationResponse(
            success=False,
            processed_count=0,
            failed_count=len(batch_data.unit_ids),
            errors=[str(e)]
        )


@router.get("/{blood_unit_id}", response_model=BloodInventoryDetailResponse)
async def get_blood_unit(
    blood_unit_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get details of a specific blood unit"""
    blood_service = BloodInventoryService(db)
    blood_unit = await blood_service.get_blood_unit(blood_unit_id)
    
    if not blood_unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Blood unit not found"
        )
    
    response = BloodInventoryDetailResponse(
        **BloodInventoryResponse.model_validate(blood_unit, from_attributes=True).model_dump(),
        blood_bank_name=blood_unit.blood_bank.blood_bank_name if blood_unit.blood_bank else None,
        added_by_name=blood_unit.added_by.last_name if blood_unit.added_by else None
    )
    
    return response


@router.get("/", response_model=PaginatedResponse[BloodInventoryDetailResponse])
async def facility_blood_inventory(
    pagination: PaginationParams = Depends(get_pagination_params),
    blood_type: Optional[str] = Query(None, description="Filter by blood type"),
    blood_product: Optional[str] = Query(None, description="Filter by blood product"),
    expiry_date_from: Optional[datetime] = Query(None, description="Filter by expiry date from"),
    expiry_date_to: Optional[datetime] = Query(None, description="Filter by expiry date to"),
    search_term: Optional[str] = Query(None, description="Search in blood type and product"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)):
    """
    List blood units with comprehensive pagination and filtering.
    Ensures the user is associated with a facility and blood bank.
    """
    # Get user's blood bank ID
    blood_bank_id = await get_user_blood_bank_id(db, current_user.id)

    if not blood_bank_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not belong to any facility or blood bank. Please contact admin."
        )

    # Proceed with fetching blood inventory
    blood_service = BloodInventoryService(db)

    result = await blood_service.get_paginated_blood_units(
        pagination=pagination,
        current_user_blood_bank_id=blood_bank_id,
        blood_type=blood_type,
        blood_product=blood_product,
        expiry_date_from=expiry_date_from,
        expiry_date_to=expiry_date_to,
        search_term=search_term
    )

    detailed_items = [
        BloodInventoryDetailResponse(
            **BloodInventoryResponse.model_validate(unit, from_attributes=True).model_dump(),
            blood_bank_name=unit.blood_bank.blood_bank_name if unit.blood_bank else None,
            added_by_name=unit.added_by.last_name if unit.added_by else None
        )
        for unit in result.items
    ]

    return PaginatedResponse(
        items=detailed_items,
        total_items=result.total_items,
        total_pages=result.total_pages,
        current_page=result.current_page,
        page_size=result.page_size,
        has_next=result.has_next,
        has_prev=result.has_prev
    )

    
@router.post("/advanced-search", response_model=PaginatedResponse[BloodInventoryDetailResponse])
async def advanced_search_blood_units(
    search_params: BloodInventorySearchParams,
    pagination: PaginationParams = Depends(get_pagination_params),
    db: AsyncSession = Depends(get_db)
):
    """
    Advanced search for blood units with multiple filter combinations.
    Supports complex queries and multiple selection criteria.
    """
    blood_service = BloodInventoryService(db)
    
    # Convert search params to service method parameters
    result = await blood_service.get_paginated_blood_units(
        pagination=pagination,
        blood_type=search_params.blood_types[0] if search_params.blood_types else None,
        blood_product=search_params.blood_products[0] if search_params.blood_products else None,
        expiry_date_from=datetime.combine(search_params.expiry_date_from, datetime.min.time()) if search_params.expiry_date_from else None,
        expiry_date_to=datetime.combine(search_params.expiry_date_to, datetime.min.time()) if search_params.expiry_date_to else None,
        search_term=search_params.search_term
    )
    
    # Additional filtering for complex criteria
    if search_params.blood_types and len(search_params.blood_types) > 1:
        result.items = [item for item in result.items if item.blood_type in search_params.blood_types]
    
    if search_params.blood_products and len(search_params.blood_products) > 1:
        result.items = [item for item in result.items if item.blood_product in search_params.blood_products]
    
    if search_params.min_quantity is not None:
        result.items = [item for item in result.items if item.quantity >= search_params.min_quantity]
    
    if search_params.max_quantity is not None:
        result.items = [item for item in result.items if item.quantity <= search_params.max_quantity]
    
    # Transform to detailed response
    detailed_items = [
        BloodInventoryDetailResponse(
            **BloodInventoryResponse.model_validate(unit, from_attributes=True).model_dump(),
            blood_bank_name=unit.blood_bank.blood_bank_name if unit.blood_bank else None,
            added_by_name=unit.added_by.last_name if unit.added_by else None
        )
        for unit in result.items
    ]
    
    return PaginatedResponse(
        items=detailed_items,
        total_items=len(detailed_items),
        total_pages=(len(detailed_items) + pagination.page_size - 1) // pagination.page_size,
        current_page=pagination.page,
        page_size=pagination.page_size,
        has_next=pagination.page * pagination.page_size < len(detailed_items),
        has_prev=pagination.page > 1
    )


@router.patch("/{blood_unit_id}", response_model=BloodInventoryResponse)
async def update_blood_unit(
    blood_unit_id: UUID,
    blood_data: BloodInventoryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update a blood unit.
    User must be associated with the blood bank that owns this unit.
    """
    blood_service = BloodInventoryService(db)
    blood_unit = await blood_service.get_blood_unit(blood_unit_id)
    
    if not blood_unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Blood unit not found"
        )
    
    user_blood_bank_id = await get_user_blood_bank_id(db, current_user.id)
    
    if blood_unit.blood_bank_id != user_blood_bank_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to update this blood unit"
        )
    
    updated_unit = await blood_service.update_blood_unit(blood_unit_id, blood_data)
    return BloodInventoryResponse.model_validate(updated_unit, from_attributes=True)


@router.delete("/{blood_unit_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_blood_unit(
    blood_unit_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Delete a blood unit.
    User must be associated with the blood bank that owns this unit.
    """
    blood_service = BloodInventoryService(db)
    blood_unit = await blood_service.get_blood_unit(blood_unit_id)
    
    if not blood_unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Blood unit not found"
        )
    
    user_blood_bank_id = await get_user_blood_bank_id(db, current_user.id)
    
    if blood_unit.blood_bank_id != user_blood_bank_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to delete this blood unit"
        )
    
    await blood_service.delete_blood_unit(blood_unit_id)


@router.get("/expiring/{days}", response_model=PaginatedResponse[BloodInventoryDetailResponse])
async def get_expiring_blood_units_paginated(
    days: int = Path(..., ge=1, le=90, description="Number of days to check for expiration"),
    pagination: PaginationParams = Depends(get_pagination_params),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)):
    """
    Get paginated blood units expiring in the specified number of days.
    Only shows units from the blood bank associated with the current user.
    """
    blood_bank_id = await get_user_blood_bank_id(db, current_user.id)
    blood_service = BloodInventoryService(db)
    
    result = await blood_service.get_expiring_blood_units(days, pagination)
    
    if isinstance(result, list):
        # Filter by user's blood bank
        filtered_units = [unit for unit in result if unit.blood_bank_id == blood_bank_id]
        
        detailed_items = [
            BloodInventoryDetailResponse(
                **BloodInventoryResponse.model_validate(unit, from_attributes=True).model_dump(),
                blood_bank_name=unit.blood_bank.blood_bank_name if unit.blood_bank else None,
                added_by_name=unit.added_by.last_name if unit.added_by else None
            )
            for unit in filtered_units
        ]
        
        return PaginatedResponse(
            items=detailed_items,
            total_items=len(detailed_items),
            total_pages=1,
            current_page=1,
            page_size=len(detailed_items),
            has_next=False,
            has_prev=False
        )
    
    # Filter paginated result by user's blood bank
    filtered_items = [unit for unit in result.items if unit.blood_bank_id == blood_bank_id]
    
    detailed_items = [
        BloodInventoryDetailResponse(
            **BloodInventoryResponse.model_validate(unit, from_attributes=True).model_dump(),
            blood_bank_name=unit.blood_bank.blood_bank_name if unit.blood_bank else None,
            added_by_name=unit.added_by.last_name if unit.added_by else None
        )
        for unit in filtered_items
    ]
    
    return PaginatedResponse(
        items=detailed_items,
        total_items=len(detailed_items),
        total_pages=(len(detailed_items) + pagination.page_size - 1) // pagination.page_size,
        current_page=pagination.page,
        page_size=pagination.page_size,
        has_next=pagination.page * pagination.page_size < len(detailed_items),
        has_prev=pagination.page > 1
    )


@router.get("/statistics/overview", response_model=InventoryStatistics)
async def get_inventory_statistics(
    blood_bank_id: Optional[UUID] = Query(None, description="Filter statistics by blood bank"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)):
    """
    Get comprehensive inventory statistics.
    If blood_bank_id is not provided, uses the current user's blood bank.
    """
    if not blood_bank_id:
        blood_bank_id = await get_user_blood_bank_id(db, current_user.id)
    
    blood_service = BloodInventoryService(db)
    stats = await blood_service.get_inventory_statistics(blood_bank_id)
    
    return InventoryStatistics(**stats)


@router.get("/export/csv")
async def export_inventory_csv(
    blood_bank_id: Optional[UUID] = Query(None, description="Filter by blood bank"),
    blood_type: Optional[str] = Query(None, description="Filter by blood type"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)):
    """
    Export blood inventory data as CSV.
    Supports filtering and is optimized for large datasets.
    """
    from fastapi.responses import StreamingResponse
    import csv
    import io
    
    if not blood_bank_id:
        blood_bank_id = await get_user_blood_bank_id(db, current_user.id)
    
    blood_service = BloodInventoryService(db)
    
    # Get all units (without pagination for export)
    if blood_type:
        units = await blood_service.get_blood_units_by_type(blood_type)
    else:
        units = await blood_service.get_blood_units_by_bank(blood_bank_id)
    
    # Filter by blood bank if needed
    if blood_bank_id:
        units = [unit for unit in units if unit.blood_bank_id == blood_bank_id]
    
    # Create CSV content
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow([
        'ID', 'Blood Product', 'Blood Type', 'Quantity', 'Expiry Date',
        'Blood Bank', 'Added By', 'Created At', 'Updated At'
    ])
    
    # Write data
    for unit in units:
        writer.writerow([
            str(unit.id),
            unit.blood_product,
            unit.blood_type,
            unit.quantity,
            unit.expiry_date.isoformat(),
            unit.blood_bank.blood_bank_name if unit.blood_bank else '',
            unit.added_by.last_name if unit.added_by else '',
            unit.created_at.isoformat(),
            unit.updated_at.isoformat()
        ])
    
    output.seek(0)
    
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode('utf-8')),
        media_type='text/csv',
        headers={'Content-Disposition': 'attachment; filename=blood_inventory.csv'}
    )