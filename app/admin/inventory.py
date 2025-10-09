from sqladmin import ModelView
from app.models.inventory_model import BloodInventory
from sqlalchemy import func


class BloodInventoryAdmin(ModelView, model=BloodInventory):
    column_list = [
        BloodInventory.id,
        BloodInventory.blood_product,
        BloodInventory.blood_type,
        "blood_bank.blood_bank_name",
        BloodInventory.quantity,
        BloodInventory.expiry_date,
        "added_by.name",
        BloodInventory.created_at,
        BloodInventory.updated_at
    ]

    column_labels = {
        "blood_bank.blood_bank_name": "Blood Bank",
        "added_by.name": "Added By"
    }

    column_formatters_detail = {
        "blood_bank": lambda m, c: m.blood_bank.blood_bank_name if m.blood_bank else "N/A",
        "added_by": lambda m, c: m.added_by.name if m.added_by else "N/A"
    }

    can_create = True
    can_edit = True
    can_delete = True
    can_view_details = True

    name = "Blood Inventory"
    name_plural = "Blood Inventories"
    icon = "fa-solid fa-droplet"

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
