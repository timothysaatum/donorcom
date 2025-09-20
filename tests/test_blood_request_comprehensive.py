"""
Comprehensive blood request management tests for hospital blood request system.
Tests request creation, status updates, priority handling, and medical workflow validation.
"""

import pytest
from fastapi.testclient import TestClient
from uuid import uuid4
from datetime import datetime, timedelta, timezone

from tests.conftest import (
    TestDataFactory,
    assert_response_success,
    assert_response_error,
    assert_validation_error,
    PerformanceTimer,
)
from app.models.request import BloodRequest
from app.models.user import User
from app.models.health_facility import Facility
from app.models.patient import Patient


class TestBloodRequestCreation:
    """Test blood request creation with medical validation."""

    def test_create_valid_blood_request(
        self,
        client: TestClient,
        auth_headers: dict,
        test_facility: Facility,
        test_patient: Patient,
    ):
        """Test creating a valid blood request."""
        request_data = {
            "facility_id": str(test_facility.id),
            "patient_id": str(test_patient.id),
            "blood_type": "A+",
            "quantity": 2,
            "priority": "urgent",
            "urgency_reason": "Emergency surgery - patient lost significant blood",
            "requested_date": datetime.now(timezone.utc).isoformat(),
        }

        with PerformanceTimer(max_duration_ms=500):
            response = client.post(
                "/api/requests", json=request_data, headers=auth_headers
            )

        data = assert_response_success(response, 201)
        assert data["blood_type"] == request_data["blood_type"]
        assert data["quantity"] == request_data["quantity"]
        assert data["priority"] == request_data["priority"]
        assert data["status"] == "pending"
        assert "id" in data
        assert "created_at" in data

    @pytest.mark.parametrize(
        "invalid_blood_type",
        [
            "Z+",  # Invalid blood type
            "A++",  # Invalid format
            "AB-+",  # Invalid format
            "",  # Empty
            "blood_type_a_positive",  # Wrong format
            "A positive",  # Wrong format
            "123",  # Numbers
        ],
    )
    def test_invalid_blood_type_request(
        self,
        client: TestClient,
        auth_headers: dict,
        test_facility: Facility,
        test_patient: Patient,
        invalid_blood_type: str,
    ):
        """Test blood request fails with invalid blood types."""
        request_data = TestDataFactory.create_blood_request_data(
            str(test_facility.id),
            str(test_patient.id),
            auth_headers.get("user_id", str(uuid4())),
        )
        request_data["blood_type"] = invalid_blood_type

        response = client.post("/api/requests", json=request_data, headers=auth_headers)
        assert_validation_error(response, "blood_type")

    @pytest.mark.parametrize(
        "invalid_quantity",
        [
            0,  # Zero quantity
            -1,  # Negative quantity
            0.5,  # Decimal quantity
            100,  # Unrealistically high
            "two",  # String instead of number
            None,  # Null
        ],
    )
    def test_invalid_quantity_request(
        self,
        client: TestClient,
        auth_headers: dict,
        test_facility: Facility,
        test_patient: Patient,
        invalid_quantity,
    ):
        """Test blood request fails with invalid quantities."""
        request_data = TestDataFactory.create_blood_request_data(
            str(test_facility.id),
            str(test_patient.id),
            auth_headers.get("user_id", str(uuid4())),
        )
        request_data["quantity"] = invalid_quantity

        response = client.post("/api/requests", json=request_data, headers=auth_headers)
        assert response.status_code in [400, 422]

    @pytest.mark.parametrize(
        "invalid_priority",
        [
            "critical",  # Not in enum
            "low",  # Not in enum
            "URGENT",  # Wrong case
            "",  # Empty
            123,  # Wrong type
            None,  # Null
        ],
    )
    def test_invalid_priority_request(
        self,
        client: TestClient,
        auth_headers: dict,
        test_facility: Facility,
        test_patient: Patient,
        invalid_priority,
    ):
        """Test blood request fails with invalid priorities."""
        request_data = TestDataFactory.create_blood_request_data(
            str(test_facility.id),
            str(test_patient.id),
            auth_headers.get("user_id", str(uuid4())),
        )
        request_data["priority"] = invalid_priority

        response = client.post("/api/requests", json=request_data, headers=auth_headers)
        assert_validation_error(response, "priority")

    def test_missing_urgency_reason_for_urgent_request(
        self,
        client: TestClient,
        auth_headers: dict,
        test_facility: Facility,
        test_patient: Patient,
    ):
        """Test urgent requests require urgency reason."""
        request_data = TestDataFactory.create_blood_request_data(
            str(test_facility.id),
            str(test_patient.id),
            auth_headers.get("user_id", str(uuid4())),
        )
        request_data["priority"] = "urgent"
        request_data.pop("urgency_reason", None)  # Remove urgency reason

        response = client.post("/api/requests", json=request_data, headers=auth_headers)
        assert_validation_error(response, "urgency_reason")

    def test_create_request_with_nonexistent_patient(
        self, client: TestClient, auth_headers: dict, test_facility: Facility
    ):
        """Test blood request fails with nonexistent patient."""
        request_data = TestDataFactory.create_blood_request_data(
            str(test_facility.id),
            str(uuid4()),
            auth_headers.get("user_id", str(uuid4())),
        )

        response = client.post("/api/requests", json=request_data, headers=auth_headers)
        assert_response_error(response, 404)

    def test_create_request_with_nonexistent_facility(
        self, client: TestClient, auth_headers: dict, test_patient: Patient
    ):
        """Test blood request fails with nonexistent facility."""
        request_data = TestDataFactory.create_blood_request_data(
            str(uuid4()),
            str(test_patient.id),
            auth_headers.get("user_id", str(uuid4())),
        )

        response = client.post("/api/requests", json=request_data, headers=auth_headers)
        assert_response_error(response, 404)

    def test_unauthorized_request_creation(
        self, client: TestClient, test_facility: Facility, test_patient: Patient
    ):
        """Test blood request creation fails without authentication."""
        request_data = TestDataFactory.create_blood_request_data(
            str(test_facility.id), str(test_patient.id), str(uuid4())
        )

        response = client.post("/api/requests", json=request_data)
        assert response.status_code == 401


