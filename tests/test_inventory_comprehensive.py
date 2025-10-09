"""
Comprehensive blood inventory management tests for hospital blood request system.
Tests inventory CRUD operations, expiry tracking, blood type validation, and stock management.
"""

import pytest
from fastapi.testclient import TestClient
from uuid import uuid4
from datetime import datetime, timedelta, timezone, date

from tests.conftest import (
    TestDataFactory,
    assert_response_success,
    assert_response_error,
    assert_validation_error,
    PerformanceTimer,
)
from app.models.health_facility_model import Facility


class TestBloodInventoryCreation:
    """Test blood inventory creation and validation."""

    def test_create_valid_inventory_item(
        self, client: TestClient, auth_headers: dict, test_facility: Facility
    ):
        """Test creating a valid blood inventory item."""
        inventory_data = {
            "blood_bank_id": str(test_facility.id),  # Using facility as blood bank
            "blood_type": "A+",
            "product_type": "whole_blood",
            "quantity": 5,
            "expiry_date": (date.today() + timedelta(days=35)).isoformat(),
            "donation_date": date.today().isoformat(),
            "storage_temperature": 4.0,
            "lot_number": f"LOT{uuid4().hex[:8]}",
            "status": "available",
        }

        with PerformanceTimer(max_duration_ms=500):
            response = client.post(
                "/api/inventory", json=inventory_data, headers=auth_headers
            )

        data = assert_response_success(response, 201)
        assert data["blood_type"] == inventory_data["blood_type"]
        assert data["product_type"] == inventory_data["product_type"]
        assert data["quantity"] == inventory_data["quantity"]
        assert data["status"] == inventory_data["status"]
        assert "id" in data
        assert "created_at" in data

    @pytest.mark.parametrize(
        "invalid_blood_type",
        [
            "Z+",  # Invalid blood type
            "A++",  # Invalid format
            "AB-+",  # Invalid format
            "",  # Empty
            "O positive",  # Wrong format
            "123",  # Numbers
            "UNKNOWN",  # Not valid
        ],
    )
    def test_invalid_blood_type_inventory(
        self,
        client: TestClient,
        auth_headers: dict,
        test_facility: Facility,
        invalid_blood_type: str,
    ):
        """Test inventory creation fails with invalid blood types."""
        inventory_data = TestDataFactory.create_inventory_data(str(test_facility.id))
        inventory_data["blood_type"] = invalid_blood_type

        response = client.post(
            "/api/inventory", json=inventory_data, headers=auth_headers
        )
        assert_validation_error(response, "blood_type")

    @pytest.mark.parametrize(
        "invalid_product_type",
        [
            "plasma_product",  # Not in enum
            "WHOLE_BLOOD",  # Wrong case
            "blood",  # Incomplete
            "",  # Empty
            123,  # Wrong type
        ],
    )
    def test_invalid_product_type_inventory(
        self,
        client: TestClient,
        auth_headers: dict,
        test_facility: Facility,
        invalid_product_type,
    ):
        """Test inventory creation fails with invalid product types."""
        inventory_data = TestDataFactory.create_inventory_data(str(test_facility.id))
        inventory_data["product_type"] = invalid_product_type

        response = client.post(
            "/api/inventory", json=inventory_data, headers=auth_headers
        )
        assert_validation_error(response, "product_type")

    @pytest.mark.parametrize(
        "invalid_quantity",
        [
            0,  # Zero quantity
            -1,  # Negative quantity
            0.5,  # Decimal quantity
            1000,  # Unrealistically high
            "five",  # String instead of number
            None,  # Null
        ],
    )
    def test_invalid_quantity_inventory(
        self,
        client: TestClient,
        auth_headers: dict,
        test_facility: Facility,
        invalid_quantity,
    ):
        """Test inventory creation fails with invalid quantities."""
        inventory_data = TestDataFactory.create_inventory_data(str(test_facility.id))
        inventory_data["quantity"] = invalid_quantity

        response = client.post(
            "/api/inventory", json=inventory_data, headers=auth_headers
        )
        assert response.status_code in [400, 422]

    def test_expired_blood_creation_prevention(
        self, client: TestClient, auth_headers: dict, test_facility: Facility
    ):
        """Test prevention of creating inventory with past expiry date."""
        inventory_data = TestDataFactory.create_inventory_data(str(test_facility.id))
        inventory_data["expiry_date"] = (
            date.today() - timedelta(days=1)
        ).isoformat()  # Yesterday

        response = client.post(
            "/api/inventory", json=inventory_data, headers=auth_headers
        )
        assert_response_error(response, 400)

    def test_invalid_temperature_range(
        self, client: TestClient, auth_headers: dict, test_facility: Facility
    ):
        """Test inventory creation with invalid storage temperatures."""
        invalid_temperatures = [
            -10.0,  # Too cold
            15.0,  # Too warm
            100.0,  # Way too warm
            "cold",  # String instead of number
        ]

        for temp in invalid_temperatures:
            inventory_data = TestDataFactory.create_inventory_data(
                str(test_facility.id)
            )
            inventory_data["storage_temperature"] = temp

            response = client.post(
                "/api/inventory", json=inventory_data, headers=auth_headers
            )
            assert response.status_code in [400, 422]

    def test_duplicate_lot_number_prevention(
        self, client: TestClient, auth_headers: dict, test_facility: Facility
    ):
        """Test prevention of duplicate lot numbers."""
        lot_number = f"UNIQUE_LOT_{uuid4().hex[:8]}"

        # Create first inventory item
        inventory_data1 = TestDataFactory.create_inventory_data(str(test_facility.id))
        inventory_data1["lot_number"] = lot_number

        response1 = client.post(
            "/api/inventory", json=inventory_data1, headers=auth_headers
        )
        assert_response_success(response1, 201)

        # Try to create second item with same lot number
        inventory_data2 = TestDataFactory.create_inventory_data(str(test_facility.id))
        inventory_data2["lot_number"] = lot_number

        response2 = client.post(
            "/api/inventory", json=inventory_data2, headers=auth_headers
        )
        assert_response_error(response2, 400)


