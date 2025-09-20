# Hospital Blood Request Management System - Test Suite

## Overview

This comprehensive test suite covers all aspects of the hospital blood request management API, including unit tests, integration tests, stress tests, and end-to-end workflows. The tests are designed to validate extreme cases, edge conditions, and real-world hospital scenarios.

## Test Structure

### Test Files

1. **`tests/conftest.py`** - Core test infrastructure

   - Test configuration and fixtures
   - Data factories for realistic hospital data
   - Performance monitoring utilities
   - Database setup and cleanup

2. **`tests/test_auth_comprehensive.py`** - Authentication & Security

   - User registration and login flows
   - JWT token validation and security
   - Rate limiting and brute force protection
   - XSS and SQL injection prevention

3. **`tests/test_blood_request_comprehensive.py`** - Blood Request Workflows

   - Blood request creation and validation
   - Priority handling and emergency protocols
   - Medical validation and compatibility checks
   - Status management and approval workflows

4. **`tests/test_inventory_comprehensive.py`** - Blood Inventory Management

   - Inventory CRUD operations
   - Expiry date tracking and alerts
   - Stock level monitoring
   - Blood type compatibility validation

5. **`tests/test_facility_comprehensive.py`** - Healthcare Facilities

   - Facility management operations
   - Multi-facility scenarios
   - Ghana region validation
   - User-facility relationships

6. **`tests/test_patient_comprehensive.py`** - Patient Data Management

   - Patient registration and validation
   - Medical record handling
   - Privacy compliance (HIPAA-like)
   - Data masking and consent tracking

7. **`tests/test_extreme_edge_cases.py`** - Stress & Edge Cases

   - System limits and boundary conditions
   - Concurrent operations and race conditions
   - Failure scenario handling
   - Security under stress

8. **`tests/test_end_to_end_integration.py`** - Complete Workflows
   - Emergency blood request workflows
   - Multi-facility transfer scenarios
   - Complete patient journeys
   - System-wide integration testing

## Running Tests

### Prerequisites

1. **Install Dependencies**

   ```bash
   pip install -r requirements.txt
   pip install pytest pytest-asyncio pytest-cov pytest-mock
   ```

2. **Environment Setup**

   ```bash
   # Set test environment
   $env:ENVIRONMENT = "test"

   # Configure test database (SQLite in-memory is used by default)
   $env:DATABASE_URL = "sqlite:///:memory:"
   ```

### Basic Test Execution

```bash
# Run all tests
pytest

# Run tests with verbose output
pytest -v

# Run specific test file
pytest tests/test_auth_comprehensive.py

# Run specific test class
pytest tests/test_auth_comprehensive.py::TestUserAuthentication

# Run specific test method
pytest tests/test_auth_comprehensive.py::TestUserAuthentication::test_user_registration_success
```

### Test Categories

```bash
# Run only fast tests (excludes slow integration tests)
pytest -m "not slow"

# Run only slow/integration tests
pytest -m "slow"

# Run security tests
pytest -k "security"

# Run performance tests
pytest -k "performance"

# Run edge case tests
pytest tests/test_extreme_edge_cases.py

# Run end-to-end tests
pytest tests/test_end_to_end_integration.py
```

### Coverage Reports

```bash
# Run tests with coverage
pytest --cov=app

# Generate HTML coverage report
pytest --cov=app --cov-report=html

# Generate XML coverage report (for CI/CD)
pytest --cov=app --cov-report=xml

# View coverage in terminal
pytest --cov=app --cov-report=term-missing
```

### Parallel Test Execution

```bash
# Install pytest-xdist for parallel execution
pip install pytest-xdist

# Run tests in parallel (4 workers)
pytest -n 4

# Run tests in parallel with auto worker detection
pytest -n auto
```

## Test Configuration

### Environment Variables

```bash
# Test Environment
$env:ENVIRONMENT = "test"
$env:TESTING = "true"

# Database Configuration
$env:DATABASE_URL = "sqlite:///:memory:"
$env:TEST_DATABASE_URL = "sqlite:///test.db"

# Security Configuration
$env:SECRET_KEY = "test-secret-key-for-jwt-tokens"
$env:ALGORITHM = "HS256"
$env:ACCESS_TOKEN_EXPIRE_MINUTES = "30"

# Email Configuration (for testing)
$env:SMTP_ENABLED = "false"
$env:EMAIL_BACKEND = "console"

# Performance Testing
$env:PERFORMANCE_TESTING = "true"
$env:MAX_TEST_DURATION_MS = "30000"
```

### pytest.ini Configuration

Create a `pytest.ini` file in the project root:

```ini
[tool:pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts =
    -v
    --tb=short
    --strict-markers
    --disable-warnings
    --color=yes
markers =
    slow: marks tests as slow (deselect with '-m "not slow"')
    integration: marks tests as integration tests
    security: marks tests as security-related
    performance: marks tests as performance benchmarks
    edge_case: marks tests as edge case scenarios
    unit: marks tests as unit tests
filterwarnings =
    ignore::DeprecationWarning
    ignore::PendingDeprecationWarning
```

## Performance Benchmarks

### Expected Performance Metrics

| Operation              | Target Time | Max Time |
| ---------------------- | ----------- | -------- |
| User Registration      | < 500ms     | < 1000ms |
| User Login             | < 300ms     | < 600ms  |
| Blood Request Creation | < 800ms     | < 1500ms |
| Inventory Search       | < 400ms     | < 800ms  |
| Patient Registration   | < 600ms     | < 1200ms |
| Emergency Workflow     | < 10s       | < 30s    |
| Mass Casualty Scenario | < 30s       | < 60s    |

### Performance Testing