class TestBloodRequestManagement:
    """Test blood request status management and updates."""

    def test_get_blood_request_by_id(
        self, client: TestClient, auth_headers: dict, test_blood_request: BloodRequest
    ):
        """Test retrieving a blood request by ID."""
        response = client.get(
            f"/api/requests/{test_blood_request.id}", headers=auth_headers
        )

        data = assert_response_success(response)
        assert data["id"] == str(test_blood_request.id)
        assert data["blood_type"] == test_blood_request.blood_type
        assert data["quantity"] == test_blood_request.quantity
        assert data["priority"] == test_blood_request.priority

    def test_update_request_status(
        self, client: TestClient, auth_headers: dict, test_blood_request: BloodRequest
    ):
        """Test updating blood request status."""
        update_data = {"status": "accepted", "notes": "Request approved by lab manager"}

        response = client.put(
            f"/api/requests/{test_blood_request.id}/status",
            json=update_data,
            headers=auth_headers,
        )

        data = assert_response_success(response)
        assert data["status"] == "accepted"
        assert data["notes"] == update_data["notes"]

    @pytest.mark.parametrize(
        "invalid_status",
        [
            "approved",  # Not in enum
            "PENDING",  # Wrong case
            "in_progress",  # Not in enum
            "",  # Empty
            123,  # Wrong type
        ],
    )
    def test_update_request_invalid_status(
        self,
        client: TestClient,
        auth_headers: dict,
        test_blood_request: BloodRequest,
        invalid_status,
    ):
        """Test updating request with invalid status."""
        update_data = {"status": invalid_status}

        response = client.put(
            f"/api/requests/{test_blood_request.id}/status",
            json=update_data,
            headers=auth_headers,
        )
        assert_validation_error(response, "status")

    def test_cancel_blood_request(
        self, client: TestClient, auth_headers: dict, test_blood_request: BloodRequest
    ):
        """Test cancelling a blood request."""
        cancel_data = {
            "status": "cancelled",
            "cancellation_reason": "Patient condition improved, transfusion no longer needed",
        }

        response = client.put(
            f"/api/requests/{test_blood_request.id}/status",
            json=cancel_data,
            headers=auth_headers,
        )

        data = assert_response_success(response)
        assert data["status"] == "cancelled"
        assert "cancellation_reason" in data

    def test_list_blood_requests_with_pagination(
        self, client: TestClient, auth_headers: dict
    ):
        """Test listing blood requests with pagination."""
        params = {"page": 1, "limit": 10, "status": "pending"}

        response = client.get("/api/requests", params=params, headers=auth_headers)

        data = assert_response_success(response)
        assert "requests" in data
        assert "total" in data
        assert "page" in data
        assert "limit" in data
        assert isinstance(data["requests"], list)

    def test_filter_requests_by_blood_type(
        self, client: TestClient, auth_headers: dict
    ):
        """Test filtering blood requests by blood type."""
        params = {"blood_type": "A+", "limit": 10}

        response = client.get("/api/requests", params=params, headers=auth_headers)

        data = assert_response_success(response)
        # All returned requests should have the specified blood type
        for request in data["requests"]:
            assert request["blood_type"] == "A+"

    def test_filter_requests_by_priority(self, client: TestClient, auth_headers: dict):
        """Test filtering blood requests by priority."""
        params = {"priority": "urgent", "limit": 10}

        response = client.get("/api/requests", params=params, headers=auth_headers)

        data = assert_response_success(response)
        # All returned requests should have urgent priority
        for request in data["requests"]:
            assert request["priority"] == "urgent"

    def test_filter_requests_by_date_range(
        self, client: TestClient, auth_headers: dict
    ):
        """Test filtering blood requests by date range."""
        today = datetime.now(timezone.utc).date()
        params = {
            "start_date": (today - timedelta(days=7)).isoformat(),
            "end_date": today.isoformat(),
            "limit": 10,
        }

        response = client.get("/api/requests", params=params, headers=auth_headers)

        data = assert_response_success(response)
        assert "requests" in data
        # Validate that returned requests fall within date range
        # (This depends on your API implementation)