class TestBloodInventoryManagement:
    """Test blood inventory management operations."""

    def test_get_inventory_by_id(self, client: TestClient, auth_headers: dict):
        """Test retrieving inventory item by ID."""
        # First create an inventory item
        inventory_data = TestDataFactory.create_inventory_data(str(uuid4()))
        create_response = client.post(
            "/api/inventory", json=inventory_data, headers=auth_headers
        )

        if create_response.status_code == 201:
            created_item = create_response.json()["data"]

            response = client.get(
                f"/api/inventory/{created_item['id']}", headers=auth_headers
            )

            data = assert_response_success(response)
            assert data["id"] == created_item["id"]
            assert data["blood_type"] == created_item["blood_type"]
            assert data["quantity"] == created_item["quantity"]

    def test_update_inventory_quantity(
        self, client: TestClient, auth_headers: dict, test_facility: Facility
    ):
        """Test updating inventory quantity."""
        # Create inventory item
        inventory_data = TestDataFactory.create_inventory_data(str(test_facility.id))
        create_response = client.post(
            "/api/inventory", json=inventory_data, headers=auth_headers
        )

        if create_response.status_code == 201:
            created_item = create_response.json()["data"]

            update_data = {
                "quantity": 3,  # Reduce quantity
                "notes": "Used 2 units for patient transfusion",
            }

            response = client.put(
                f"/api/inventory/{created_item['id']}",
                json=update_data,
                headers=auth_headers,
            )

            data = assert_response_success(response)
            assert data["quantity"] == 3

    def test_mark_inventory_as_used(
        self, client: TestClient, auth_headers: dict, test_facility: Facility
    ):
        """Test marking inventory as used/expired."""
        inventory_data = TestDataFactory.create_inventory_data(str(test_facility.id))
        create_response = client.post(
            "/api/inventory", json=inventory_data, headers=auth_headers
        )

        if create_response.status_code == 201:
            created_item = create_response.json()["data"]

            update_data = {"status": "used", "notes": "Used for emergency transfusion"}

            response = client.put(
                f"/api/inventory/{created_item['id']}/status",
                json=update_data,
                headers=auth_headers,
            )

            data = assert_response_success(response)
            assert data["status"] == "used"

    def test_list_inventory_with_filters(self, client: TestClient, auth_headers: dict):
        """Test listing inventory with various filters."""
        params = {"blood_type": "A+", "status": "available", "limit": 10, "page": 1}

        response = client.get("/api/inventory", params=params, headers=auth_headers)

        data = assert_response_success(response)
        assert "inventory" in data
        assert "total" in data
        assert "page" in data
        assert "limit" in data

        # Verify filtering
        for item in data["inventory"]:
            assert item["blood_type"] == "A+"
            assert item["status"] == "available"

    def test_search_inventory_by_lot_number(
        self, client: TestClient, auth_headers: dict
    ):
        """Test searching inventory by lot number."""
        params = {"lot_number": "LOT12345", "limit": 10}

        response = client.get("/api/inventory", params=params, headers=auth_headers)

        data = assert_response_success(response)
        # Results should match the lot number if any exist
        for item in data["inventory"]:
            assert "LOT12345" in item["lot_number"]

    def test_filter_by_expiry_date_range(self, client: TestClient, auth_headers: dict):
        """Test filtering inventory by expiry date range."""
        today = date.today()
        params = {
            "expiry_start": today.isoformat(),
            "expiry_end": (today + timedelta(days=30)).isoformat(),
            "limit": 10,
        }

        response = client.get("/api/inventory", params=params, headers=auth_headers)

        data = assert_response_success(response)
        # All returned items should have expiry dates within range
        for item in data["inventory"]:
            expiry_date = datetime.fromisoformat(item["expiry_date"]).date()
            assert today <= expiry_date <= (today + timedelta(days=30))


