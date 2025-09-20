"""
Extreme edge case and stress tests for hospital blood request system.
Tests boundary conditions, concurrent operations, failure scenarios, and system limits.
"""

import pytest
import asyncio
from fastapi.testclient import TestClient
import threading
import time

from tests.conftest import (
    TestDataFactory,
    PerformanceTimer,
)


class TestSystemLimits:
    """Test system limits and boundary conditions."""

    def test_maximum_request_payload_size(self, client: TestClient, auth_headers: dict):
        """Test handling of extremely large request payloads."""
        # Create payload approaching typical JSON size limits
        large_payload = {
            "description": "A" * 50000,  # 50KB description
            "notes": "B" * 100000,  # 100KB notes
            "metadata": {
                f"field_{i}": "X" * 1000 for i in range(100)
            },  # Additional bulk
        }

        response = client.post(
            "/api/test/large-payload", json=large_payload, headers=auth_headers
        )

        # Should either handle gracefully or reject with appropriate status
        assert response.status_code in [
            200,
            400,
            413,
            422,
        ]  # OK, Bad Request, Payload Too Large, or Validation Error

        if response.status_code == 413:
            error_data = response.json()
            assert (
                "payload" in error_data.get("message", "").lower()
                or "size" in error_data.get("message", "").lower()
            )

    def test_maximum_pagination_limits(self, client: TestClient, auth_headers: dict):
        """Test pagination with extreme limit values."""
        extreme_pagination_tests = [
            {"limit": 10000, "page": 1},  # Very large limit
            {"limit": 1, "page": 999999},  # Very large page number
            {"limit": 0, "page": 1},  # Zero limit
            {"limit": -1, "page": 1},  # Negative limit
            {"limit": "invalid", "page": 1},  # Non-numeric limit
        ]

        for params in extreme_pagination_tests:
            response = client.get("/api/users", params=params, headers=auth_headers)

            # Should handle invalid pagination gracefully
            if params["limit"] in [0, -1, "invalid"]:
                assert response.status_code in [400, 422]
            else:
                # Should either work or impose reasonable limits
                assert response.status_code in [200, 400]

                if response.status_code == 200:
                    data = response.json()["data"]
                    # Should impose reasonable limits (e.g., max 1000 per page)
                    assert len(data.get("users", [])) <= 1000

    def test_deeply_nested_json_handling(self, client: TestClient, auth_headers: dict):
        """Test handling of deeply nested JSON structures."""
        # Create deeply nested structure
        nested_data = {"level": 0}
        current = nested_data
        for i in range(100):  # 100 levels deep
            current["nested"] = {"level": i + 1, "data": "x" * 100}
            current = current["nested"]

        test_payload = {"name": "Deep Nesting Test", "metadata": nested_data}

        response = client.post(
            "/api/test/nested-data", json=test_payload, headers=auth_headers
        )

        # Should either handle or reject gracefully
        assert response.status_code in [200, 400, 413, 422]

    def test_unicode_edge_cases(self, client: TestClient, auth_headers: dict):
        """Test handling of edge case Unicode characters."""
        unicode_edge_cases = [
            "🩸💉🏥",  # Medical emojis
            "Test\x00\x01\x02",  # Control characters
            "Test\ufffd",  # Unicode replacement character
            "Test\u200b\u200c\u200d",  # Zero-width characters
            "Test\U0001f4a9",  # Emoji outside basic plane
            "नमस्ते",  # Non-Latin script
            "🇬🇭🏥",  # Flag + medical emoji
            "A" * 4 + "\U0001f600" * 1000,  # Many emojis
        ]

        for unicode_text in unicode_edge_cases:
            test_data = TestDataFactory.create_user_data()
            test_data["first_name"] = unicode_text

            response = client.post(
                "/api/users/register", json=test_data, headers=auth_headers
            )

            # Should either succeed with proper encoding or fail gracefully
            if response.status_code == 201:
                data = response.json()["data"]
                # Should preserve Unicode or properly sanitize
                assert isinstance(data["first_name"], str)
            else:
                assert response.status_code in [400, 422]

    def test_timestamp_edge_cases(self, client: TestClient, auth_headers: dict):
        """Test handling of edge case timestamps."""
        timestamp_edge_cases = [
            "1970-01-01T00:00:00Z",  # Unix epoch
            "2038-01-19T03:14:07Z",  # 32-bit timestamp limit
            "9999-12-31T23:59:59Z",  # Far future
            "0001-01-01T00:00:00Z",  # Very old date
            "2024-02-29T12:00:00Z",  # Leap year
            "2024-13-01T25:61:61Z",  # Invalid date components
            "invalid-timestamp",  # Completely invalid
            "",  # Empty string
        ]

        for timestamp in timestamp_edge_cases:
            test_data = {
                "requested_date": timestamp,
                "blood_type": "A+",
                "quantity": 1,
                "priority": "urgent",
            }

            response = client.post(
                "/api/test/timestamp", json=test_data, headers=auth_headers
            )

            # Should validate timestamps properly
            if "invalid" in timestamp or timestamp == "" or "25:" in timestamp:
                assert response.status_code in [400, 422]
            else:
                # Valid timestamps should be accepted or reasonably rejected
                assert response.status_code in [200, 201, 400]


