from sqladmin import ModelView
from app.models.inventory import BloodInventory
from sqlalchemy import func


class BloodInventoryAdmin(ModelView, model=BloodInventory):
    column_list = [
        BloodInventory.id,
        BloodInventory.blood_product,
        BloodInventory.blood_type,
        BloodInventory.quantity,
        BloodInventory.expiry_date,
        BloodInventory.blood_bank_id,
        BloodInventory.added_by_id,
        BloodInventory.created_at,
        BloodInventory.updated_at
    ]
    
    column_searchable_list = [
        BloodInventory.blood_product,
        BloodInventory.blood_type
    ]
    
    column_sortable_list = [
        BloodInventory.blood_product,
        BloodInventory.blood_type,
        BloodInventory.quantity,
        BloodInventory.expiry_date,
        BloodInventory.created_at
    ]
    
    column_filters = [
        BloodInventory.blood_product,
        BloodInventory.blood_type,
        BloodInventory.expiry_date,
        BloodInventory.blood_bank_id
    ]
    
    form_excluded_columns = [
        BloodInventory.id,
        BloodInventory.created_at,
        BloodInventory.updated_at
    ]
    
    can_create = True
    can_edit = True
    can_delete = True
    can_view_details = True
    
    name = "Blood Inventory"
    name_plural = "Blood Inventory"
    icon = "fa-solid fa-droplet"
    
    # Add aggregations for the dashboard
    def get_dashboard_stats(self):
        return {
            "total_units": {
                "value": self.session.query(func.sum(BloodInventory.quantity)).scalar() or 0,
                "icon": "fa-solid fa-droplet",
                "color": "red"
            },
            "expiring_soon": {
                "value": self.session.query(func.count(BloodInventory.id))
                    .filter(BloodInventory.expiry_date <= func.now() + func.interval("7 days"))
                    .scalar() or 0,
                "icon": "fa-solid fa-clock",
                "color": "yellow"
            }
        }