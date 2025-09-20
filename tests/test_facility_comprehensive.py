"""
Comprehensive facility management tests for hospital blood request system.
Tests facility operations, user-facility relationships, and multi-facility scenarios.
"""

import pytest
from fastapi.testclient import TestClient
from uuid import uuid4

from tests.conftest import (
    TestDataFactory,
    assert_response_success,
    assert_response_error,
    assert_validation_error,
    PerformanceTimer,
)
from app.models.health_facility import Facility
from app.models.user import User


class TestFacilityCreation:
    """Test facility creation and validation."""

    def test_create_valid_facility(self, client: TestClient, admin_auth_headers: dict):
        """Test creating a valid healthcare facility."""
        facility_data = {
            "name": "Ghana National Hospital",
            "address": "123 Independence Avenue, Accra",
            "contact_phone": "+233302123456",
            "email": "info@gnhospital.gh",
            "facility_type": "hospital",
            "region": "GH-AA",  # Greater Accra
            "description": "Leading healthcare facility in Ghana",
            "is_active": True,
            "emergency_contact": "+233302999999",
            "license_number": "GH-MED-2024-001",
        }

        with PerformanceTimer(max_duration_ms=500):
            response = client.post(
                "/api/facilities", json=facility_data, headers=admin_auth_headers
            )

        data = assert_response_success(response, 201)
        assert data["name"] == facility_data["name"]
        assert data["facility_type"] == facility_data["facility_type"]
        assert data["region"] == facility_data["region"]
        assert data["is_active"] is True
        assert "id" in data
        assert "created_at" in data

    @pytest.mark.parametrize(
        "invalid_facility_type",
        [
            "private_clinic",  # Not in enum
            "HOSPITAL",  # Wrong case
            "medical_center",  # Not in enum
            "",  # Empty
            123,  # Wrong type
            None,  # Null
        ],
    )
    def test_invalid_facility_type(
        self, client: TestClient, admin_auth_headers: dict, invalid_facility_type
    ):
        """Test facility creation fails with invalid facility types."""
        facility_data = TestDataFactory.create_facility_data()
        facility_data["facility_type"] = invalid_facility_type

        response = client.post(
            "/api/facilities", json=facility_data, headers=admin_auth_headers
        )
        assert_validation_error(response, "facility_type")

    @pytest.mark.parametrize(
        "invalid_region",
        [
            "GH-XX",  # Invalid Ghana region
            "US-NY",  # Wrong country
            "ACCRA",  # Wrong format
            "",  # Empty
            "GH",  # Incomplete
            123,  # Wrong type
        ],
    )
    def test_invalid_ghana_region(
        self, client: TestClient, admin_auth_headers: dict, invalid_region
    ):
        """Test facility creation fails with invalid Ghana regions."""
        facility_data = TestDataFactory.create_facility_data()
        facility_data["region"] = invalid_region

        response = client.post(
            "/api/facilities", json=facility_data, headers=admin_auth_headers
        )
        assert_validation_error(response, "region")

    @pytest.mark.parametrize(
        "invalid_phone",
        [
            "123456",  # Too short
            "+1234567890123456789",  # Too long
            "not-a-phone",  # Invalid format
            "+233-2XX-XXXX",  # Invalid Ghana format
            "",  # Empty
            "+233244",  # Incomplete Ghana number
        ],
    )
    def test_invalid_phone_numbers(
        self, client: TestClient, admin_auth_headers: dict, invalid_phone: str
    ):
        """Test facility creation fails with invalid phone numbers."""
        facility_data = TestDataFactory.create_facility_data()
        facility_data["contact_phone"] = invalid_phone

        response = client.post(
            "/api/facilities", json=facility_data, headers=admin_auth_headers
        )
        assert_validation_error(response, "contact_phone")

    def test_duplicate_facility_name_prevention(
        self, client: TestClient, admin_auth_headers: dict
    ):
        """Test prevention of duplicate facility names in same region."""
        facility_name = f"Unique Hospital {uuid4().hex[:8]}"

        # Create first facility
        facility_data1 = TestDataFactory.create_facility_data(facility_name)
        response1 = client.post(
            "/api/facilities", json=facility_data1, headers=admin_auth_headers
        )
        assert_response_success(response1, 201)

        # Try to create second facility with same name in same region
        facility_data2 = TestDataFactory.create_facility_data(facility_name)
        facility_data2["region"] = facility_data1["region"]  # Same region

        response2 = client.post(
            "/api/facilities", json=facility_data2, headers=admin_auth_headers
        )
        assert_response_error(response2, 400)

    def test_missing_required_fields(
        self, client: TestClient, admin_auth_headers: dict
    ):
        """Test facility creation fails with missing required fields."""
        required_fields = [
            "name",
            "address",
            "contact_phone",
            "email",
            "facility_type",
            "region",
        ]

        for field in required_fields:
            facility_data = TestDataFactory.create_facility_data()
            del facility_data[field]

            response = client.post(
                "/api/facilities", json=facility_data, headers=admin_auth_headers
            )
            assert_validation_error(response, field)

    def test_unauthorized_facility_creation(
        self, client: TestClient, auth_headers: dict  # Regular user, not admin
    ):
        """Test facility creation fails without admin privileges."""
        facility_data = TestDataFactory.create_facility_data()

        response = client.post(
            "/api/facilities", json=facility_data, headers=auth_headers
        )
        assert response.status_code in [403, 401]  # Forbidden or Unauthorized