class TestConcurrencyStress:
    """Test concurrent operations and race conditions."""

    @pytest.mark.asyncio
    async def test_concurrent_user_registrations(self, client: TestClient):
        """Test massive concurrent user registrations."""

        async def register_user(user_id: int):
            user_data = TestDataFactory.create_user_data()
            user_data["email"] = f"stress_test_{user_id}@hospital.com"
            return client.post("/api/users/register", json=user_data)

        # Create 50 concurrent registration tasks
        tasks = [register_user(i) for i in range(50)]

        with PerformanceTimer(max_duration_ms=10000):  # 10 seconds max
            responses = await asyncio.gather(*tasks, return_exceptions=True)

        successful_registrations = 0
        failed_registrations = 0

        for response in responses:
            if hasattr(response, "status_code"):
                if response.status_code == 201:
                    successful_registrations += 1
                else:
                    failed_registrations += 1

        # Should handle concurrent load gracefully
        assert successful_registrations > 0  # At least some should succeed
        # Some failures are acceptable under extreme load
        assert (
            successful_registrations / len(tasks)
        ) >= 0.7  # At least 70% success rate

    def test_concurrent_inventory_updates(
        self, client: TestClient, auth_headers: dict, test_facility
    ):
        """Test concurrent updates to the same inventory item."""
        # Create inventory item
        inventory_data = TestDataFactory.create_inventory_data(str(test_facility.id))
        inventory_data["quantity"] = 100  # Start with high quantity

        create_response = client.post(
            "/api/inventory", json=inventory_data, headers=auth_headers
        )

        if create_response.status_code == 201:
            item_id = create_response.json()["data"]["id"]

            def update_inventory(reduction: int):
                """Function to run in thread for concurrent updates."""
                update_data = {
                    "quantity_change": -reduction,  # Reduce quantity
                    "notes": f"Concurrent test reduction: {reduction}",
                }
                return client.put(
                    f"/api/inventory/{item_id}/quantity",
                    json=update_data,
                    headers=auth_headers,
                )

            # Create multiple threads for concurrent updates
            threads = []
            responses = []

            for i in range(10):
                thread = threading.Thread(
                    target=lambda r=i + 1: responses.append(update_inventory(r))
                )
                threads.append(thread)
                thread.start()

            # Wait for all threads to complete
            for thread in threads:
                thread.join()

            # Check that race conditions are handled properly
            success_count = sum(
                1
                for r in responses
                if hasattr(r, "status_code") and r.status_code == 200
            )

            # Should handle concurrent updates without data corruption
            assert success_count > 0

            # Verify final state is consistent
            final_response = client.get(
                f"/api/inventory/{item_id}", headers=auth_headers
            )
            if final_response.status_code == 200:
                final_data = final_response.json()["data"]
                # Quantity should never go negative due to race conditions
                assert final_data["quantity"] >= 0

    def test_high_frequency_login_attempts(self, client: TestClient, test_user):
        """Test high frequency login attempts (rate limiting)."""
        login_data = {"email": test_user.email, "password": "SecurePass123!"}

        responses = []
        rate_limited = False

        # Attempt 100 rapid logins
        for i in range(100):
            response = client.post("/api/users/auth/login", data=login_data)
            responses.append(response)

            if response.status_code == 429:  # Rate limited
                rate_limited = True
                break

            # Small delay to avoid overwhelming the system
            time.sleep(0.01)

        # Should implement rate limiting
        success_responses = [r for r in responses if r.status_code == 200]

        # Either rate limiting kicks in, or all requests succeed (both acceptable)
        assert rate_limited or len(success_responses) == len(responses)

        if rate_limited:
            # Rate limiting should kick in before 100 requests
            assert len(responses) < 100

    @pytest.mark.asyncio
    async def test_concurrent_blood_requests(
        self, client: TestClient, auth_headers: dict, test_facility, test_patient
    ):
        """Test concurrent blood requests for the same patient."""

        async def create_blood_request(request_id: int):
            request_data = {
                "facility_id": str(test_facility.id),
                "patient_id": str(test_patient.id),
                "blood_type": "A+",
                "quantity": 1,
                "priority": "urgent",
                "urgency_reason": f"Concurrent test request {request_id}",
            }
            return client.post("/api/requests", json=request_data, headers=auth_headers)

        # Create 20 concurrent requests
        tasks = [create_blood_request(i) for i in range(20)]

        responses = await asyncio.gather(*tasks, return_exceptions=True)

        successful_requests = 0
        for response in responses:
            if hasattr(response, "status_code") and response.status_code == 201:
                successful_requests += 1

        # Should handle concurrent requests properly
        # May limit concurrent requests per patient or accept all
        assert successful_requests >= 1  # At least one should succeed


