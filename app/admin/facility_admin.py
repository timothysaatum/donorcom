from sqladmin import ModelView
from app.models import Facility

class FacilityAdmin(ModelView, model=Facility):
    
    form_columns = [
        Facility.facility_name,
        Facility.facility_manager_id,
        Facility.facility_email,
        Facility.facility_digital_address,
        Facility.facility_contact_number,
        Facility.created_at,
        Facility.updated_at,
    ]

    
    column_list = [
        Facility.id,
        Facility.facility_name,
        Facility.facility_email,
        Facility.facility_digital_address,
        Facility.facility_contact_number,
        Facility.created_at,
        Facility.updated_at,
    ]

    
    column_actions = [
        "assign_manager", "deactivate", "activate"
    ]

    def get_plural(self):
        return "Facilities"
    
    
    def assign_manager(self, model: Facility):
        
        pass

    
    def deactivate(self, model: Facility):
        
        model.status = False
        return f"Facility {model.facility_name} is now inactive."

    
    def activate(self, model: Facility):
        
        model.status = True
        return f"Facility {model.facility_name} is now active."

    def after_model_change(self, form, model, is_created):
        if is_created:
            
            pass