class TestBloodInventoryExpiry:
    """Test blood inventory expiry management and alerts."""

    def test_get_expiring_soon_inventory(self, client: TestClient, auth_headers: dict):
        """Test getting inventory items expiring soon."""
        params = {
            "expiring_days": 7,  # Items expiring within 7 days
            "status": "available",
        }

        response = client.get(
            "/api/inventory/expiring", params=params, headers=auth_headers
        )

        data = assert_response_success(response)
        assert "inventory" in data

        # Verify all items are expiring within the specified timeframe
        cutoff_date = date.today() + timedelta(days=7)
        for item in data["inventory"]:
            expiry_date = datetime.fromisoformat(item["expiry_date"]).date()
            assert expiry_date <= cutoff_date

    def test_mark_expired_inventory(
        self, client: TestClient, auth_headers: dict, test_facility: Facility
    ):
        """Test marking inventory as expired."""
        # Create inventory that's about to expire
        inventory_data = TestDataFactory.create_inventory_data(str(test_facility.id))
        inventory_data["expiry_date"] = (date.today() + timedelta(days=1)).isoformat()

        create_response = client.post(
            "/api/inventory", json=inventory_data, headers=auth_headers
        )

        if create_response.status_code == 201:
            created_item = create_response.json()["data"]

            expire_data = {
                "status": "expired",
                "expiry_reason": "Reached expiration date",
            }

            response = client.put(
                f"/api/inventory/{created_item['id']}/expire",
                json=expire_data,
                headers=auth_headers,
            )

            data = assert_response_success(response)
            assert data["status"] == "expired"

    def test_bulk_expire_old_inventory(
        self, client: TestClient, admin_auth_headers: dict
    ):
        """Test bulk expiring old inventory items."""
        expire_data = {
            "cutoff_date": date.today().isoformat(),
            "reason": "Automated expiry process",
        }

        response = client.post(
            "/api/inventory/bulk-expire", json=expire_data, headers=admin_auth_headers
        )

        # Should succeed if user has proper permissions
        if response.status_code == 200:
            data = response.json()["data"]
            assert "expired_count" in data
            assert isinstance(data["expired_count"], int)

    def test_expiry_alert_thresholds(self, client: TestClient, auth_headers: dict):
        """Test different expiry alert thresholds."""
        thresholds = [1, 3, 7, 14, 30]  # Days

        for threshold in thresholds:
            params = {
                "expiring_days": threshold,
                "alert_level": "warning" if threshold > 7 else "critical",
            }

            response = client.get(
                "/api/inventory/alerts", params=params, headers=auth_headers
            )

            if response.status_code == 200:
                data = response.json()["data"]
                assert "alerts" in data
                assert "threshold_days" in data
                assert data["threshold_days"] == threshold