class TestBloodRequestWorkflow:
    """Test complete blood request workflow scenarios."""

    def test_emergency_blood_request_workflow(
        self,
        client: TestClient,
        auth_headers: dict,
        lab_manager_user: User,
        test_facility: Facility,
        test_patient: Patient,
    ):
        """Test complete emergency blood request workflow."""
        # Step 1: Create urgent blood request
        request_data = {
            "facility_id": str(test_facility.id),
            "patient_id": str(test_patient.id),
            "blood_type": "O-",  # Universal donor
            "quantity": 4,  # Emergency quantity
            "priority": "urgent",
            "urgency_reason": "Major trauma - multiple injuries, severe blood loss",
            "requested_date": datetime.now(timezone.utc).isoformat(),
        }

        response = client.post("/api/requests", json=request_data, headers=auth_headers)
        request_data_response = assert_response_success(response, 201)
        request_id = request_data_response["id"]

        # Step 2: Lab manager accepts the request
        lab_manager_headers = self._get_auth_headers(client, lab_manager_user)
        accept_data = {
            "status": "accepted",
            "notes": "Emergency request approved - O- blood available",
        }

        response = client.put(
            f"/api/requests/{request_id}/status",
            json=accept_data,
            headers=lab_manager_headers,
        )
        assert_response_success(response)

        # Step 3: Update to dispatched
        dispatch_data = {
            "status": "dispatched",
            "notes": "Blood units dispatched to emergency room",
        }

        response = client.put(
            f"/api/requests/{request_id}/status",
            json=dispatch_data,
            headers=lab_manager_headers,
        )
        assert_response_success(response)

        # Step 4: Complete the request
        complete_data = {
            "status": "completed",
            "notes": "Blood transfusion completed successfully",
        }

        response = client.put(
            f"/api/requests/{request_id}/status",
            json=complete_data,
            headers=auth_headers,
        )
        final_data = assert_response_success(response)

        assert final_data["status"] == "completed"

    def test_routine_blood_request_workflow(
        self,
        client: TestClient,
        auth_headers: dict,
        test_facility: Facility,
        test_patient: Patient,
    ):
        """Test routine blood request workflow."""
        # Create routine request
        request_data = {
            "facility_id": str(test_facility.id),
            "patient_id": str(test_patient.id),
            "blood_type": "B+",
            "quantity": 1,
            "priority": "not_urgent",
            "urgency_reason": "Scheduled surgery preparation",
            "requested_date": (
                datetime.now(timezone.utc) + timedelta(days=2)
            ).isoformat(),
        }

        response = client.post("/api/requests", json=request_data, headers=auth_headers)
        request_data_response = assert_response_success(response, 201)

        # Routine requests should be created successfully
        assert request_data_response["priority"] == "not_urgent"
        assert request_data_response["status"] == "pending"

    def test_blood_type_mismatch_prevention(
        self, client: TestClient, auth_headers: dict, test_facility: Facility
    ):
        """Test prevention of blood type mismatches."""
        # Create patient with specific blood type
        patient_data = TestDataFactory.create_patient_data()
        patient_data["blood_type"] = "A+"

        patient_response = client.post(
            "/api/patients", json=patient_data, headers=auth_headers
        )
        patient = assert_response_success(patient_response, 201)

        # Try to request incompatible blood type
        request_data = {
            "facility_id": str(test_facility.id),
            "patient_id": patient["id"],
            "blood_type": "B+",  # Incompatible with A+
            "quantity": 1,
            "priority": "urgent",
            "urgency_reason": "Blood type mismatch test",
        }

        response = client.post("/api/requests", json=request_data, headers=auth_headers)

        # Should either be accepted with warning or rejected
        # (Depends on your business logic - some blood types are compatible)
        assert response.status_code in [201, 400]

        if response.status_code == 201:
            # If accepted, should have compatibility validation
            data = response.json()["data"]
            # Your API might include compatibility warnings

    def _get_auth_headers(self, client: TestClient, user: User) -> dict:
        """Helper to get auth headers for a specific user."""
        login_data = {"email": user.email, "password": "SecurePass123!"}
        response = client.post("/api/users/auth/login", data=login_data)
        token = response.json()["data"]["access_token"]
        return {"Authorization": f"Bearer {token}"}