```bash
# Run performance benchmarks
pytest tests/test_extreme_edge_cases.py::TestPerformanceBenchmarks -v

# Run with performance profiling
pytest --profile

# Run stress tests
pytest tests/test_extreme_edge_cases.py::TestConcurrencyStress -v
```

## Security Testing

### Security Test Categories

1. **Authentication Security**

   - JWT token validation
   - Password strength requirements
   - Session management
   - Rate limiting

2. **Input Validation**

   - SQL injection prevention
   - XSS protection
   - Command injection prevention
   - Path traversal protection

3. **Data Privacy**
   - Patient data masking
   - Access control validation
   - Audit trail verification
   - HIPAA-like compliance

### Running Security Tests

```bash
# Run all security tests
pytest -k "security" -v

# Run authentication security tests
pytest tests/test_auth_comprehensive.py::TestAuthenticationSecurity -v

# Run input validation tests
pytest tests/test_extreme_edge_cases.py::TestSecurityStress -v

# Run privacy compliance tests
pytest tests/test_patient_comprehensive.py::TestPatientPrivacy -v
```

## Integration Testing

### Hospital Workflow Tests

1. **Emergency Blood Request Workflow**

   - Staff registration and authentication
   - Emergency facility setup
   - Critical patient registration
   - Urgent blood request creation
   - Lab manager approval
   - Fulfillment processing

2. **Multi-Facility Transfer Workflow**

   - Network administrator setup
   - Donor and recipient facility creation
   - Inventory management
   - Transfer request processing
   - Regional distribution

3. **Complete Patient Journey**
   - Patient admission
   - Pre-operative preparation
   - Surgical blood management
   - Post-operative monitoring
   - Discharge planning

### Running Integration Tests

```bash
# Run all integration tests
pytest tests/test_end_to_end_integration.py -v

# Run emergency workflow tests
pytest tests/test_end_to_end_integration.py::TestEmergencyBloodRequestWorkflow -v

# Run multi-facility tests
pytest tests/test_end_to_end_integration.py::TestMultiFacilityTransferWorkflow -v

# Run complete patient journey
pytest tests/test_end_to_end_integration.py::TestCompletePatientJourney -v
```

## Continuous Integration

### GitHub Actions Example

```yaml
name: Test Suite

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: [3.8, 3.9, 3.10, 3.11]

    steps:
      - uses: actions/checkout@v3

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v3
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install pytest pytest-asyncio pytest-cov pytest-xdist

      - name: Run unit tests
        run: pytest tests/ -m "not slow" --cov=app --cov-report=xml

      - name: Run integration tests
        run: pytest tests/ -m "slow" --maxfail=5

      - name: Upload coverage to Codecov
        uses: codecov/codecov-action@v3
        with:
          file: ./coverage.xml
```

### Docker Testing Environment

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt
RUN pip install pytest pytest-asyncio pytest-cov pytest-xdist

COPY . .

ENV ENVIRONMENT=test
ENV DATABASE_URL=sqlite:///:memory:

CMD ["pytest", "--cov=app", "--cov-report=term-missing"]
```

## Test Data Management

### Data Factories

The test suite uses comprehensive data factories to generate realistic hospital data:

- **UserDataFactory**: Creates realistic user profiles with proper roles
- **FacilityDataFactory**: Generates hospital and blood bank data with Ghana regions
- **PatientDataFactory**: Creates patient records with medical history
- **InventoryDataFactory**: Generates blood inventory with proper expiry dates
- **BloodRequestDataFactory**: Creates realistic blood request scenarios

### Test Database

- Uses SQLite in-memory database for fast test execution
- Automatic database creation and cleanup between tests
- Transaction isolation to prevent test interference
- Realistic data seeding for integration tests

## Troubleshooting

### Common Issues

1. **Import Errors**

   ```bash
   # Ensure proper Python path
   $env:PYTHONPATH = "."
   pytest
   ```

2. **Database Connection Issues**

   ```bash
   # Reset test database
   rm -f test.db
   pytest
   ```

3. **Permission Errors**

   ```bash
   # Run with proper test configuration
   $env:ENVIRONMENT = "test"
   pytest
   ```

4. **Timeout Issues**
   ```bash
   # Increase timeout for slow tests
   pytest --timeout=300
   ```

### Debug Mode

```bash
# Run tests with debug output
pytest -s -vv

# Run specific test with debugging
pytest tests/test_auth_comprehensive.py::test_user_registration_success -s -vv

# Use pytest debugger
pytest --pdb

# Use pytest trace
pytest --trace
```

## Test Metrics

### Coverage Goals

- **Overall Coverage**: > 90%
- **Critical Paths**: > 95%
- **Security Functions**: 100%
- **API Endpoints**: > 95%

### Performance Goals

- **Test Suite Execution**: < 5 minutes (all tests)
- **Unit Tests**: < 2 minutes
- **Integration Tests**: < 10 minutes
- **Memory Usage**: < 512MB during testing

## Contributing to Tests

### Adding New Tests

1. **Follow naming conventions**: `test_[feature]_[scenario].py`
2. **Use appropriate fixtures**: Leverage existing fixtures from `conftest.py`
3. **Include edge cases**: Test boundary conditions and error scenarios
4. **Add performance markers**: Mark slow tests appropriately
5. **Document test purpose**: Include docstrings explaining test scenarios

### Test Review Checklist

- [ ] Tests cover both positive and negative scenarios
- [ ] Edge cases and boundary conditions are tested
- [ ] Security implications are considered
- [ ] Performance impact is measured
- [ ] Tests are deterministic and isolated
- [ ] Documentation is updated
- [ ] CI/CD integration works correctly

This comprehensive test suite ensures the reliability, security, and performance of the hospital blood request management system under all conditions, from normal operations to extreme emergency scenarios.
