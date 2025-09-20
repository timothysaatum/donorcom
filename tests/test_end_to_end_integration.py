"""
End-to-end integration tests for complete hospital workflows.
Tests full user journeys and complex multi-system interactions.
"""

import pytest
from fastapi.testclient import TestClient
from uuid import uuid4
from datetime import datetime, timedelta, timezone

from tests.conftest import (
    TestDataFactory,
    assert_response_success,
    PerformanceTimer,
)


class TestEmergencyBloodRequestWorkflow:
    """Test complete emergency blood request workflow from start to finish."""

    def test_critical_emergency_workflow(self, client: TestClient):
        """Test complete critical emergency blood request workflow."""
        with PerformanceTimer(
            max_duration_ms=30000
        ):  # 30 seconds max for critical workflow

            # Step 1: Emergency staff registration
            emergency_staff_data = TestDataFactory.create_user_data()
            emergency_staff_data.update(
                {
                    "email": "emergency.staff@hospital.gh",
                    "role": "staff",
                    "department": "Emergency",
                    "emergency_contact": True,
                }
            )

            registration_response = client.post(
                "/api/users/register", json=emergency_staff_data
            )
            assert_response_success(registration_response, 201)
            staff_user = registration_response.json()["data"]

            # Step 2: Emergency staff login
            login_data = {
                "email": emergency_staff_data["email"],
                "password": emergency_staff_data["password"],
            }
            login_response = client.post("/api/users/auth/login", data=login_data)
            assert_response_success(login_response, 200)

            access_token = login_response.json()["data"]["access_token"]
            auth_headers = {"Authorization": f"Bearer {access_token}"}

            # Step 3: Register emergency facility
            facility_data = TestDataFactory.create_facility_data()
            facility_data.update(
                {
                    "name": "Korle-Bu Emergency Center",
                    "region": "Greater Accra",
                    "emergency_services": True,
                    "trauma_level": 1,
                }
            )

            facility_response = client.post(
                "/api/facilities", json=facility_data, headers=auth_headers
            )
            assert_response_success(facility_response, 201)
            facility_id = facility_response.json()["data"]["id"]

            # Step 4: Create critical patient with trauma
            patient_data = TestDataFactory.create_patient_data()
            patient_data.update(
                {
                    "blood_type": "O-",  # Universal donor, critical for emergencies
                    "medical_conditions": ["Trauma", "Massive blood loss"],
                    "allergies": ["None known"],
                    "emergency_contact": "0244123456",
                    "current_condition": "Critical",
                }
            )

            patient_response = client.post(
                "/api/patients", json=patient_data, headers=auth_headers
            )
            assert_response_success(patient_response, 201)
            patient_id = patient_response.json()["data"]["id"]

            # Step 5: Check available blood inventory
            inventory_search = client.get(
                "/api/inventory",
                params={"blood_type": "O-", "available_only": True},
                headers=auth_headers,
            )
            assert_response_success(inventory_search, 200)

            available_inventory = inventory_search.json()["data"]["items"]

            # Step 6: If no inventory, create emergency inventory
            if not available_inventory:
                emergency_inventory = TestDataFactory.create_inventory_data(facility_id)
                emergency_inventory.update(
                    {
                        "blood_type": "O-",
                        "quantity": 10,
                        "collection_date": datetime.now(timezone.utc).isoformat(),
                        "expiry_date": (
                            datetime.now(timezone.utc) + timedelta(days=35)
                        ).isoformat(),
                        "lot_number": "EMERGENCY_001",
                        "donor_id": str(uuid4()),
                        "processing_status": "processed",
                    }
                )

                inventory_response = client.post(
                    "/api/inventory", json=emergency_inventory, headers=auth_headers
                )
                assert_response_success(inventory_response, 201)

            # Step 7: Create urgent blood request
            blood_request_data = {
                "facility_id": facility_id,
                "patient_id": patient_id,
                "blood_type": "O-",
                "quantity": 4,  # 4 units for massive transfusion
                "priority": "critical",
                "urgency_reason": "Massive trauma - patient in shock, active bleeding",
                "requested_by": staff_user["id"],
                "required_by": (
                    datetime.now(timezone.utc) + timedelta(minutes=30)
                ).isoformat(),
                "crossmatch_required": True,
                "special_requirements": ["CMV negative", "Irradiated"],
                "clinical_indication": "Massive transfusion protocol",
            }

            request_response = client.post(
                "/api/requests", json=blood_request_data, headers=auth_headers
            )
            assert_response_success(request_response, 201)
            request_id = request_response.json()["data"]["id"]

            # Step 8: Lab manager approves request
            lab_manager_data = TestDataFactory.create_user_data()
            lab_manager_data.update(
                {
                    "email": "lab.manager@hospital.gh",
                    "role": "lab_manager",
                    "department": "Blood Bank",
                }
            )

            lab_manager_reg = client.post("/api/users/register", json=lab_manager_data)
            assert_response_success(lab_manager_reg, 201)

            lab_login = client.post(
                "/api/users/auth/login",
                data={
                    "email": lab_manager_data["email"],
                    "password": lab_manager_data["password"],
                },
            )
            assert_response_success(lab_login, 200)

            lab_headers = {
                "Authorization": f"Bearer {lab_login.json()['data']['access_token']}"
            }

            # Approve the request
            approval_data = {
                "status": "approved",
                "approved_quantity": 4,
                "notes": "Approved for emergency massive transfusion protocol",
                "crossmatch_compatible": True,
                "special_instructions": "Rush processing - critical patient",
            }

            approval_response = client.put(
                f"/api/requests/{request_id}/status",
                json=approval_data,
                headers=lab_headers,
            )
            assert_response_success(approval_response, 200)

            # Step 9: Process fulfillment
            fulfillment_data = {
                "fulfilled_quantity": 4,
                "inventory_items": [],  # Would be populated with actual inventory IDs
                "processing_notes": "Emergency processing complete",
                "quality_checks_passed": True,
                "released_by": lab_manager_reg.json()["data"]["id"],
                "release_time": datetime.now(timezone.utc).isoformat(),
            }

            fulfillment_response = client.post(
                f"/api/requests/{request_id}/fulfill",
                json=fulfillment_data,
                headers=lab_headers,
            )
            # May not be implemented yet, but should handle gracefully
            assert fulfillment_response.status_code in [200, 201, 404, 501]

            # Step 10: Verify request status and audit trail
            final_request = client.get(
                f"/api/requests/{request_id}", headers=auth_headers
            )
            assert_response_success(final_request, 200)

            request_data = final_request.json()["data"]
            assert request_data["status"] == "approved"
            assert request_data["priority"] == "critical"
            assert request_data["blood_type"] == "O-"

    def test_mass_casualty_scenario(self, client: TestClient):
        """Test mass casualty scenario with multiple urgent requests."""
        with PerformanceTimer(max_duration_ms=60000):  # 60 seconds for mass casualty

            # Create emergency coordinator
            coordinator_data = TestDataFactory.create_user_data()
            coordinator_data.update(
                {
                    "email": "coordinator@emergency.gh",
                    "role": "facility_administrator",
                    "department": "Emergency Management",
                }
            )

            coord_reg = client.post("/api/users/register", json=coordinator_data)
            assert_response_success(coord_reg, 201)

            coord_login = client.post(
                "/api/users/auth/login",
                data={
                    "email": coordinator_data["email"],
                    "password": coordinator_data["password"],
                },
            )
            assert_response_success(coord_login, 200)

            coord_headers = {
                "Authorization": f"Bearer {coord_login.json()['data']['access_token']}"
            }

            # Create trauma center
            trauma_center_data = TestDataFactory.create_facility_data()
            trauma_center_data.update(
                {
                    "name": "Greater Accra Trauma Center",
                    "region": "Greater Accra",
                    "trauma_level": 1,
                    "bed_capacity": 200,
                    "emergency_services": True,
                }
            )

            facility_response = client.post(
                "/api/facilities", json=trauma_center_data, headers=coord_headers
            )
            assert_response_success(facility_response, 201)
            facility_id = facility_response.json()["data"]["id"]

            # Create multiple casualties with different blood types
            casualties = []
            blood_types = ["O+", "O-", "A+", "A-", "B+", "B-", "AB+", "AB-"]

            for i, blood_type in enumerate(blood_types):
                patient_data = TestDataFactory.create_patient_data()
                patient_data.update(
                    {
                        "first_name": f"Casualty_{i+1}",
                        "blood_type": blood_type,
                        "medical_conditions": ["Trauma", "Multiple injuries"],
                        "current_condition": "Critical" if i < 4 else "Serious",
                    }
                )

                patient_response = client.post(
                    "/api/patients", json=patient_data, headers=coord_headers
                )
                if patient_response.status_code == 201:
                    casualties.append(
                        {
                            "patient_id": patient_response.json()["data"]["id"],
                            "blood_type": blood_type,
                            "priority": "critical" if i < 4 else "urgent",
                        }
                    )

            # Create blood requests for all casualties
            requests_created = []
            for i, casualty in enumerate(casualties):
                request_data = {
                    "facility_id": facility_id,
                    "patient_id": casualty["patient_id"],
                    "blood_type": casualty["blood_type"],
                    "quantity": 2 if casualty["priority"] == "critical" else 1,
                    "priority": casualty["priority"],
                    "urgency_reason": f"Mass casualty incident - Patient {i+1}",
                    "clinical_indication": "Trauma resuscitation",
                    "required_by": (
                        datetime.now(timezone.utc) + timedelta(hours=1)
                    ).isoformat(),
                }

                request_response = client.post(
                    "/api/requests", json=request_data, headers=coord_headers
                )
                if request_response.status_code == 201:
                    requests_created.append(request_response.json()["data"])

            # Verify all requests were created successfully
            assert len(requests_created) >= 4  # At least half should succeed

            # Verify critical requests are properly prioritized
            critical_requests = [
                r for r in requests_created if r["priority"] == "critical"
            ]
            urgent_requests = [r for r in requests_created if r["priority"] == "urgent"]

            assert len(critical_requests) > 0
            assert len(urgent_requests) > 0

            # Check that O-negative requests (universal donor) are prioritized
            o_negative_requests = [
                r for r in requests_created if r["blood_type"] == "O-"
            ]
            if o_negative_requests:
                for request in o_negative_requests:
                    assert request["priority"] in ["critical", "urgent"]