class TestFailureScenarios:
    """Test system behavior under failure conditions."""

    def test_database_connection_simulation(
        self, client: TestClient, auth_headers: dict
    ):
        """Test behavior when database connections are stressed."""
        # Create many requests that would require database connections
        responses = []

        for i in range(50):
            response = client.get("/api/users/me", headers=auth_headers)
            responses.append(response)

        # Should maintain reasonable performance under load
        success_count = sum(1 for r in responses if r.status_code == 200)
        error_count = sum(1 for r in responses if r.status_code >= 500)

        # Most requests should succeed, minimal server errors
        assert success_count >= 40  # At least 80% success rate
        assert error_count <= 5  # At most 10% server errors

    def test_malformed_request_handling(self, client: TestClient, auth_headers: dict):
        """Test handling of various malformed requests."""
        malformed_requests = [
            # Invalid JSON
            '{"invalid": json,}',
            # Null bytes
            '{"name": "test\x00\x01"}',
            # Extremely long values
            '{"name": "' + "A" * 100000 + '"}',
            # Binary data in JSON
            '{"data": "\\xFF\\xFE\\xFD"}',
            # Circular references (impossible in JSON but test parser)
            '{"a": {"b": {"c": {"ref_to_a": "..."}}}}',
        ]

        for malformed_json in malformed_requests:
            # Send malformed data directly
            response = client.post(
                "/api/test/malformed",
                data=malformed_json,
                headers={**auth_headers, "Content-Type": "application/json"},
            )

            # Should handle malformed data gracefully
            assert response.status_code in [400, 422]  # Bad Request or Validation Error

            # Should not cause server errors
            assert response.status_code < 500

    def test_resource_exhaustion_simulation(
        self, client: TestClient, auth_headers: dict
    ):
        """Test behavior under simulated resource exhaustion."""
        # Create requests that would consume memory/CPU
        large_search_requests = []

        for i in range(20):
            # Search with broad criteria that might return large results
            params = {
                "search": "",  # Empty search to get all results
                "limit": 1000,  # Large limit
                "include_inactive": True,
                "detailed": True,
            }

            response = client.get("/api/users", params=params, headers=auth_headers)
            large_search_requests.append(response)

        # System should remain stable under load
        server_errors = sum(1 for r in large_search_requests if r.status_code >= 500)
        timeouts = sum(1 for r in large_search_requests if r.status_code == 408)

        # Should handle resource pressure gracefully
        assert server_errors <= 2  # Minimal server errors
        assert timeouts <= 5  # Some timeouts acceptable under extreme load

    def test_invalid_authentication_edge_cases(self, client: TestClient):
        """Test edge cases in authentication handling."""
        invalid_auth_cases = [
            {"Authorization": "Bearer " + "a" * 10000},  # Extremely long token
            {"Authorization": "Bearer \x00\x01\x02"},  # Binary in token
            {"Authorization": "Invalid format"},  # Wrong format
            {"Authorization": "Bearer"},  # Missing token
            {"Authorization": ""},  # Empty header
            {"Authorization": None},  # Null header
            # Multiple authorization headers would be handled by HTTP layer
        ]

        for auth_header in invalid_auth_cases:
            headers = auth_header if auth_header["Authorization"] is not None else {}

            response = client.get("/api/users/me", headers=headers)

            # Should reject invalid authentication gracefully
            assert response.status_code == 401  # Unauthorized

            # Should not cause server errors
            error_data = response.json()
            assert "error" in error_data or "message" in error_data