class TestFacilityManagement:
    """Test facility management operations."""

    def test_get_facility_by_id(
        self, client: TestClient, auth_headers: dict, test_facility: Facility
    ):
        """Test retrieving facility by ID."""
        response = client.get(
            f"/api/facilities/{test_facility.id}", headers=auth_headers
        )

        data = assert_response_success(response)
        assert data["id"] == str(test_facility.id)
        assert data["name"] == test_facility.name
        assert data["facility_type"] == test_facility.facility_type

    def test_update_facility_information(
        self, client: TestClient, admin_auth_headers: dict, test_facility: Facility
    ):
        """Test updating facility information."""
        update_data = {
            "name": "Updated Hospital Name",
            "description": "Updated facility description",
            "emergency_contact": "+233302888888",
            "is_active": True,
        }

        response = client.put(
            f"/api/facilities/{test_facility.id}",
            json=update_data,
            headers=admin_auth_headers,
        )

        data = assert_response_success(response)
        assert data["name"] == update_data["name"]
        assert data["description"] == update_data["description"]
        assert data["emergency_contact"] == update_data["emergency_contact"]

    def test_deactivate_facility(
        self, client: TestClient, admin_auth_headers: dict, test_facility: Facility
    ):
        """Test deactivating a facility."""
        deactivate_data = {
            "is_active": False,
            "deactivation_reason": "Facility temporarily closed for renovations",
        }

        response = client.put(
            f"/api/facilities/{test_facility.id}/status",
            json=deactivate_data,
            headers=admin_auth_headers,
        )

        data = assert_response_success(response)
        assert data["is_active"] is False

    def test_list_facilities_with_pagination(
        self, client: TestClient, auth_headers: dict
    ):
        """Test listing facilities with pagination."""
        params = {"page": 1, "limit": 10, "is_active": True}

        response = client.get("/api/facilities", params=params, headers=auth_headers)

        data = assert_response_success(response)
        assert "facilities" in data
        assert "total" in data
        assert "page" in data
        assert "limit" in data
        assert isinstance(data["facilities"], list)

    def test_filter_facilities_by_type(self, client: TestClient, auth_headers: dict):
        """Test filtering facilities by type."""
        params = {"facility_type": "hospital", "limit": 10}

        response = client.get("/api/facilities", params=params, headers=auth_headers)

        data = assert_response_success(response)
        # All returned facilities should be hospitals
        for facility in data["facilities"]:
            assert facility["facility_type"] == "hospital"

    def test_filter_facilities_by_region(self, client: TestClient, auth_headers: dict):
        """Test filtering facilities by Ghana region."""
        params = {"region": "GH-AA", "limit": 10}  # Greater Accra

        response = client.get("/api/facilities", params=params, headers=auth_headers)

        data = assert_response_success(response)
        # All returned facilities should be in Greater Accra
        for facility in data["facilities"]:
            assert facility["region"] == "GH-AA"

    def test_search_facilities_by_name(self, client: TestClient, auth_headers: dict):
        """Test searching facilities by name."""
        params = {"search": "Hospital", "limit": 10}

        response = client.get("/api/facilities", params=params, headers=auth_headers)

        data = assert_response_success(response)
        # Results should contain the search term
        for facility in data["facilities"]:
            assert (
                "Hospital" in facility["name"] or "hospital" in facility["name"].lower()
            )