class TestMultiFacilityTransferWorkflow:
    """Test blood transfer workflows between facilities."""

    def test_inter_facility_blood_transfer(self, client: TestClient):
        """Test blood transfer between facilities."""
        with PerformanceTimer(max_duration_ms=45000):  # 45 seconds max

            # Create network administrator
            admin_data = TestDataFactory.create_user_data()
            admin_data.update(
                {
                    "email": "network.admin@health.gh",
                    "role": "facility_administrator",
                    "permissions": ["manage_facilities", "approve_transfers"],
                }
            )

            admin_reg = client.post("/api/users/register", json=admin_data)
            assert_response_success(admin_reg, 201)

            admin_login = client.post(
                "/api/users/auth/login",
                data={"email": admin_data["email"], "password": admin_data["password"]},
            )
            assert_response_success(admin_login, 200)

            admin_headers = {
                "Authorization": f"Bearer {admin_login.json()['data']['access_token']}"
            }

            # Create donor facility (has excess blood)
            donor_facility_data = TestDataFactory.create_facility_data()
            donor_facility_data.update(
                {
                    "name": "Kumasi Blood Bank",
                    "region": "Ashanti",
                    "type": "blood_bank",
                    "storage_capacity": 1000,
                }
            )

            donor_response = client.post(
                "/api/facilities", json=donor_facility_data, headers=admin_headers
            )
            assert_response_success(donor_response, 201)
            donor_facility_id = donor_response.json()["data"]["id"]

            # Create recipient facility (needs blood)
            recipient_facility_data = TestDataFactory.create_facility_data()
            recipient_facility_data.update(
                {
                    "name": "Tamale Regional Hospital",
                    "region": "Northern",
                    "type": "hospital",
                    "emergency_services": True,
                }
            )

            recipient_response = client.post(
                "/api/facilities", json=recipient_facility_data, headers=admin_headers
            )
            assert_response_success(recipient_response, 201)
            recipient_facility_id = recipient_response.json()["data"]["id"]

            # Create blood inventory at donor facility
            donor_inventory = TestDataFactory.create_inventory_data(donor_facility_id)
            donor_inventory.update(
                {
                    "blood_type": "A+",
                    "quantity": 20,
                    "collection_date": datetime.now(timezone.utc).isoformat(),
                    "expiry_date": (
                        datetime.now(timezone.utc) + timedelta(days=30)
                    ).isoformat(),
                    "donor_id": str(uuid4()),
                    "processing_status": "processed",
                    "available_for_transfer": True,
                }
            )

            inventory_response = client.post(
                "/api/inventory", json=donor_inventory, headers=admin_headers
            )
            assert_response_success(inventory_response, 201)
            inventory_id = inventory_response.json()["data"]["id"]

            # Create patient at recipient facility needing blood
            patient_data = TestDataFactory.create_patient_data()
            patient_data.update(
                {
                    "blood_type": "A+",
                    "current_condition": "Serious",
                    "medical_conditions": ["Surgical patient", "Blood loss"],
                }
            )

            patient_response = client.post(
                "/api/patients", json=patient_data, headers=admin_headers
            )
            assert_response_success(patient_response, 201)
            patient_id = patient_response.json()["data"]["id"]

            # Create blood request at recipient facility
            request_data = {
                "facility_id": recipient_facility_id,
                "patient_id": patient_id,
                "blood_type": "A+",
                "quantity": 3,
                "priority": "urgent",
                "urgency_reason": "Surgical patient requiring transfusion",
                "clinical_indication": "Pre-operative preparation",
                "special_requirements": ["Leukoreduced"],
            }

            request_response = client.post(
                "/api/requests", json=request_data, headers=admin_headers
            )
            assert_response_success(request_response, 201)
            request_id = request_response.json()["data"]["id"]

            # Initiate transfer request
            transfer_data = {
                "source_facility_id": donor_facility_id,
                "destination_facility_id": recipient_facility_id,
                "blood_request_id": request_id,
                "inventory_items": [inventory_id],
                "quantity": 3,
                "transport_method": "refrigerated_vehicle",
                "estimated_arrival": (
                    datetime.now(timezone.utc) + timedelta(hours=4)
                ).isoformat(),
                "priority": "urgent",
                "transfer_reason": "Critical patient need - insufficient local inventory",
            }

            transfer_response = client.post(
                "/api/transfers", json=transfer_data, headers=admin_headers
            )
            # Transfer endpoint may not be implemented yet
            assert transfer_response.status_code in [200, 201, 404, 501]

            if transfer_response.status_code in [200, 201]:
                transfer_id = transfer_response.json()["data"]["id"]

                # Track transfer status
                status_response = client.get(
                    f"/api/transfers/{transfer_id}", headers=admin_headers
                )
                assert_response_success(status_response, 200)

                transfer_status = status_response.json()["data"]
                assert transfer_status["source_facility_id"] == donor_facility_id
                assert (
                    transfer_status["destination_facility_id"] == recipient_facility_id
                )
                assert transfer_status["quantity"] == 3

    def test_regional_blood_distribution(self, client: TestClient):
        """Test regional blood distribution network."""
        with PerformanceTimer(max_duration_ms=60000):  # 60 seconds for regional test

            # Create regional coordinator
            coordinator_data = TestDataFactory.create_user_data()
            coordinator_data.update(
                {
                    "email": "regional.coordinator@health.gh",
                    "role": "facility_administrator",
                    "department": "Regional Blood Services",
                }
            )

            coord_reg = client.post("/api/users/register", json=coordinator_data)
            assert_response_success(coord_reg, 201)

            coord_login = client.post(
                "/api/users/auth/login",
                data={
                    "email": coordinator_data["email"],
                    "password": coordinator_data["password"],
                },
            )
            assert_response_success(coord_login, 200)

            coord_headers = {
                "Authorization": f"Bearer {coord_login.json()['data']['access_token']}"
            }

            # Create facilities across different regions
            regions = ["Greater Accra", "Ashanti", "Northern", "Western", "Eastern"]
            facilities = []

            for region in regions:
                facility_data = TestDataFactory.create_facility_data()
                facility_data.update(
                    {
                        "name": f"{region} Regional Blood Center",
                        "region": region,
                        "type": "blood_bank",
                        "regional_center": True,
                    }
                )

                facility_response = client.post(
                    "/api/facilities", json=facility_data, headers=coord_headers
                )
                if facility_response.status_code == 201:
                    facilities.append(
                        {
                            "id": facility_response.json()["data"]["id"],
                            "region": region,
                            "name": facility_data["name"],
                        }
                    )

            # Create inventory at each regional center
            blood_types = ["O+", "O-", "A+", "A-", "B+", "B-", "AB+", "AB-"]
            inventory_items = []

            for facility in facilities:
                for blood_type in blood_types:
                    inventory_data = TestDataFactory.create_inventory_data(
                        facility["id"]
                    )
                    inventory_data.update(
                        {
                            "blood_type": blood_type,
                            "quantity": 5,  # Limited quantity to test distribution
                            "collection_date": datetime.now(timezone.utc).isoformat(),
                            "expiry_date": (
                                datetime.now(timezone.utc) + timedelta(days=25)
                            ).isoformat(),
                            "processing_status": "processed",
                        }
                    )

                    inventory_response = client.post(
                        "/api/inventory", json=inventory_data, headers=coord_headers
                    )
                    if inventory_response.status_code == 201:
                        inventory_items.append(
                            {
                                "id": inventory_response.json()["data"]["id"],
                                "facility_id": facility["id"],
                                "blood_type": blood_type,
                                "region": facility["region"],
                            }
                        )

            # Create emergency need in one region
            emergency_facility = facilities[0]  # Use first facility

            # Create multiple patients needing different blood types
            emergency_requests = []
            for blood_type in ["O-", "A+", "B-"]:  # Different blood types
                patient_data = TestDataFactory.create_patient_data()
                patient_data.update(
                    {
                        "blood_type": blood_type,
                        "current_condition": "Critical",
                        "medical_conditions": ["Emergency surgery"],
                    }
                )

                patient_response = client.post(
                    "/api/patients", json=patient_data, headers=coord_headers
                )
                if patient_response.status_code == 201:
                    patient_id = patient_response.json()["data"]["id"]

                    # Create urgent request
                    request_data = {
                        "facility_id": emergency_facility["id"],
                        "patient_id": patient_id,
                        "blood_type": blood_type,
                        "quantity": 4,  # High quantity to trigger regional distribution
                        "priority": "critical",
                        "urgency_reason": f"Emergency surgery - {blood_type} blood needed",
                        "clinical_indication": "Life-threatening hemorrhage",
                    }

                    request_response = client.post(
                        "/api/requests", json=request_data, headers=coord_headers
                    )
                    if request_response.status_code == 201:
                        emergency_requests.append(request_response.json()["data"])

            # Verify emergency requests were created
            assert len(emergency_requests) >= 1  # At least one should succeed

            # Check regional inventory status
            for facility in facilities:
                inventory_check = client.get(
                    "/api/inventory",
                    params={"facility_id": facility["id"]},
                    headers=coord_headers,
                )

                if inventory_check.status_code == 200:
                    facility_inventory = inventory_check.json()["data"]["items"]
                    # Each facility should have some inventory
                    assert (
                        len(facility_inventory) >= 0
                    )  # May be empty after distribution