class TestDataIntegrityStress:
    """Test data integrity under stress conditions."""

    def test_blood_type_consistency_under_load(
        self, client: TestClient, auth_headers: dict, test_facility
    ):
        """Test blood type consistency during concurrent operations."""
        # Create multiple inventory items and requests with same blood type
        blood_type = "O-"  # Universal donor

        # Create inventory
        inventory_responses = []
        for i in range(10):
            inventory_data = TestDataFactory.create_inventory_data(
                str(test_facility.id)
            )
            inventory_data["blood_type"] = blood_type
            inventory_data["lot_number"] = f"STRESS_LOT_{i}"

            response = client.post(
                "/api/inventory", json=inventory_data, headers=auth_headers
            )
            inventory_responses.append(response)

        # Create patients with same blood type
        patient_responses = []
        for i in range(5):
            patient_data = TestDataFactory.create_patient_data()
            patient_data["blood_type"] = blood_type
            patient_data["national_id"] = f"STRESS_PATIENT_{i}"

            response = client.post(
                "/api/patients", json=patient_data, headers=auth_headers
            )
            patient_responses.append(response)

        # Verify blood type consistency
        successful_inventory = [r for r in inventory_responses if r.status_code == 201]
        successful_patients = [r for r in patient_responses if r.status_code == 201]

        for response in successful_inventory:
            data = response.json()["data"]
            assert data["blood_type"] == blood_type

        for response in successful_patients:
            data = response.json()["data"]
            assert data["blood_type"] == blood_type

    def test_quantity_tracking_accuracy(
        self, client: TestClient, auth_headers: dict, test_facility
    ):
        """Test accuracy of quantity tracking under concurrent operations."""
        # Create inventory with known quantity
        inventory_data = TestDataFactory.create_inventory_data(str(test_facility.id))
        inventory_data["quantity"] = 100

        create_response = client.post(
            "/api/inventory", json=inventory_data, headers=auth_headers
        )

        if create_response.status_code == 201:
            item_id = create_response.json()["data"]["id"]

            # Perform multiple quantity operations
            operations = [
                {"operation": "reduce", "amount": 5},
                {"operation": "reduce", "amount": 10},
                {"operation": "reduce", "amount": 3},
                {"operation": "reduce", "amount": 7},
                {"operation": "reduce", "amount": 15},
            ]

            total_reduction = sum(op["amount"] for op in operations)
            expected_final_quantity = 100 - total_reduction

            # Apply operations sequentially to avoid race conditions
            for op in operations:
                update_data = {
                    "quantity_change": -op["amount"],
                    "notes": f"Test {op['operation']} {op['amount']}",
                }

                response = client.put(
                    f"/api/inventory/{item_id}/quantity",
                    json=update_data,
                    headers=auth_headers,
                )
                # Allow some operations to fail due to insufficient quantity
                assert response.status_code in [200, 400]

            # Check final quantity
            final_response = client.get(
                f"/api/inventory/{item_id}", headers=auth_headers
            )
            if final_response.status_code == 200:
                final_data = final_response.json()["data"]
                # Quantity should be accurate and non-negative
                assert final_data["quantity"] >= 0
                assert final_data["quantity"] <= 100  # Should never exceed initial

    def test_referential_integrity_stress(
        self,
        client: TestClient,
        auth_headers: dict,
        test_facility,
        test_patient,
        test_user,
    ):
        """Test referential integrity under stress conditions."""
        # Create multiple blood requests referencing the same entities
        request_responses = []

        for i in range(20):
            request_data = {
                "facility_id": str(test_facility.id),
                "patient_id": str(test_patient.id),
                "requester_id": str(test_user.id),
                "blood_type": "A+",
                "quantity": 1,
                "priority": "urgent",
                "urgency_reason": f"Stress test request {i}",
            }

            response = client.post(
                "/api/requests", json=request_data, headers=auth_headers
            )
            request_responses.append(response)

        # All successful requests should maintain referential integrity
        successful_requests = [r for r in request_responses if r.status_code == 201]

        for response in successful_requests:
            data = response.json()["data"]
            assert data["facility_id"] == str(test_facility.id)
            assert data["patient_id"] == str(test_patient.id)
            # Verify that referenced entities still exist

            facility_check = client.get(
                f"/api/facilities/{data['facility_id']}", headers=auth_headers
            )
            assert facility_check.status_code == 200

            patient_check = client.get(
                f"/api/patients/{data['patient_id']}", headers=auth_headers
            )
            assert patient_check.status_code in [200, 403]  # OK or Forbidden (privacy)


