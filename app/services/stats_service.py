from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, and_, case, text
from fastapi import HTTPException, status
from uuid import UUID
from app.models.inventory import BloodInventory
from app.models.request import BloodRequest, DashboardDailySummary, RequestStatus, ProcessingStatus
from app.models.health_facility import Facility
from app.models.blood_bank import BloodBank
from app.schemas.stats_schema import (
    DashboardTimeSeriesRequest,
    BloodInventoryTimeSeriesResponse,
    DashboardSummaryRequest,
    DashboardSummaryResponse,
    DailySummaryMetrics,
    TimeRangeEnum,
    BloodComponentEnum,
    ChartDataPoint,
    DetailedInventoryStats,
    BloodAvailabilityByType,
    BloodAvailabilityByProduct,
    HistoricalTrendData,
    ComprehensiveDashboardResponse
)
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta, date
import asyncio
from contextlib import asynccontextmanager
from collections import defaultdict


class DashboardService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.cache_duration = 300  # 5 minutes cache for performance

    @asynccontextmanager
    async def optimized_transaction(self):
        """Context manager for optimized read-heavy operations"""
        try:
            # Set session to read-only mode for better performance on analytics queries
            await self.db.execute(text("SET TRANSACTION READ ONLY"))
            yield
        except Exception as e:
            await self.db.rollback()
            raise e
        finally:
            await self.db.rollback()  # Clean rollback for read-only

    def _get_date_range(self, time_range: TimeRangeEnum, start_date: Optional[date] = None, 
                       end_date: Optional[date] = None) -> Tuple[date, date]:
        """Calculate date range based on time range enum"""
        today = date.today()
        
        if time_range == TimeRangeEnum.custom:
            if not start_date or not end_date:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="start_date and end_date required for custom range"
                )
            return start_date, end_date
        
        range_mapping = {
            TimeRangeEnum.last_7_days: timedelta(days=7),
            TimeRangeEnum.last_30_days: timedelta(days=30),
            TimeRangeEnum.last_90_days: timedelta(days=90),
            TimeRangeEnum.last_6_months: timedelta(days=180),
            TimeRangeEnum.last_year: timedelta(days=365)
        }
        
        delta = range_mapping.get(time_range, timedelta(days=30))
        return today - delta, today

    async def get_blood_inventory_time_series(
        self, 
        request_params: DashboardTimeSeriesRequest,
        current_user_facility_id: Optional[UUID] = None
    ) -> BloodInventoryTimeSeriesResponse:
        """
        Get time series data for blood inventory tracking (for line chart visualization)
        Highly optimized for performance with proper indexing assumptions
        """
        start_date, end_date = self._get_date_range(
            request_params.time_range, 
            request_params.start_date, 
            request_params.end_date
        )
        
        # Use facility_id from request or fall back to current user's facility
        facility_id = request_params.facility_id or current_user_facility_id
        
        async with self.optimized_transaction():
            # Build optimized query with date_trunc for daily aggregation
            base_query = select(
                func.date_trunc('day', BloodInventory.created_at).label('date'),
                func.sum(BloodInventory.quantity).label('total_quantity')
            ).select_from(BloodInventory)
            
            # Join with BloodBank and Facility if facility filtering is needed
            if facility_id:
                base_query = base_query.join(
                    BloodBank, BloodInventory.blood_bank_id == BloodBank.id
                ).join(
                    Facility, BloodBank.facility_id == Facility.id
                ).where(Facility.id == facility_id)
            
            # Apply filters
            conditions = [
                BloodInventory.blood_product == request_params.component.value,
                func.date(BloodInventory.created_at) >= start_date,
                func.date(BloodInventory.created_at) <= end_date,
                BloodInventory.quantity > 0  # Only count available units
            ]
            
            query = base_query.where(and_(*conditions)).group_by(
                func.date_trunc('day', BloodInventory.created_at)
            ).order_by('date')
            
            result = await self.db.execute(query)
            raw_data = result.all()
            
            # Fill in missing dates with zero values for continuous line chart
            data_points = []
            current_date = start_date
            data_dict = {row.date.date(): int(row.total_quantity or 0) for row in raw_data}
            
            while current_date <= end_date:
                data_points.append(ChartDataPoint(
                    date=current_date,
                    value=data_dict.get(current_date, 0)
                ))
                current_date += timedelta(days=1)
            
            return BloodInventoryTimeSeriesResponse(
                component=request_params.component,
                data_points=data_points,
                total_records=len(data_points),
                date_range={"start": start_date, "end": end_date}
            )

    async def get_dashboard_summary(
        self, 
        request_params: DashboardSummaryRequest,
        current_user_facility_id: Optional[UUID] = None
    ) -> DashboardSummaryResponse:
        """
        Get dashboard summary with KPI metrics (for dashboard cards)
        Optimized with single query for current and previous day data
        """
        facility_id = request_params.facility_id or current_user_facility_id
        target_date = request_params.target_date or date.today()
        previous_date = target_date - timedelta(days=1)
        
        if not facility_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Facility ID is required"
            )
        
        async with self.optimized_transaction():
            # Get or create dashboard summary records for both dates
            summary_query = select(DashboardDailySummary).where(
                and_(
                    DashboardDailySummary.facility_id == facility_id,
                    DashboardDailySummary.date.in_([target_date, previous_date])
                )
            )
            
            result = await self.db.execute(summary_query)
            summaries = {summary.date: summary for summary in result.scalars().all()}
            
            # If current day summary doesn't exist, calculate it
            if target_date not in summaries:
                current_summary = await self._calculate_daily_summary(facility_id, target_date)
                summaries[target_date] = current_summary
            
            current = summaries.get(target_date)
            previous = summaries.get(previous_date)
            
            # Calculate percentage changes
            def calc_percentage_change(current_val: int, previous_val: int) -> float:
                if previous_val == 0:
                    return 100.0 if current_val > 0 else 0.0
                return round(((current_val - previous_val) / previous_val) * 100, 1)
            
            # Get facility info
            facility_query = select(Facility.facility_name).where(Facility.id == facility_id)
            facility_result = await self.db.execute(facility_query)
            facility_name = facility_result.scalar_one_or_none()
            
            if not facility_name:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Facility not found"
                )
            
            current_metrics = DailySummaryMetrics(
                total_stock=current.total_stock,
                total_transferred=current.total_transferred,
                total_requests=current.total_requests,
                stock_change_percent=calc_percentage_change(
                    current.total_stock, 
                    previous.total_stock if previous else 0
                ),
                transfer_change_percent=calc_percentage_change(
                    current.total_transferred,
                    previous.total_transferred if previous else 0
                ),
                request_change_percent=calc_percentage_change(
                    current.total_requests,
                    previous.total_requests if previous else 0
                ),
                date=target_date
            )
            
            return DashboardSummaryResponse(
                current_metrics=current_metrics,
                facility_id=facility_id,
                facility_name=facility_name,
                last_updated=datetime.now()
            )

    async def _calculate_daily_summary(
        self, 
        facility_id: UUID, 
        target_date: date
    ) -> DashboardDailySummary:
        """
        Calculate daily summary metrics for a specific facility and date
        Uses efficient aggregation queries
        """
        # Calculate total stock (current available inventory)
        stock_query = select(
            func.coalesce(func.sum(BloodInventory.quantity), 0).label('total_stock')
        ).select_from(BloodInventory).join(
            BloodBank, BloodInventory.blood_bank_id == BloodBank.id
        ).where(
            and_(
                BloodBank.facility_id == facility_id,
                BloodInventory.quantity > 0,
                BloodInventory.expiry_date >= target_date
            )
        )
        
        # Calculate transfers for the day
        transfer_query = select(
            func.coalesce(func.sum(BloodRequest.quantity_requested), 0).label('total_transferred')
        ).where(
            and_(
                BloodRequest.facility_id == facility_id,
                func.date(BloodRequest.created_at) == target_date,
                BloodRequest.processing_status == ProcessingStatus.completed
            )
        )
        
        # Calculate requests for the day
        request_query = select(
            func.coalesce(func.count(BloodRequest.id), 0).label('total_requests')
        ).where(
            and_(
                BloodRequest.facility_id == facility_id,
                func.date(BloodRequest.created_at) == target_date
            )
        )
        
        # Execute all queries concurrently for better performance
        stock_result, transfer_result, request_result = await asyncio.gather(
            self.db.execute(stock_query),
            self.db.execute(transfer_query),
            self.db.execute(request_query)
        )
        
        total_stock = stock_result.scalar()
        total_transferred = transfer_result.scalar()
        total_requests = request_result.scalar()
        
        # Create and save the summary record
        summary = DashboardDailySummary(
            facility_id=facility_id,
            date=target_date,
            total_stock=total_stock,
            total_transferred=total_transferred,
            total_requests=total_requests
        )
        
        self.db.add(summary)
        await self.db.commit()
        
        return summary

    async def get_detailed_inventory_stats(
        self, 
        facility_id: UUID
    ) -> DetailedInventoryStats:
        """Get detailed inventory statistics for comprehensive dashboard view"""
        async with self.optimized_transaction():
            # Get blood bank for the facility
            blood_bank_query = select(BloodBank.id).where(BloodBank.facility_id == facility_id)
            bank_result = await self.db.execute(blood_bank_query)
            blood_bank_id = bank_result.scalar_one_or_none()
            
            if not blood_bank_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Blood bank not found for facility"
                )
            
            # Get current date for expiry calculations
            today = date.today()
            expiry_7_days = today + timedelta(days=7)
            expiry_30_days = today + timedelta(days=30)
            
            # Blood type distribution query
            blood_type_query = select(
                BloodInventory.blood_type,
                func.sum(BloodInventory.quantity).label('available_units'),
                func.sum(
                    case(
                        (BloodInventory.expiry_date <= expiry_7_days, BloodInventory.quantity),
                        else_=0
                    )
                ).label('expiring_soon')
            ).where(
                and_(
                    BloodInventory.blood_bank_id == blood_bank_id,
                    BloodInventory.quantity > 0,
                    BloodInventory.expiry_date >= today
                )
            ).group_by(BloodInventory.blood_type)
            
            # Blood product distribution query
            product_query = select(
                BloodInventory.blood_product,
                func.sum(BloodInventory.quantity).label('available_units'),
                func.sum(
                    case(
                        (BloodInventory.expiry_date <= expiry_7_days, BloodInventory.quantity),
                        else_=0
                    )
                ).label('expiring_soon')
            ).where(
                and_(
                    BloodInventory.blood_bank_id == blood_bank_id,
                    BloodInventory.quantity > 0,
                    BloodInventory.expiry_date >= today
                )
            ).group_by(BloodInventory.blood_product)
            
            # Total units and expiry summary
            summary_query = select(
                func.sum(BloodInventory.quantity).label('total_units'),
                func.sum(
                    case(
                        (BloodInventory.expiry_date <= expiry_7_days, BloodInventory.quantity),
                        else_=0
                    )
                ).label('expiring_7_days'),
                func.sum(
                    case(
                        (BloodInventory.expiry_date <= expiry_30_days, BloodInventory.quantity),
                        else_=0
                    )
                ).label('expiring_30_days')
            ).where(
                and_(
                    BloodInventory.blood_bank_id == blood_bank_id,
                    BloodInventory.quantity > 0,
                    BloodInventory.expiry_date >= today
                )
            )
            
            # Execute queries concurrently
            blood_type_result, product_result, summary_result = await asyncio.gather(
                self.db.execute(blood_type_query),
                self.db.execute(product_query),
                self.db.execute(summary_query)
            )
            
            # Process results
            by_blood_type = [
                BloodAvailabilityByType(
                    blood_type=row.blood_type,
                    available_units=int(row.available_units or 0),
                    expiring_soon=int(row.expiring_soon or 0)
                )
                for row in blood_type_result.all()
            ]
            
            by_product = [
                BloodAvailabilityByProduct(
                    blood_product=row.blood_product,
                    available_units=int(row.available_units or 0),
                    expiring_soon=int(row.expiring_soon or 0)
                )
                for row in product_result.all()
            ]
            
            summary = summary_result.first()
            
            return DetailedInventoryStats(
                total_units=int(summary.total_units or 0),
                by_blood_type=by_blood_type,
                by_product=by_product,
                expiring_in_7_days=int(summary.expiring_7_days or 0),
                expiring_in_30_days=int(summary.expiring_30_days or 0)
            )

    async def get_historical_trends(
        self, 
        facility_id: UUID,
        days: int = 30
    ) -> HistoricalTrendData:
        """Get historical trend data for the past N days"""
        end_date = date.today()
        start_date = end_date - timedelta(days=days)
        
        async with self.optimized_transaction():
            # Query historical summary data
            trend_query = select(DashboardDailySummary).where(
                and_(
                    DashboardDailySummary.facility_id == facility_id,
                    DashboardDailySummary.date >= start_date,
                    DashboardDailySummary.date <= end_date
                )
            ).order_by(DashboardDailySummary.date)
            
            result = await self.db.execute(trend_query)
            summaries = result.scalars().all()
            
            # Create data structure with all dates filled
            dates = []
            stock_levels = []
            transfer_volumes = []
            request_counts = []
            
            summary_dict = {summary.date: summary for summary in summaries}
            
            current_date = start_date
            while current_date <= end_date:
                dates.append(current_date)
                summary = summary_dict.get(current_date)
                
                if summary:
                    stock_levels.append(summary.total_stock)
                    transfer_volumes.append(summary.total_transferred)
                    request_counts.append(summary.total_requests)
                else:
                    # Fill missing dates with zeros or interpolated values
                    stock_levels.append(0)
                    transfer_volumes.append(0)
                    request_counts.append(0)
                
                current_date += timedelta(days=1)
            
            return HistoricalTrendData(
                dates=dates,
                stock_levels=stock_levels,
                transfer_volumes=transfer_volumes,
                request_counts=request_counts
            )

    async def get_comprehensive_dashboard(
        self,
        facility_id: UUID,
        time_range: TimeRangeEnum = TimeRangeEnum.last_30_days
    ) -> ComprehensiveDashboardResponse:
        """
        Get comprehensive dashboard data combining all metrics
        Optimized with concurrent execution of independent queries
        """
        # Prepare requests
        summary_request = DashboardSummaryRequest(facility_id=facility_id)
        
        # Get data for multiple blood components
        blood_components = [
            BloodComponentEnum.whole_blood,
            BloodComponentEnum.red_blood_cells,
            BloodComponentEnum.platelets,
            BloodComponentEnum.fresh_frozen_plasma
        ]
        
        time_series_requests = [
            DashboardTimeSeriesRequest(
                component=component,
                time_range=time_range,
                facility_id=facility_id
            )
            for component in blood_components
        ]
        
        # Execute all queries concurrently for optimal performance
        summary_task = self.get_dashboard_summary(summary_request, facility_id)
        inventory_stats_task = self.get_detailed_inventory_stats(facility_id)
        historical_trends_task = self.get_historical_trends(facility_id)
        time_series_tasks = [
            self.get_blood_inventory_time_series(req, facility_id)
            for req in time_series_requests
        ]
        
        # Wait for all results
        results = await asyncio.gather(
            summary_task,
            inventory_stats_task,
            historical_trends_task,
            *time_series_tasks,
            return_exceptions=True
        )
        
        # Check for exceptions
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Error in dashboard data retrieval: {str(result)}"
                )
        
        summary, inventory_stats, historical_trends = results[:3]
        time_series_data = results[3:]
        
        return ComprehensiveDashboardResponse(
            summary=summary,
            inventory_stats=inventory_stats,
            historical_trends=historical_trends,
            time_series_data=time_series_data
        )