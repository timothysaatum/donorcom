from sqladmin import ModelView
from app.models import BloodBank, User, Facility

class BloodBankAdmin(ModelView, model=BloodBank):
    column_list = [
        BloodBank.id,
        BloodBank.blood_bank_name,
        BloodBank.email,
        BloodBank.phone,
        "facility",
        "manager_user",
        BloodBank.created_at,
        BloodBank.updated_at,
    ]

    column_labels = {
        "facility": "Facility",
        "manager_user": "Manager"
    }

    column_formatters_detail = {
        "facility": lambda m, c: m.facility.facility_name if m.facility else "N/A",
        "manager_user": lambda m, c: m.manager_user.name if m.manager_user else "N/A"
    }

    form_columns = [
        BloodBank.blood_bank_name,
        BloodBank.phone,
        BloodBank.email,
        "manager_user",
        "facility",
    ]

    can_create = True
    can_edit = True
    can_delete = True
    can_view_details = True

    icon = "fa-solid fa-building-columns"

    name = "Blood Bank"
    name_plural = "Blood Banks"

    column_actions = ["assign_manager", "deactivate", "activate"]

    def assign_manager(self, model: BloodBank):
        return f"Assign manager action triggered for {model.blood_bank_name}"

    def deactivate(self, model: BloodBank):
        model.status = False
        return f"Blood Bank {model.blood_bank_name} is now inactive."

    def activate(self, model: BloodBank):
        model.status = True
        return f"Blood Bank {model.blood_bank_name} is now active."

    def after_model_change(self, form, model, is_created):
        if is_created:
            pass