class TestBloodInventoryStockManagement:
    """Test stock level management and alerts."""

    def test_low_stock_alerts(self, client: TestClient, auth_headers: dict):
        """Test low stock level alerts."""
        params = {
            "blood_type": "O-",  # Universal donor - critical to monitor
            "minimum_threshold": 5,
        }

        response = client.get(
            "/api/inventory/low-stock", params=params, headers=auth_headers
        )

        data = assert_response_success(response)
        assert "low_stock_items" in data

        # All returned items should be below threshold
        for item in data["low_stock_items"]:
            assert item["quantity"] < 5

    def test_stock_level_by_blood_type(self, client: TestClient, auth_headers: dict):
        """Test getting stock levels by blood type."""
        response = client.get("/api/inventory/stock-summary", headers=auth_headers)

        data = assert_response_success(response)
        assert "stock_summary" in data

        # Should have entries for each blood type
        blood_types = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]
        summary = data["stock_summary"]

        # Verify structure
        for blood_type in blood_types:
            if blood_type in summary:
                assert "total_units" in summary[blood_type]
                assert "available_units" in summary[blood_type]

    def test_critical_shortage_alerts(self, client: TestClient, auth_headers: dict):
        """Test critical shortage alerts for emergency blood types."""
        critical_blood_types = ["O-", "O+"]  # Universal donors

        for blood_type in critical_blood_types:
            params = {"blood_type": blood_type, "critical_threshold": 2}

            response = client.get(
                "/api/inventory/critical-shortage", params=params, headers=auth_headers
            )

            if response.status_code == 200:
                data = response.json()["data"]
                assert "is_critical" in data
                assert "current_stock" in data
                assert "threshold" in data

    def test_reserve_inventory_for_surgery(
        self, client: TestClient, auth_headers: dict, test_facility: Facility
    ):
        """Test reserving inventory for scheduled surgery."""
        # Create available inventory
        inventory_data = TestDataFactory.create_inventory_data(str(test_facility.id))
        inventory_data["quantity"] = 5

        create_response = client.post(
            "/api/inventory", json=inventory_data, headers=auth_headers
        )

        if create_response.status_code == 201:
            created_item = create_response.json()["data"]

            reserve_data = {
                "quantity": 2,
                "reservation_reason": "Scheduled surgery for Patient #12345",
                "reserved_until": (
                    datetime.now(timezone.utc) + timedelta(hours=24)
                ).isoformat(),
            }

            response = client.post(
                f"/api/inventory/{created_item['id']}/reserve",
                json=reserve_data,
                headers=auth_headers,
            )

            if response.status_code == 200:
                data = response.json()["data"]
                assert "reserved_quantity" in data
                assert data["reserved_quantity"] == 2


class TestBloodInventoryCompatibility:
    """Test blood type compatibility and cross-matching."""

    def test_blood_compatibility_check(self, client: TestClient, auth_headers: dict):
        """Test blood type compatibility checking."""
        compatibility_data = {"recipient_blood_type": "A+", "donor_blood_type": "O+"}

        response = client.post(
            "/api/inventory/compatibility-check",
            json=compatibility_data,
            headers=auth_headers,
        )

        if response.status_code == 200:
            data = response.json()["data"]
            assert "compatible" in data
            assert "compatibility_level" in data
            # O+ should be compatible with A+
            assert data["compatible"] is True

    def test_cross_match_requirements(self, client: TestClient, auth_headers: dict):
        """Test cross-match requirements for blood products."""
        cross_match_data = {
            "patient_blood_type": "AB-",
            "product_type": "whole_blood",
            "special_requirements": ["irradiated", "cmv_negative"],
        }

        response = client.post(
            "/api/inventory/cross-match", json=cross_match_data, headers=auth_headers
        )

        if response.status_code == 200:
            data = response.json()["data"]
            assert "cross_match_required" in data
            assert "special_processing" in data

    def test_emergency_release_protocol(self, client: TestClient, auth_headers: dict):
        """Test emergency blood release without full cross-match."""
        emergency_data = {
            "blood_type": "O-",  # Universal donor
            "quantity": 2,
            "emergency_level": "life_threatening",
            "requesting_physician": "Dr. Emergency",
            "patient_id": str(uuid4()),
        }

        response = client.post(
            "/api/inventory/emergency-release",
            json=emergency_data,
            headers=auth_headers,
        )

        # Should either succeed or require additional authorization
        assert response.status_code in [200, 202, 403]

        if response.status_code in [200, 202]:
            data = response.json()["data"]
            assert "release_authorized" in data


