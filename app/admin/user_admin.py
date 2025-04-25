from sqladmin import ModelView
from app.models import User  # or any model you have

class UserAdmin(ModelView, model=User):
    column_list = [User.id, User.name, User.email, User.phone, User.role]
