from sqladmin import ModelView
from app.models import BloodBank

class BloodBankAdmin(ModelView, model=BloodBank):
    
    form_columns = [
        BloodBank.blood_bank_name,
        BloodBank.phone,
        BloodBank.email,
        BloodBank.manager_id,
        BloodBank.facility_id,
        BloodBank.created_at,
        BloodBank.updated_at,
    ]

   
    column_list = [
        BloodBank.id,
        BloodBank.blood_bank_name,
        BloodBank.email,
        BloodBank.phone,
        BloodBank.facility_id,
        BloodBank.manager_id,
        BloodBank.created_at,
        BloodBank.updated_at,
    ]

    
    column_actions = [
        "assign_manager", "deactivate", "activate"
    ]

    
    def assign_manager(self, model: BloodBank):
       
        pass

    
    def deactivate(self, model: BloodBank):
        
        model.status = False
        return f"Blood Bank {model.blood_bank_name} is now inactive."

    
    def activate(self, model: BloodBank):
        
        model.status = True
        return f"Blood Bank {model.blood_bank_name} is now active."

    def after_model_change(self, form, model, is_created):
        if is_created:
            
            pass