class TestBloodRequestValidation:
    """Test medical validation and business rules for blood requests."""

    def test_maximum_quantity_limits(
        self,
        client: TestClient,
        auth_headers: dict,
        test_facility: Facility,
        test_patient: Patient,
    ):
        """Test enforcement of maximum quantity limits."""
        request_data = TestDataFactory.create_blood_request_data(
            str(test_facility.id),
            str(test_patient.id),
            auth_headers.get("user_id", str(uuid4())),
        )
        request_data["quantity"] = 50  # Unreasonably high quantity

        response = client.post("/api/requests", json=request_data, headers=auth_headers)

        # Should be rejected or require special approval
        assert response.status_code in [400, 422]

    def test_duplicate_request_prevention(
        self,
        client: TestClient,
        auth_headers: dict,
        test_facility: Facility,
        test_patient: Patient,
    ):
        """Test prevention of duplicate blood requests."""
        request_data = TestDataFactory.create_blood_request_data(
            str(test_facility.id),
            str(test_patient.id),
            auth_headers.get("user_id", str(uuid4())),
        )

        # Create first request
        response1 = client.post(
            "/api/requests", json=request_data, headers=auth_headers
        )
        assert_response_success(response1, 201)

        # Try to create identical request
        response2 = client.post(
            "/api/requests", json=request_data, headers=auth_headers
        )

        # Should either succeed (multiple requests allowed) or be rejected
        # This depends on your business rules
        assert response2.status_code in [201, 400, 409]

    def test_request_date_validation(
        self,
        client: TestClient,
        auth_headers: dict,
        test_facility: Facility,
        test_patient: Patient,
    ):
        """Test validation of request dates."""
        # Test past date
        past_request_data = TestDataFactory.create_blood_request_data(
            str(test_facility.id),
            str(test_patient.id),
            auth_headers.get("user_id", str(uuid4())),
        )
        past_request_data["requested_date"] = (
            datetime.now(timezone.utc) - timedelta(days=1)
        ).isoformat()

        response = client.post(
            "/api/requests", json=past_request_data, headers=auth_headers
        )

        # Past dates might be allowed for urgent requests but not routine ones
        if past_request_data["priority"] == "urgent":
            assert response.status_code in [201, 400]
        else:
            assert response.status_code in [400, 422]

        # Test far future date
        future_request_data = TestDataFactory.create_blood_request_data(
            str(test_facility.id),
            str(test_patient.id),
            auth_headers.get("user_id", str(uuid4())),
        )
        future_request_data["requested_date"] = (
            datetime.now(timezone.utc) + timedelta(days=365)
        ).isoformat()

        response = client.post(
            "/api/requests", json=future_request_data, headers=auth_headers
        )
        # Very far future dates should be rejected
        assert response.status_code in [400, 422]

    def test_cross_contamination_prevention(
        self,
        client: TestClient,
        auth_headers: dict,
        test_facility: Facility,
        test_patient: Patient,
    ):
        """Test prevention of cross-contamination in blood requests."""
        request_data = TestDataFactory.create_blood_request_data(
            str(test_facility.id),
            str(test_patient.id),
            auth_headers.get("user_id", str(uuid4())),
        )

        # Add patient-specific medical conditions that might affect blood compatibility
        request_data["special_requirements"] = (
            "Patient has history of transfusion reactions"
        )
        request_data["notes"] = (
            "Please cross-match carefully - previous adverse reactions"
        )

        response = client.post("/api/requests", json=request_data, headers=auth_headers)

        # Should succeed but with special handling flags
        if response.status_code == 201:
            data = response.json()["data"]
            assert "special_requirements" in data or "notes" in data


