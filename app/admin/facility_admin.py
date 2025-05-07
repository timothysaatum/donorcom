from sqladmin import ModelView
from app.models import Facility

class FacilityAdmin(ModelView, model=Facility):
    icon = "fa-solid fa-hospital"
    name = "Facility"
    name_plural = "Facilities"

    column_list = [
        Facility.id,
        Facility.facility_name,
        Facility.facility_email,
        Facility.facility_digital_address,
        Facility.facility_contact_number,
        "facility_manager",
        Facility.created_at,
        Facility.updated_at,
    ]

    form_columns = [
        Facility.facility_name,
        "facility_manager",
        Facility.facility_email,
        Facility.facility_digital_address,
        Facility.facility_contact_number,
    ]

    column_labels = {
        "facility_manager": "Manager",
    }

    column_formatters_detail = {
        "facility_manager": lambda m, c: m.facility_manager.name if m.facility_manager else "N/A"
    }

    # Optional: add column formatter for list view (to show name instead of object)
    column_formatters = {
        "facility_manager": lambda m, c: m.facility_manager.name if m.facility_manager else "N/A"
    }

    column_actions = ["assign_manager", "deactivate", "activate"]

    can_create = True
    can_edit = True
    can_delete = True
    can_view_details = True

    def assign_manager(self, model: Facility):
        return f"Assign manager action triggered for {model.facility_name}"

    def deactivate(self, model: Facility):
        model.status = False
        return f"Facility {model.facility_name} is now inactive."

    def activate(self, model: Facility):
        model.status = True
        return f"Facility {model.facility_name} is now active."

    def after_model_change(self, form, model, is_created):
        if is_created:
            pass
