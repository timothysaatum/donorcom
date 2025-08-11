# Use a lightweight Python image
FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable output flushing
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Install system dependencies for PostgreSQL drivers
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code into container
COPY . .

# Expose port for Cloud Run
EXPOSE 8080

# Run FastAPI app (app is in app/main.py, variable is app)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