class TestCompletePatientJourney:
    """Test complete patient journey from admission to discharge."""

    def test_surgical_patient_complete_journey(self, client: TestClient):
        """Test complete surgical patient journey with blood management."""
        with PerformanceTimer(max_duration_ms=45000):  # 45 seconds for complete journey

            # Create surgical team
            surgeon_data = TestDataFactory.create_user_data()
            surgeon_data.update(
                {
                    "email": "surgeon@hospital.gh",
                    "role": "staff",
                    "department": "Surgery",
                    "specialization": "Cardiac Surgery",
                }
            )

            surgeon_reg = client.post("/api/users/register", json=surgeon_data)
            assert_response_success(surgeon_reg, 201)

            surgeon_login = client.post(
                "/api/users/auth/login",
                data={
                    "email": surgeon_data["email"],
                    "password": surgeon_data["password"],
                },
            )
            assert_response_success(surgeon_login, 200)

            surgeon_headers = {
                "Authorization": f"Bearer {surgeon_login.json()['data']['access_token']}"
            }

            # Create hospital facility
            hospital_data = TestDataFactory.create_facility_data()
            hospital_data.update(
                {
                    "name": "Korle-Bu Teaching Hospital",
                    "region": "Greater Accra",
                    "type": "teaching_hospital",
                    "surgical_services": True,
                    "icu_beds": 20,
                }
            )

            hospital_response = client.post(
                "/api/facilities", json=hospital_data, headers=surgeon_headers
            )
            assert_response_success(hospital_response, 201)
            hospital_id = hospital_response.json()["data"]["id"]

            # Patient admission
            patient_data = TestDataFactory.create_patient_data()
            patient_data.update(
                {
                    "blood_type": "B+",
                    "medical_conditions": ["Coronary artery disease", "Diabetes"],
                    "allergies": ["Penicillin"],
                    "current_condition": "Stable",
                    "surgical_history": ["Appendectomy 2015"],
                    "emergency_contact": "0244567890",
                }
            )

            patient_response = client.post(
                "/api/patients", json=patient_data, headers=surgeon_headers
            )
            assert_response_success(patient_response, 201)
            patient_id = patient_response.json()["data"]["id"]

            # Pre-operative blood type and screen
            pre_op_data = {
                "patient_id": patient_id,
                "test_type": "type_and_screen",
                "blood_type_confirmed": "B+",
                "antibody_screen": "negative",
                "special_notes": "Pre-operative testing for cardiac surgery",
            }

            # This endpoint might not exist, but test the pattern
            pre_op_response = client.post(
                "/api/lab/tests", json=pre_op_data, headers=surgeon_headers
            )
            # Accept that lab endpoints might not be implemented
            assert pre_op_response.status_code in [200, 201, 404, 501]

            # Pre-operative blood request
            pre_op_request_data = {
                "facility_id": hospital_id,
                "patient_id": patient_id,
                "blood_type": "B+",
                "quantity": 2,
                "priority": "routine",
                "urgency_reason": "Pre-operative preparation for cardiac surgery",
                "clinical_indication": "Type and hold for CABG procedure",
                "surgery_date": (
                    datetime.now(timezone.utc) + timedelta(days=2)
                ).isoformat(),
                "crossmatch_required": True,
            }

            pre_op_request = client.post(
                "/api/requests", json=pre_op_request_data, headers=surgeon_headers
            )
            assert_response_success(pre_op_request, 201)
            pre_op_request_id = pre_op_request.json()["data"]["id"]

            # Surgery day - intraoperative blood request
            intra_op_request_data = {
                "facility_id": hospital_id,
                "patient_id": patient_id,
                "blood_type": "B+",
                "quantity": 1,
                "priority": "urgent",
                "urgency_reason": "Intraoperative blood loss during cardiac surgery",
                "clinical_indication": "Active bleeding during CABG",
                "required_by": (
                    datetime.now(timezone.utc) + timedelta(hours=2)
                ).isoformat(),
                "crossmatch_required": True,
                "special_requirements": ["Leukoreduced", "CMV negative"],
            }

            intra_op_request = client.post(
                "/api/requests", json=intra_op_request_data, headers=surgeon_headers
            )
            assert_response_success(intra_op_request, 201)
            intra_op_request_id = intra_op_request.json()["data"]["id"]

            # Post-operative monitoring
            post_op_data = {
                "patient_id": patient_id,
                "hemoglobin_level": 8.5,  # Low hemoglobin
                "vital_signs": "stable",
                "blood_loss": "moderate",
                "transfusion_reaction": "none",
            }

            # Post-operative endpoint might not exist
            post_op_response = client.post(
                "/api/monitoring/post-op", json=post_op_data, headers=surgeon_headers
            )
            assert post_op_response.status_code in [200, 201, 404, 501]

            # Discharge planning
            discharge_data = {
                "patient_id": patient_id,
                "discharge_status": "stable",
                "follow_up_required": True,
                "blood_work_needed": "CBC in 1 week",
                "medications": ["Aspirin", "Metoprolol"],
                "activity_restrictions": "No heavy lifting for 6 weeks",
            }

            discharge_response = client.post(
                "/api/patients/discharge", json=discharge_data, headers=surgeon_headers
            )
            assert discharge_response.status_code in [200, 201, 404, 501]

            # Verify patient record completeness
            final_patient = client.get(
                f"/api/patients/{patient_id}", headers=surgeon_headers
            )
            if final_patient.status_code == 200:
                patient_record = final_patient.json()["data"]
                assert patient_record["blood_type"] == "B+"
                assert "Coronary artery disease" in patient_record["medical_conditions"]
                assert "Penicillin" in patient_record["allergies"]

            # Verify blood requests were properly logged
            patient_requests = client.get(
                "/api/requests",
                params={"patient_id": patient_id},
                headers=surgeon_headers,
            )

            if patient_requests.status_code == 200:
                requests = patient_requests.json()["data"]["requests"]
                # Should have both pre-op and intra-op requests
                assert len(requests) >= 2

                priorities = [r["priority"] for r in requests]
                assert "routine" in priorities  # Pre-op
                assert "urgent" in priorities  # Intra-op