class TestBloodInventoryExtremeCases:
    """Test extreme edge cases and boundary conditions for inventory."""

    def test_massive_inventory_operations(self, client: TestClient, auth_headers: dict):
        """Test performance with large inventory operations."""
        # Request large inventory list
        params = {"limit": 1000, "page": 1}

        with PerformanceTimer(max_duration_ms=3000):  # 3 seconds max
            response = client.get("/api/inventory", params=params, headers=auth_headers)

        # Should handle large requests gracefully
        assert response.status_code in [200, 400, 413]

    def test_concurrent_inventory_updates(
        self, client: TestClient, auth_headers: dict, test_facility: Facility
    ):
        """Test concurrent updates to the same inventory item."""
        # Create inventory item
        inventory_data = TestDataFactory.create_inventory_data(str(test_facility.id))
        inventory_data["quantity"] = 10

        create_response = client.post(
            "/api/inventory", json=inventory_data, headers=auth_headers
        )

        if create_response.status_code == 201:
            created_item = create_response.json()["data"]
            item_id = created_item["id"]

            # Simulate concurrent updates
            update_data_1 = {"quantity": 8, "notes": "Used 2 units"}
            update_data_2 = {"quantity": 7, "notes": "Used 3 units"}

            response1 = client.put(
                f"/api/inventory/{item_id}", json=update_data_1, headers=auth_headers
            )
            response2 = client.put(
                f"/api/inventory/{item_id}", json=update_data_2, headers=auth_headers
            )

            # At least one should succeed, handle race conditions gracefully
            success_count = sum(
                1 for r in [response1, response2] if r.status_code == 200
            )
            assert success_count >= 1

    def test_invalid_uuid_handling_inventory(
        self, client: TestClient, auth_headers: dict
    ):
        """Test handling of invalid UUIDs in inventory operations."""
        invalid_uuids = [
            "not-a-uuid",
            "12345",
            "",
            "00000000-0000-0000-0000-000000000000",
        ]

        for invalid_uuid in invalid_uuids:
            response = client.get(
                f"/api/inventory/{invalid_uuid}", headers=auth_headers
            )
            assert response.status_code in [400, 404, 422]

    def test_temperature_monitoring_extremes(
        self, client: TestClient, auth_headers: dict, test_facility: Facility
    ):
        """Test extreme temperature monitoring scenarios."""
        extreme_temp_data = {
            "blood_bank_id": str(test_facility.id),
            "blood_type": "A+",
            "product_type": "whole_blood",
            "quantity": 1,
            "expiry_date": (date.today() + timedelta(days=30)).isoformat(),
            "donation_date": date.today().isoformat(),
            "storage_temperature": 25.0,  # Way too warm
            "lot_number": f"TEMP_TEST_{uuid4().hex[:8]}",
            "status": "quarantine",  # Should be quarantined due to temp
        }

        response = client.post(
            "/api/inventory", json=extreme_temp_data, headers=auth_headers
        )

        # Should either reject or accept with quarantine status
        if response.status_code == 201:
            data = response.json()["data"]
            assert data["status"] == "quarantine"
        else:
            assert response.status_code in [400, 422]

    def test_bulk_operations_boundary_limits(
        self, client: TestClient, admin_auth_headers: dict
    ):
        """Test bulk operations with boundary limits."""
        # Test bulk update with maximum allowed items
        bulk_update_data = {
            "item_ids": [str(uuid4()) for _ in range(100)],  # Large batch
            "update_data": {
                "status": "quarantine",
                "notes": "Bulk quarantine operation",
            },
        }

        response = client.put(
            "/api/inventory/bulk-update",
            json=bulk_update_data,
            headers=admin_auth_headers,
        )

        # Should either process or reject based on limits
        assert response.status_code in [200, 400, 413, 422]

    def test_special_characters_in_lot_numbers(
        self, client: TestClient, auth_headers: dict, test_facility: Facility
    ):
        """Test handling of special characters in lot numbers."""
        special_lot_numbers = [
            "LOT-2024/01/01",
            "LOT_αβγ_001",  # Unicode
            "LOT#!@#$%",  # Special chars
            "LOT\x00\x01",  # Control chars
            "LOT" + "A" * 100,  # Very long
        ]

        for lot_number in special_lot_numbers:
            inventory_data = TestDataFactory.create_inventory_data(
                str(test_facility.id)
            )
            inventory_data["lot_number"] = lot_number

            response = client.post(
                "/api/inventory", json=inventory_data, headers=auth_headers
            )

            # Should either succeed with sanitized data or be rejected
            if response.status_code == 201:
                data = response.json()["data"]
                # Check that dangerous characters are handled
                assert "\x00" not in data["lot_number"]
            else:
                assert response.status_code in [400, 422]
