# Test Execution Scripts for Hospital Blood Request Management System

Write-Host "Hospital Blood Request Management System - Test Suite" -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Green

# Set test environment variables
$env:ENVIRONMENT = "test"
$env:TESTING = "true"
$env:DATABASE_URL = "sqlite+aiosqlite:///:memory:"
$env:SECRET_KEY = "test-secret-key-for-jwt-tokens"
$env:ALGORITHM = "HS256"
$env:ACCESS_TOKEN_EXPIRE_MINUTES = "30"

function Show-Menu {
    Write-Host "`nTest Execution Options:" -ForegroundColor Cyan
    Write-Host "1. Run All Tests" -ForegroundColor White
    Write-Host "2. Run Unit Tests Only (Fast)" -ForegroundColor White
    Write-Host "3. Run Integration Tests" -ForegroundColor White
    Write-Host "4. Run Security Tests" -ForegroundColor White
    Write-Host "5. Run Performance Tests" -ForegroundColor White
    Write-Host "6. Run Edge Case Tests" -ForegroundColor White
    Write-Host "7. Run End-to-End Tests" -ForegroundColor White
    Write-Host "8. Run Tests with Coverage" -ForegroundColor White
    Write-Host "9. Run Specific Test File" -ForegroundColor White
    Write-Host "10. Generate Coverage Report" -ForegroundColor White
    Write-Host "11. Run Tests in Parallel" -ForegroundColor White
    Write-Host "12. Install Test Dependencies" -ForegroundColor White
    Write-Host "0. Exit" -ForegroundColor Red
    Write-Host ""
}

function Install-TestDependencies {
    Write-Host "Installing test dependencies..." -ForegroundColor Yellow
    
    pip install --upgrade pip
    pip install pytest pytest-asyncio pytest-cov pytest-xdist pytest-mock pytest-timeout
    
    Write-Host "Test dependencies installed successfully!" -ForegroundColor Green
}

function Run-AllTests {
    Write-Host "Running all tests..." -ForegroundColor Yellow
    pytest -v
}

function Run-UnitTests {
    Write-Host "Running unit tests (excluding slow tests)..." -ForegroundColor Yellow
    pytest -m "not slow" -v
}

function Run-IntegrationTests {
    Write-Host "Running integration tests..." -ForegroundColor Yellow
    pytest -m "slow" -v
}

function Run-SecurityTests {
    Write-Host "Running security tests..." -ForegroundColor Yellow
    pytest -k "security" -v
}

function Run-PerformanceTests {
    Write-Host "Running performance benchmarks..." -ForegroundColor Yellow
    pytest -k "performance" -v
}

function Run-EdgeCaseTests {
    Write-Host "Running extreme edge case tests..." -ForegroundColor Yellow
    pytest tests/test_extreme_edge_cases.py -v
}

function Run-EndToEndTests {
    Write-Host "Running end-to-end integration tests..." -ForegroundColor Yellow
    pytest tests/test_end_to_end_integration.py -v
}

function Run-TestsWithCoverage {
    Write-Host "Running tests with coverage analysis..." -ForegroundColor Yellow
    pytest --cov=app --cov-report=term-missing --cov-report=html -v
    
    Write-Host "`nCoverage report generated!" -ForegroundColor Green
    Write-Host "View HTML report: htmlcov/index.html" -ForegroundColor Cyan
}

function Run-SpecificTestFile {
    Write-Host "`nAvailable test files:" -ForegroundColor Cyan
    Get-ChildItem "tests\test_*.py" | ForEach-Object { 
        Write-Host "  - $($_.Name)" -ForegroundColor White
    }
    
    $testFile = Read-Host "`nEnter test file name (without .py extension)"
    
    if ($testFile) {
        $fullPath = "tests\test_$testFile.py"
        if (Test-Path $fullPath) {
            Write-Host "Running tests from $fullPath..." -ForegroundColor Yellow
            pytest $fullPath -v
        } else {
            Write-Host "Test file not found: $fullPath" -ForegroundColor Red
        }
    }
}

function Generate-CoverageReport {
    Write-Host "Generating comprehensive coverage report..." -ForegroundColor Yellow
    
    pytest --cov=app --cov-report=html --cov-report=xml --cov-report=term-missing
    
    Write-Host "`nCoverage reports generated:" -ForegroundColor Green
    Write-Host "  - HTML: htmlcov/index.html" -ForegroundColor Cyan
    Write-Host "  - XML: coverage.xml" -ForegroundColor Cyan
    Write-Host "  - Terminal output above" -ForegroundColor Cyan
}

function Run-ParallelTests {
    Write-Host "Installing pytest-xdist for parallel execution..." -ForegroundColor Yellow
    pip install pytest-xdist
    
    Write-Host "Running tests in parallel..." -ForegroundColor Yellow
    pytest -n auto -v
}

# Main execution loop
do {
    Show-Menu
    $choice = Read-Host "Select an option (0-12)"
    
    switch ($choice) {
        "1" { Run-AllTests }
        "2" { Run-UnitTests }
        "3" { Run-IntegrationTests }
        "4" { Run-SecurityTests }
        "5" { Run-PerformanceTests }
        "6" { Run-EdgeCaseTests }
        "7" { Run-EndToEndTests }
        "8" { Run-TestsWithCoverage }
        "9" { Run-SpecificTestFile }
        "10" { Generate-CoverageReport }
        "11" { Run-ParallelTests }
        "12" { Install-TestDependencies }
        "0" { 
            Write-Host "Exiting test runner..." -ForegroundColor Yellow
            break
        }
        default { 
            Write-Host "Invalid option. Please select 0-12." -ForegroundColor Red
        }
    }
    
    if ($choice -ne "0") {
        Write-Host "`nPress any key to continue..." -ForegroundColor Gray
        $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    }
} while ($choice -ne "0")

Write-Host "`nTest execution completed. Thank you!" -ForegroundColor Green