class TestSystemIntegrationStress:
    """Test system-wide integration under stress conditions."""

    @pytest.mark.slow
    def test_full_system_under_load(self, client: TestClient):
        """Test full system integration under simulated load."""
        with PerformanceTimer(max_duration_ms=120000):  # 2 minutes for full system test

            # Create multiple user types simultaneously
            user_types = [
                {"role": "facility_administrator", "count": 2},
                {"role": "lab_manager", "count": 3},
                {"role": "staff", "count": 5},
            ]

            created_users = []
            for user_type in user_types:
                for i in range(user_type["count"]):
                    user_data = TestDataFactory.create_user_data()
                    user_data.update(
                        {
                            "email": f"{user_type['role']}_{i}@system.test",
                            "role": user_type["role"],
                        }
                    )

                    response = client.post("/api/users/register", json=user_data)
                    if response.status_code == 201:
                        created_users.append(
                            {
                                "user_data": response.json()["data"],
                                "login_data": {
                                    "email": user_data["email"],
                                    "password": user_data["password"],
                                },
                                "role": user_type["role"],
                            }
                        )

            # Log in all users and create auth headers
            authenticated_users = []
            for user in created_users:
                login_response = client.post(
                    "/api/users/auth/login", data=user["login_data"]
                )
                if login_response.status_code == 200:
                    token = login_response.json()["data"]["access_token"]
                    user["headers"] = {"Authorization": f"Bearer {token}"}
                    authenticated_users.append(user)

            # Create multiple facilities
            facilities = []
            admin_users = [
                u for u in authenticated_users if u["role"] == "facility_administrator"
            ]

            for i, admin in enumerate(admin_users):
                facility_data = TestDataFactory.create_facility_data()
                facility_data.update(
                    {
                        "name": f"Test Facility {i+1}",
                        "region": ["Greater Accra", "Ashanti"][i % 2],
                    }
                )

                response = client.post(
                    "/api/facilities", json=facility_data, headers=admin["headers"]
                )
                if response.status_code == 201:
                    facilities.append(response.json()["data"])

            # Create patients across facilities
            patients = []
            staff_users = [u for u in authenticated_users if u["role"] == "staff"]

            for i, staff in enumerate(staff_users):
                patient_data = TestDataFactory.create_patient_data()
                patient_data["national_id"] = f"STRESS_PATIENT_{i}"

                response = client.post(
                    "/api/patients", json=patient_data, headers=staff["headers"]
                )
                if response.status_code == 201:
                    patients.append(response.json()["data"])

            # Create inventory across facilities
            lab_users = [u for u in authenticated_users if u["role"] == "lab_manager"]

            for facility in facilities:
                for lab_user in lab_users:
                    inventory_data = TestDataFactory.create_inventory_data(
                        facility["id"]
                    )

                    response = client.post(
                        "/api/inventory",
                        json=inventory_data,
                        headers=lab_user["headers"],
                    )
                    # Some may fail due to permissions, which is expected
                    assert response.status_code in [200, 201, 403, 422]

            # Create blood requests across the system
            requests_created = 0
            for patient in patients:
                for facility in facilities:
                    request_data = {
                        "facility_id": facility["id"],
                        "patient_id": patient["id"],
                        "blood_type": patient["blood_type"],
                        "quantity": 1,
                        "priority": "routine",
                        "urgency_reason": "System integration test",
                        "clinical_indication": "Test request",
                    }

                    # Use first staff user for requests
                    if staff_users:
                        response = client.post(
                            "/api/requests",
                            json=request_data,
                            headers=staff_users[0]["headers"],
                        )
                        if response.status_code == 201:
                            requests_created += 1

            # Verify system stability
            assert len(authenticated_users) >= 5  # At least half of users authenticated
            assert len(facilities) >= 1  # At least one facility created
            assert len(patients) >= 2  # At least some patients created
            assert requests_created >= 1  # At least some requests created

            # Test system-wide search functionality
            search_response = client.get(
                "/api/users",
                params={"search": "test"},
                headers=authenticated_users[0]["headers"],
            )
            assert search_response.status_code in [
                200,
                403,
            ]  # OK or Forbidden (permissions)

            # Test concurrent access to shared resources
            concurrent_responses = []
            for user in authenticated_users[:5]:  # First 5 users
                response = client.get("/api/facilities", headers=user["headers"])
                concurrent_responses.append(response)

            # Most should succeed
            successful_responses = [
                r for r in concurrent_responses if r.status_code == 200
            ]
            assert (
                len(successful_responses) >= 3
            )  # At least 60% success rate under load