class TestSecurityStress:
    """Test security under stress and edge conditions."""

    def test_brute_force_login_protection(self, client: TestClient, test_user):
        """Test protection against brute force login attempts."""
        # Attempt many failed logins
        failed_attempts = 0
        locked_out = False

        for attempt in range(50):
            login_data = {
                "email": test_user.email,
                "password": f"wrong_password_{attempt}",
            }

            response = client.post("/api/users/auth/login", data=login_data)

            if response.status_code == 429:  # Rate limited/locked
                locked_out = True
                break
            elif response.status_code == 401:
                failed_attempts += 1

            # Small delay between attempts
            time.sleep(0.1)

        # Should implement some form of protection
        assert (
            locked_out or failed_attempts >= 10
        )  # Either locked out or many failures tracked

    def test_session_exhaustion_protection(self, client: TestClient, test_user):
        """Test protection against session exhaustion attacks."""
        login_data = {"email": test_user.email, "password": "SecurePass123!"}

        # Create many sessions
        sessions = []
        for i in range(100):
            response = client.post("/api/users/auth/login", data=login_data)

            if response.status_code == 200:
                token = response.json()["data"]["access_token"]
                sessions.append(token)
            elif response.status_code == 429:
                # Rate limited - good protection
                break

            # Brief delay
            time.sleep(0.05)

        # Should either limit sessions or handle gracefully
        if len(sessions) > 50:
            # If many sessions created, verify they work
            valid_sessions = 0
            for token in sessions[:10]:  # Test first 10
                headers = {"Authorization": f"Bearer {token}"}
                response = client.get("/api/users/me", headers=headers)
                if response.status_code == 200:
                    valid_sessions += 1

            # Most recent sessions should work
            assert valid_sessions >= 5

    def test_input_validation_under_stress(
        self, client: TestClient, auth_headers: dict
    ):
        """Test input validation under various attack patterns."""
        attack_patterns = [
            # SQL injection variants
            "'; DROP TABLE users; --",
            "admin' OR '1'='1",
            "1'; UPDATE users SET password='hacked'; --",
            # XSS variants
            "<script>alert('xss')</script>",
            "javascript:alert('xss')",
            "<img src=x onerror=alert('xss')>",
            # Command injection
            "; rm -rf /",
            "| whoami",
            "&& cat /etc/passwd",
            # Path traversal
            "../../etc/passwd",
            "..\\..\\windows\\system32",
            # Buffer overflow simulation
            "A" * 10000,
            "\x00" * 1000,
        ]

        for attack_pattern in attack_patterns:
            # Test in user registration
            user_data = TestDataFactory.create_user_data()
            user_data["first_name"] = attack_pattern

            response = client.post(
                "/api/users/register", json=user_data, headers=auth_headers
            )

            # Should reject or sanitize malicious input
            if response.status_code == 201:
                data = response.json()["data"]
                # Should be sanitized
                assert "<script>" not in data["first_name"]
                assert "DROP TABLE" not in data["first_name"]
                assert "rm -rf" not in data["first_name"]
            else:
                # Rejection is also acceptable
                assert response.status_code in [400, 422]

            # Should never cause server errors
            assert response.status_code < 500


@pytest.mark.slow
class TestPerformanceBenchmarks:
    """Performance benchmarks for system operations."""

    def test_user_registration_performance(self, client: TestClient):
        """Benchmark user registration performance."""
        registration_times = []

        for i in range(20):
            user_data = TestDataFactory.create_user_data()
            user_data["email"] = f"perf_test_{i}@hospital.com"

            with PerformanceTimer() as timer:
                response = client.post("/api/users/register", json=user_data)

            if response.status_code == 201:
                registration_times.append(timer.duration_ms)

        if registration_times:
            avg_time = sum(registration_times) / len(registration_times)
            max_time = max(registration_times)

            # Performance expectations
            assert avg_time < 1000  # Average under 1 second
            assert max_time < 2000  # Maximum under 2 seconds

    def test_search_performance_under_load(
        self, client: TestClient, auth_headers: dict
    ):
        """Test search performance with various query patterns."""
        search_queries = [
            {"search": "John"},
            {"search": "A+", "type": "blood_type"},
            {"search": "hospital"},
            {"search": "2024"},
            {"search": ""},  # Empty search
        ]

        search_times = []

        for query in search_queries:
            with PerformanceTimer() as timer:
                response = client.get("/api/users", params=query, headers=auth_headers)

            if response.status_code == 200:
                search_times.append(timer.duration_ms)

        if search_times:
            avg_search_time = sum(search_times) / len(search_times)
            max_search_time = max(search_times)

            # Search performance expectations
            assert avg_search_time < 2000  # Average under 2 seconds
            assert max_search_time < 5000  # Maximum under 5 seconds