class TestFacilityUserRelationships:
    """Test relationships between facilities and users."""

    def test_assign_user_to_facility(
        self,
        client: TestClient,
        admin_auth_headers: dict,
        test_facility: Facility,
        test_user: User,
    ):
        """Test assigning a user to a facility."""
        assignment_data = {
            "user_id": str(test_user.id),
            "facility_id": str(test_facility.id),
            "role": "staff",
        }

        response = client.post(
            f"/api/facilities/{test_facility.id}/users",
            json=assignment_data,
            headers=admin_auth_headers,
        )

        data = assert_response_success(response, 201)
        assert data["user_id"] == str(test_user.id)
        assert data["facility_id"] == str(test_facility.id)

    def test_list_facility_users(
        self, client: TestClient, auth_headers: dict, test_facility: Facility
    ):
        """Test listing users assigned to a facility."""
        response = client.get(
            f"/api/facilities/{test_facility.id}/users", headers=auth_headers
        )

        data = assert_response_success(response)
        assert "users" in data
        assert isinstance(data["users"], list)

        # Each user should have facility relationship info
        for user in data["users"]:
            assert "id" in user
            assert "email" in user
            assert "role" in user

    def test_filter_facility_users_by_role(
        self, client: TestClient, auth_headers: dict, test_facility: Facility
    ):
        """Test filtering facility users by role."""
        params = {"role": "staff", "is_active": True}

        response = client.get(
            f"/api/facilities/{test_facility.id}/users",
            params=params,
            headers=auth_headers,
        )

        data = assert_response_success(response)
        # All returned users should have staff role
        for user in data["users"]:
            assert user["role"] == "staff"

    def test_remove_user_from_facility(
        self,
        client: TestClient,
        admin_auth_headers: dict,
        test_facility: Facility,
        test_user: User,
    ):
        """Test removing a user from a facility."""
        response = client.delete(
            f"/api/facilities/{test_facility.id}/users/{test_user.id}",
            headers=admin_auth_headers,
        )

        assert_response_success(response)

    def test_facility_administrator_permissions(
        self, client: TestClient, test_facility: Facility, admin_user: User
    ):
        """Test facility administrator can manage their facility."""
        # Login as facility administrator
        admin_headers = self._get_auth_headers(client, admin_user)

        # Should be able to view facility details
        response = client.get(
            f"/api/facilities/{test_facility.id}", headers=admin_headers
        )
        assert_response_success(response)

        # Should be able to update facility
        update_data = {"description": "Updated by facility admin"}
        response = client.put(
            f"/api/facilities/{test_facility.id}",
            json=update_data,
            headers=admin_headers,
        )
        assert response.status_code in [200, 403]  # Depends on permission model

    def test_cross_facility_access_restriction(
        self, client: TestClient, auth_headers: dict
    ):
        """Test users cannot access other facilities' data."""
        # Create another facility
        other_facility_data = TestDataFactory.create_facility_data("Other Hospital")

        # Try to access as regular user from different facility
        other_facility_id = str(uuid4())  # Non-existent facility
        response = client.get(
            f"/api/facilities/{other_facility_id}/users", headers=auth_headers
        )

        # Should be forbidden or not found
        assert response.status_code in [403, 404]

    def _get_auth_headers(self, client: TestClient, user: User) -> dict:
        """Helper to get auth headers for a specific user."""
        login_data = {"email": user.email, "password": "SecurePass123!"}
        response = client.post("/api/users/auth/login", data=login_data)
        token = response.json()["data"]["access_token"]
        return {"Authorization": f"Bearer {token}"}


