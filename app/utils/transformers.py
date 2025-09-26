from typing import List, Dict, Any


def transform_blood_product_keys_to_readable(
    data: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Transform snake_case blood product keys to human-readable names.

    Args:
        data: List of dictionaries containing blood product data

    Returns:
        List of dictionaries with human-readable field names
    """

    # Mapping from snake_case to human-readable names
    key_mapping = {
        "whole_blood": "Whole Blood",
        "red_blood_cells": "Red Blood Cells",
        "platelets": "Platelets",
        "fresh_frozen_plasma": "Fresh Frozen Plasma",
        "cryoprecipitate": "Cryoprecipitate",
        "albumin": "Albumin",
    }

    transformed_data = []

    for item in data:
        new_item = {}

        # Copy non-blood product fields as is
        for key, value in item.items():
            if key in key_mapping:
                # Transform blood product keys
                new_item[key_mapping[key]] = value
            else:
                # Keep other fields unchanged (date, formattedDate, etc.)
                new_item[key] = value

        transformed_data.append(new_item)

    return transformed_data


def transform_response_to_readable(response_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transform an entire API response to use human-readable blood product names.

    Args:
        response_data: API response dictionary containing 'data' field

    Returns:
        Transformed response with readable field names
    """
    if "data" in response_data and isinstance(response_data["data"], list):
        response_data["data"] = transform_blood_product_keys_to_readable(
            response_data["data"]
        )

    return response_data


# Example usage in your route handler:
def example_usage():
    """Example of how to use the transformation in your routes."""

    # Your existing response
    api_response = {
        "success": True,
        "data": [
            {
                "date": "2025-09-18T10:30:00Z",
                "formattedDate": "Sep 18",
                "whole_blood": 5,
                "red_blood_cells": 10,
                "platelets": 3,
                "fresh_frozen_plasma": 2,
                "cryoprecipitate": 0,
                "albumin": 1,
            }
        ],
        "meta": {
            "totalRecords": 1,
            "dateRange": {"from": "2025-09-18", "to": "2025-09-18"},
        },
    }

    # Transform to readable names
    readable_response = transform_response_to_readable(api_response)

    # Result will have "Whole Blood", "Red Blood Cells", etc. instead of snake_case
    return readable_response
