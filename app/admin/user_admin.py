from sqladmin import ModelView
from app.models import User

class UserAdmin(ModelView, model=User):
    
    icon = "fa-solid fa-user"
    
    form_columns = [
        User.first_name,
        User.last_name,
        User.email,
        User.phone,
        User.roles,
        User.is_verified,
        User.is_active,
        User.status,
        User.created_at,
        User.updated_at,
    ]
    
    
    column_list = [
        User.id,
        User.first_name,
        User.last_name,
        User.email,
        User.phone,
        User.roles,
        User.is_verified,
        User.is_active,
        User.status,
        User.created_at,
        User.updated_at,
    ]

   
    column_actions = [
        "activate", "deactivate", "verify_email"
    ]
    
    
    def activate(self, model: User):
        model.is_active = True
        return f"User {model.name} is now active."

    
    def deactivate(self, model: User):
        model.is_active = False
        return f"User {model.name} is now inactive."
    
    
    def verify_email(self, model: User):
        model.is_verified = True
        return f"User {model.name} is now verified."
    
    
    def after_model_change(self, form, model, is_created):
        if is_created:
            
            pass