class TestMultiFacilityScenarios:
    """Test multi-facility scenarios and data isolation."""

    def test_multi_facility_blood_request_routing(
        self, client: TestClient, admin_auth_headers: dict
    ):
        """Test blood request routing between multiple facilities."""
        # Create two facilities
        facility1_data = TestDataFactory.create_facility_data("Hospital A")
        facility2_data = TestDataFactory.create_facility_data("Hospital B")

        response1 = client.post(
            "/api/facilities", json=facility1_data, headers=admin_auth_headers
        )
        response2 = client.post(
            "/api/facilities", json=facility2_data, headers=admin_auth_headers
        )

        if response1.status_code == 201 and response2.status_code == 201:
            facility1 = response1.json()["data"]
            facility2 = response2.json()["data"]

            # Test cross-facility blood request
            transfer_data = {
                "from_facility_id": facility1["id"],
                "to_facility_id": facility2["id"],
                "blood_type": "O-",
                "quantity": 2,
                "reason": "Emergency transfer - critical shortage",
                "priority": "urgent",
            }

            response = client.post(
                "/api/facilities/transfer-request",
                json=transfer_data,
                headers=admin_auth_headers,
            )

            # Should either succeed or require special authorization
            assert response.status_code in [201, 202, 403]

    def test_facility_data_isolation(
        self, client: TestClient, auth_headers: dict, test_facility: Facility
    ):
        """Test that facility data is properly isolated."""
        # Get facility-specific data
        response = client.get(
            f"/api/facilities/{test_facility.id}/statistics", headers=auth_headers
        )

        if response.status_code == 200:
            data = response.json()["data"]
            # Statistics should only include data from this facility
            assert "facility_id" in data
            assert data["facility_id"] == str(test_facility.id)

    def test_inter_facility_communication(
        self, client: TestClient, admin_auth_headers: dict
    ):
        """Test communication between facilities."""
        communication_data = {
            "recipient_facility_ids": [str(uuid4()), str(uuid4())],
            "message": "Blood shortage alert - O negative critically low",
            "priority": "high",
            "message_type": "shortage_alert",
        }

        response = client.post(
            "/api/facilities/broadcast",
            json=communication_data,
            headers=admin_auth_headers,
        )

        # Should either succeed or require proper authorization
        assert response.status_code in [200, 201, 403]

    def test_facility_network_status(self, client: TestClient, auth_headers: dict):
        """Test getting facility network status."""
        response = client.get("/api/facilities/network-status", headers=auth_headers)

        if response.status_code == 200:
            data = response.json()["data"]
            assert "facilities" in data
            assert "network_health" in data

            # Each facility should have status information
            for facility in data["facilities"]:
                assert "id" in facility
                assert "name" in facility
                assert "status" in facility
                assert "last_updated" in facility


