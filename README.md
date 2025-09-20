# 🩸 DonorCom - Blood Bank Management System

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115.12-009688?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776ab?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17-336791?style=flat&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.x-FCA121?style=flat&logo=sqlalchemy&logoColor=white)](https://www.sqlalchemy.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ed?style=flat&logo=docker&logoColor=white)](https://docs.docker.com/compose/)

> A comprehensive blood distribution and management system designed for healthcare facilities, blood banks, and medical institutions.

## 🌟 Features

### 🏥 **Multi-Facility Management**

- **Healthcare Facility Management**: Complete CRUD operations for hospitals, clinics, and medical centers
- **Blood Bank Operations**: Dedicated blood bank management with facility linking
- **Role-Based Access Control (RBAC)**: Fine-grained permissions for different user roles
- **Administrative Dashboard**: SQLAdmin-powered admin interface for system management

### 🩸 **Blood Inventory System**

- **Real-time Inventory Tracking**: Track blood units by type, product, quantity, and expiration
- **Blood Compatibility System**: Automated blood type compatibility checking
- **Expiry Management**: Automated alerts for expiring blood products
- **Batch Operations**: Bulk create, update, and delete operations for efficiency
- **Advanced Search & Filtering**: Multi-parameter search with pagination

### 📊 **Analytics & Reporting**

- **Inventory Statistics**: Comprehensive dashboards with blood type distribution
- **Usage Analytics**: Track blood distribution patterns and facility performance
- **Export Capabilities**: CSV export functionality for reporting
- **Real-time Monitoring**: Live inventory levels and facility status

### 🔐 **Security & Authentication**

- **JWT-based Authentication**: Secure token-based authentication system
- **Multi-factor Security**: Account lockout, failed attempt tracking
- **Session Management**: Advanced session tracking with device fingerprinting
- **Audit Logging**: Comprehensive audit trails for all system operations
- **Device Trust Management**: Trusted device registration and management

### 🚀 **Distribution & Transfer**

- **Inter-facility Transfers**: Blood transfer workflows between facilities
- **Request Management**: Blood request handling and approval workflows
- **Distribution Tracking**: Complete chain of custody tracking
- **Automated Notifications**: Real-time alerts for requests and transfers

### 📱 **API Features**

- **RESTful API**: Fully documented REST API with OpenAPI/Swagger
- **Async Operations**: High-performance async request handling
- **Background Tasks**: Scheduled operations for maintenance and notifications
- **Rate Limiting**: API rate limiting and performance optimization
- **Comprehensive Testing**: Full test suite with pytest

## 🛠️ Technology Stack

### **Backend**

- **Framework**: FastAPI 0.115.12 (Python async web framework)
- **Database**: PostgreSQL 17 with SQLAlchemy 2.x ORM
- **Authentication**: JWT tokens with Argon2 password hashing
- **Task Scheduling**: APScheduler for background tasks
- **Admin Interface**: SQLAdmin for administrative operations

### **Development & DevOps**

- **Containerization**: Docker & Docker Compose
- **Database Migrations**: Alembic for schema management
- **Testing**: Pytest with async support and comprehensive test coverage
- **Code Quality**: Type hints, Pydantic for data validation
- **Logging**: Structured logging with performance monitoring

### **Security**

- **Password Hashing**: Argon2 CFI for secure password storage
- **CORS**: Configurable cross-origin resource sharing
- **Input Validation**: Pydantic models for request/response validation
- **SQL Injection Protection**: SQLAlchemy ORM with parameterized queries

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose (recommended)
- PostgreSQL 17 (if running without Docker)

### Option 1: Docker Compose (Recommended)

```bash
# Clone the repository
git clone https://github.com/timothysaatum/donorcom.git
cd donorcom

# Create environment file
cp .env.example .env
# Edit .env with your configuration

# Start the application
docker-compose up -d

# The API will be available at http://localhost:8000
# API Documentation at http://localhost:8000/docs
# Admin Interface at http://localhost:8000/admin
```

### Option 2: Local Development

```bash
# Clone and setup
git clone https://github.com/timothysaatum/donorcom.git
cd donorcom

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Setup database
alembic upgrade head
# Run the application
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Seed initial data (optional)
python db_fixtures.py

```

## 📁 Project Structure

```
donorcom/
├── app/
│   ├── admin/              # SQLAdmin configuration
│   ├── models/             # SQLAlchemy models
│   ├── routes/             # API route handlers
│   ├── schemas/            # Pydantic schemas
│   ├── services/           # Business logic layer
│   ├── utils/              # Utility functions
│   ├── middlewares/        # Custom middleware
│   ├── tasks/              # Background tasks
│   ├── config.py           # Application configuration
│   ├── database.py         # Database setup
│   └── main.py             # FastAPI application
├── alembic/                # Database migrations
├── tests/                  # Test suite
├── docker-compose.yml      # Docker configuration
├── Dockerfile              # Container definition
├── requirements.txt        # Python dependencies
└── README.md              # This file
```

## 🔧 Configuration

### Environment Variables

Create a `.env` file with the following configuration:

```env
# Application
PROJECT_NAME="DonorCom API"
PROJECT_DESCRIPTION="Blood Bank Management System"
VERSION="1.0.0"
ENVIRONMENT="development"
DEBUG=true

# Database
DATABASE_URL="postgresql+asyncpg://username:password@localhost:5432/donorcom"

# Security
SECRET_KEY="your-secret-key-here"
ALGORITHM="HS256"
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# Account Security
MAX_LOGIN_ATTEMPTS=5
ACCOUNT_LOCKOUT_DURATION_MINUTES=15

# Email (if configured)
SMTP_SERVER="smtp.gmail.com"
SMTP_PORT=587
SMTP_USERNAME="your-email@gmail.com"
SMTP_PASSWORD="your-app-password"
```

### Database Setup

```bash
# Run migrations
alembic upgrade head

# Seed initial data (creates roles, permissions, test users)
python db_fixtures.py
```

## 📚 API Documentation

### Interactive Documentation

- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`
- **OpenAPI Schema**: `http://localhost:8000/openapi.json`

### Key API Endpoints

#### Authentication

```
POST /api/users/auth/login          # User login
GET  /api/users/auth/refresh        # Refresh token
POST /api/users/auth/logout         # User logout
```

#### Blood Inventory

```
GET    /api/inventory               # List blood inventory
POST   /api/inventory               # Create blood unit
GET    /api/inventory/{id}          # Get specific blood unit
PUT    /api/inventory/{id}          # Update blood unit
DELETE /api/inventory/{id}          # Delete blood unit
POST   /api/inventory/batch         # Batch operations
GET    /api/inventory/statistics    # Inventory statistics
```

#### Facilities

```
GET    /api/facilities              # List facilities
POST   /api/facilities              # Create facility
GET    /api/facilities/{id}         # Get specific facility
PUT    /api/facilities/{id}         # Update facility
```

#### Blood Banks

```
GET    /api/blood-banks             # List blood banks
POST   /api/blood-banks             # Create blood bank
GET    /api/blood-banks/{id}        # Get specific blood bank
```

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app

# Run specific test categories
pytest tests/test_inventory_comprehensive.py
pytest tests/test_end_to_end_integration.py

# Run performance tests
pytest tests/test_performance.py -v
```

### Test Categories

- **Unit Tests**: Individual component testing
- **Integration Tests**: API endpoint testing
- **End-to-End Tests**: Complete workflow testing
- **Performance Tests**: Load and response time testing
- **Security Tests**: Authentication and authorization testing

## 🏗️ Development

### Setting up Development Environment

```bash
# Install development dependencies
pip install -r requirements.txt
pip install pytest pytest-asyncio httpx

# Install pre-commit hooks (optional)
pre-commit install

# Run code formatting
black app/
isort app/

# Type checking
mypy app/
```

### Database Migrations

```bash
# Create new migration
alembic revision --autogenerate -m "Description of changes"

# Apply migrations
alembic upgrade head

# Rollback migrations
alembic downgrade -1
```

### Adding New Features

1. **Models**: Add SQLAlchemy models in `app/models/`
2. **Schemas**: Define Pydantic schemas in `app/schemas/`
3. **Services**: Implement business logic in `app/services/`
4. **Routes**: Create API endpoints in `app/routes/`
5. **Tests**: Add comprehensive tests in `tests/`

## 🔒 Security Features

### Authentication & Authorization

- **JWT Tokens**: Secure stateless authentication
- **Role-Based Access**: Fine-grained permission system
- **Account Security**: Lockout protection, failed attempt tracking
- **Session Management**: Device tracking and session control

### Data Protection

- **Password Security**: Argon2 hashing algorithm
- **Input Validation**: Comprehensive data validation
- **SQL Injection Protection**: Parameterized queries
- **CORS Configuration**: Secure cross-origin requests

### Audit & Monitoring

- **Audit Logs**: Complete action tracking
- **Security Events**: Failed login monitoring
- **Performance Metrics**: Response time tracking
- **Error Monitoring**: Comprehensive error logging

## 📈 Performance

### Optimization Features

- **Async Operations**: Non-blocking I/O operations
- **Database Indexing**: Optimized query performance
- **Connection Pooling**: Efficient database connections
- **Background Tasks**: Non-blocking background operations
- **Caching**: Strategic caching implementation

### Monitoring

- **Response Time Tracking**: Built-in performance monitoring
- **Database Query Optimization**: Efficient query patterns
- **Memory Management**: Optimized resource usage

## 🚀 Deployment

### Production Deployment

```bash
# Using Docker Compose (Production)
docker-compose -f docker-compose.prod.yml up -d

# Environment variables for production
ENVIRONMENT=production
DEBUG=false
# ... other production settings
```

### AWS Lambda Deployment

The application includes Mangum for AWS Lambda deployment:

```python
# lambda_handler.py included for serverless deployment
from mangum import Mangum
from app.main import app

handler = Mangum(app)
```

## 🤝 Contributing

1. **Fork** the repository
2. **Create** a feature branch (`git checkout -b feature/AmazingFeature`)
3. **Commit** your changes (`git commit -m 'Add some AmazingFeature'`)
4. **Push** to the branch (`git push origin feature/AmazingFeature`)
5. **Open** a Pull Request

### Development Guidelines

- Follow PEP 8 style guidelines
- Add comprehensive tests for new features
- Update documentation for API changes
- Use type hints for all functions
- Write descriptive commit messages

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 👥 Support

### Getting Help

- **Documentation**: Check the API docs at `/docs`
- **Issues**: Report bugs via GitHub Issues
- **Discussions**: Use GitHub Discussions for questions

### Maintenance

This project is actively maintained. Security updates and feature improvements are regularly released.

## 🙏 Acknowledgments

- **FastAPI**: For the excellent async web framework
- **SQLAlchemy**: For the powerful ORM
- **PostgreSQL**: For reliable data storage
- **All Contributors**: Thank you for your contributions!

---

**Built with ❤️ for healthcare and life-saving blood distribution**

> 🩸 Every line of code here contributes to saving lives through efficient blood management.
