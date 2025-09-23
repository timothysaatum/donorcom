import datetime
import random
import string


def generate_tracking_number(length=12):
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


def generate_batch_number():
    """Generate a unique batch number in format YYYYMMDD-XXXX"""
    date_part = datetime.now().strftime("%Y%m%d")
    random_part = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"{date_part}-{random_part}"


def calculate_expiry_date(blood_product: str) -> datetime.date:
    """Calculate expiry date based on blood product type"""
    # Standard shelf life for different blood products (in days)
    shelf_life_days = {
        "whole blood": 35,
        "red blood cells": 42,
        "packed red blood cells": 42,
        "platelets": 5,
        "plasma": 365,
        "fresh frozen plasma": 365,
        "cryoprecipitate": 365,
    }

    # Default to 35 days if product type not found
    days = shelf_life_days.get(blood_product.lower(), 35)
    return (datetime.now() + datetime.timedelta(days=days)).date()