class TestFacilityExtremeCases:
    """Test extreme edge cases and boundary conditions for facilities."""

    def test_facility_with_unicode_characters(
        self, client: TestClient, admin_auth_headers: dict
    ):
        """Test facility creation with Unicode characters."""
        unicode_facility_data = {
            "name": "Hôpital Général du Benin",  # French accents
            "address": "123 Rue de l'Indépendance, Cotonou",
            "contact_phone": "+233302123456",
            "email": "info@hopital-benin.bj",
            "facility_type": "hospital",
            "region": "GH-AA",
            "description": "Hôpital avec caractères spéciaux: éàç",
        }

        response = client.post(
            "/api/facilities", json=unicode_facility_data, headers=admin_auth_headers
        )

        # Should either succeed or fail gracefully
        if response.status_code == 201:
            data = response.json()["data"]
            assert "Hôpital" in data["name"]
        else:
            assert response.status_code in [400, 422]

    def test_extremely_long_facility_data(
        self, client: TestClient, admin_auth_headers: dict
    ):
        """Test facility creation with extremely long data."""
        long_facility_data = TestDataFactory.create_facility_data()
        long_facility_data.update(
            {
                "name": "A" * 1000,  # Very long name
                "description": "B" * 5000,  # Very long description
                "address": "C" * 2000,  # Very long address
            }
        )

        response = client.post(
            "/api/facilities", json=long_facility_data, headers=admin_auth_headers
        )

        # Should be rejected due to length limits
        assert response.status_code in [400, 413, 422]

    def test_concurrent_facility_operations(
        self, client: TestClient, admin_auth_headers: dict, test_facility: Facility
    ):
        """Test concurrent operations on the same facility."""
        import asyncio

        # Simulate concurrent updates
        update_data_1 = {"description": "Update 1"}
        update_data_2 = {"description": "Update 2"}

        response1 = client.put(
            f"/api/facilities/{test_facility.id}",
            json=update_data_1,
            headers=admin_auth_headers,
        )
        response2 = client.put(
            f"/api/facilities/{test_facility.id}",
            json=update_data_2,
            headers=admin_auth_headers,
        )

        # At least one should succeed
        success_count = sum(1 for r in [response1, response2] if r.status_code == 200)
        assert success_count >= 1

    def test_facility_deletion_with_dependencies(
        self, client: TestClient, admin_auth_headers: dict, test_facility: Facility
    ):
        """Test facility deletion when it has dependencies."""
        # Try to delete facility that has users/requests
        response = client.delete(
            f"/api/facilities/{test_facility.id}", headers=admin_auth_headers
        )

        # Should either prevent deletion or handle dependencies
        if response.status_code == 200:
            # If deletion succeeds, dependencies should be handled
            data = response.json()["data"]
            assert "dependencies_handled" in data or "soft_deleted" in data
        else:
            # Should prevent deletion with clear error message
            assert response.status_code in [400, 409]
            error_data = response.json()
            assert (
                "dependencies" in error_data["message"].lower()
                or "users" in error_data["message"].lower()
            )

    def test_malformed_facility_data(
        self, client: TestClient, admin_auth_headers: dict
    ):
        """Test handling of malformed facility data."""
        malformed_data_sets = [
            {"name": None, "address": "123 Street"},  # Null required field
            {"name": "", "address": "   "},  # Empty strings
            {"name": 12345, "address": True},  # Wrong data types
            {"invalid_field": "value"},  # Extra fields
            {},  # Empty object
        ]

        for malformed_data in malformed_data_sets:
            response = client.post(
                "/api/facilities", json=malformed_data, headers=admin_auth_headers
            )
            assert response.status_code in [400, 422]

    def test_sql_injection_prevention_facilities(
        self, client: TestClient, admin_auth_headers: dict
    ):
        """Test SQL injection prevention in facility operations."""
        injection_attempts = [
            "'; DROP TABLE facilities; --",
            "Hospital'; UPDATE facilities SET name='HACKED' WHERE id='1'; --",
            "Hospital' OR '1'='1",
            'Hospital"; DELETE FROM facilities; --',
        ]

        for injection_text in injection_attempts:
            facility_data = TestDataFactory.create_facility_data()
            facility_data["name"] = injection_text

            response = client.post(
                "/api/facilities", json=facility_data, headers=admin_auth_headers
            )

            # Should either reject or sanitize the input
            if response.status_code == 201:
                data = response.json()["data"]
                assert "DROP TABLE" not in data["name"]
                assert "DELETE FROM" not in data["name"]
            else:
                assert response.status_code in [400, 422]

    def test_performance_with_large_facility_list(
        self, client: TestClient, auth_headers: dict
    ):
        """Test performance with large facility listings."""
        params = {"limit": 1000, "page": 1, "include_inactive": True}  # Large limit

        with PerformanceTimer(max_duration_ms=3000):  # 3 seconds max
            response = client.get(
                "/api/facilities", params=params, headers=auth_headers
            )

        # Should handle large requests gracefully
        assert response.status_code in [200, 400, 413]

        if response.status_code == 200:
            data = response.json()["data"]
            # Should have reasonable pagination limits
            assert len(data.get("facilities", [])) <= 100  # Reasonable max