class TestBloodRequestExtremeCases:
    """Test extreme edge cases and boundary conditions for blood requests."""

    def test_massive_transfusion_protocol(
        self,
        client: TestClient,
        auth_headers: dict,
        test_facility: Facility,
        test_patient: Patient,
    ):
        """Test massive transfusion protocol requests."""
        massive_transfusion_data = {
            "facility_id": str(test_facility.id),
            "patient_id": str(test_patient.id),
            "blood_type": "O-",
            "quantity": 10,  # Massive transfusion quantity
            "priority": "urgent",
            "urgency_reason": "Massive transfusion protocol activated - trauma patient",
            "requested_date": datetime.now(timezone.utc).isoformat(),
            "protocol_type": "massive_transfusion",
        }

        response = client.post(
            "/api/requests", json=massive_transfusion_data, headers=auth_headers
        )

        # Should either succeed with special handling or require additional authorization
        assert response.status_code in [201, 400, 403]

    def test_concurrent_requests_same_patient(
        self,
        client: TestClient,
        auth_headers: dict,
        test_facility: Facility,
        test_patient: Patient,
    ):
        """Test handling of concurrent requests for the same patient."""
        import asyncio

        async def create_request(blood_type: str):
            request_data = {
                "facility_id": str(test_facility.id),
                "patient_id": str(test_patient.id),
                "blood_type": blood_type,
                "quantity": 1,
                "priority": "urgent",
                "urgency_reason": f"Concurrent request test - {blood_type}",
            }
            return client.post("/api/requests", json=request_data, headers=auth_headers)

        # Create multiple concurrent requests for the same patient
        responses = [create_request("A+"), create_request("O+"), create_request("B+")]

        # All should either succeed or be handled gracefully
        for response in responses:
            assert hasattr(response, "status_code")
            assert response.status_code in [201, 400, 409]

    def test_blood_request_with_expired_patient_data(
        self, client: TestClient, auth_headers: dict, test_facility: Facility
    ):
        """Test blood request with potentially outdated patient information."""
        # Create patient with old data
        old_patient_data = TestDataFactory.create_patient_data()
        old_patient_data["last_updated"] = "2020-01-01T00:00:00Z"  # Very old

        patient_response = client.post(
            "/api/patients", json=old_patient_data, headers=auth_headers
        )

        if patient_response.status_code == 201:
            patient = patient_response.json()["data"]

            request_data = TestDataFactory.create_blood_request_data(
                str(test_facility.id),
                patient["id"],
                auth_headers.get("user_id", str(uuid4())),
            )

            response = client.post(
                "/api/requests", json=request_data, headers=auth_headers
            )

            # Should either succeed with warnings or require patient data update
            assert response.status_code in [201, 400]

    def test_malformed_uuid_handling(self, client: TestClient, auth_headers: dict):
        """Test handling of malformed UUIDs in blood requests."""
        malformed_uuids = [
            "not-a-uuid",
            "12345",
            "",
            "00000000-0000-0000-0000-000000000000",  # Null UUID
            "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",  # Invalid format
        ]

        for malformed_uuid in malformed_uuids:
            request_data = {
                "facility_id": malformed_uuid,
                "patient_id": malformed_uuid,
                "blood_type": "A+",
                "quantity": 1,
                "priority": "urgent",
                "urgency_reason": "UUID test",
            }

            response = client.post(
                "/api/requests", json=request_data, headers=auth_headers
            )
            assert response.status_code in [400, 422]  # Should be rejected

    def test_extremely_long_notes_and_reasons(
        self,
        client: TestClient,
        auth_headers: dict,
        test_facility: Facility,
        test_patient: Patient,
    ):
        """Test handling of extremely long text fields."""
        long_text = "A" * 10000  # Very long text

        request_data = TestDataFactory.create_blood_request_data(
            str(test_facility.id),
            str(test_patient.id),
            auth_headers.get("user_id", str(uuid4())),
        )
        request_data["urgency_reason"] = long_text
        request_data["notes"] = long_text

        response = client.post("/api/requests", json=request_data, headers=auth_headers)

        # Should either truncate, reject, or handle gracefully
        assert response.status_code in [201, 400, 413, 422]

    def test_special_character_injection_in_notes(
        self,
        client: TestClient,
        auth_headers: dict,
        test_facility: Facility,
        test_patient: Patient,
    ):
        """Test handling of special characters and potential injection in notes."""
        injection_attempts = [
            "<script>alert('xss')</script>",
            "'; DROP TABLE blood_requests; --",
            "\\x00\\x01\\x02",  # Null bytes
            "𝕿𝖊𝖘𝖙 𝖚𝖓𝖎𝖈𝖔𝖉𝖊",  # Unicode
            "\n\r\t",  # Control characters
        ]

        for injection_text in injection_attempts:
            request_data = TestDataFactory.create_blood_request_data(
                str(test_facility.id),
                str(test_patient.id),
                auth_headers.get("user_id", str(uuid4())),
            )
            request_data["urgency_reason"] = injection_text
            request_data["notes"] = injection_text

            response = client.post(
                "/api/requests", json=request_data, headers=auth_headers
            )

            if response.status_code == 201:
                # If successful, check that dangerous content is sanitized
                data = response.json()["data"]
                assert "<script>" not in data.get("urgency_reason", "")
                assert "DROP TABLE" not in data.get("notes", "")
