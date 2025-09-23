from enum import Enum
from typing import List


class SortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"


class BloodType(str, Enum):
    """Enum for valid blood types"""

    A_POSITIVE = "A+"
    A_NEGATIVE = "A-"
    B_POSITIVE = "B+"
    B_NEGATIVE = "B-"
    AB_POSITIVE = "AB+"
    AB_NEGATIVE = "AB-"
    O_POSITIVE = "O+"
    O_NEGATIVE = "O-"

    @classmethod
    def get_values(cls) -> List[str]:
        """Get all valid blood type values"""
        return [item.value for item in cls]


class BloodProduct(str, Enum):
    """Enum for valid blood products with standardized naming"""

    WHOLE_BLOOD = "Whole Blood"
    RED_BLOOD_CELLS = "Red Blood Cells"
    RED_CELLS = "Red Cells"  # Alternative name for Red Blood Cells
    PLASMA = "Plasma"
    PLATELETS = "Platelets"
    CRYOPRECIPITATE = "Cryoprecipitate"
    FRESH_FROZEN_PLASMA = "Fresh Frozen Plasma"
    ALBUMIN = "Albumin"

    @classmethod
    def get_values(cls) -> List[str]:
        """Get all valid blood product values"""
        return [item.value for item in cls]

    @classmethod
    def get_all_accepted_values(cls) -> List[str]:
        """Get all accepted values including case variations"""
        base_values = cls.get_values()
        case_variations = []

        # Add lowercase versions
        for value in base_values:
            case_variations.append(value.lower())

        # Add specific common variations
        variations = {
            "red blood cells": "Red Blood Cells",
            "red cells": "Red Cells",
            "platelets": "Platelets",
            "cryoprecipitate": "Cryoprecipitate",
            "fresh frozen plasma": "Fresh Frozen Plasma",
            "albumin": "Albumin",
            "whole blood": "Whole Blood",
        }

        return base_values + list(variations.keys())

    @classmethod
    def normalize_product_name(cls, product_name: str) -> str:
        """Normalize product name to standard enum value"""
        # Direct match first
        for product in cls:
            if product.value == product_name:
                return product.value

        # Case-insensitive match with normalization
        product_lower = product_name.lower()
        normalization_map = {
            "whole blood": cls.WHOLE_BLOOD.value,
            "red blood cells": cls.RED_BLOOD_CELLS.value,
            "red cells": cls.RED_CELLS.value,
            "plasma": cls.PLASMA.value,
            "platelets": cls.PLATELETS.value,
            "cryoprecipitate": cls.CRYOPRECIPITATE.value,
            "fresh frozen plasma": cls.FRESH_FROZEN_PLASMA.value,
            "albumin": cls.ALBUMIN.value,
        }

        return normalization_map.get(product_lower, product_name)
