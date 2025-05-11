FROM python:3.9-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install playwright and its dependencies
RUN pip install playwright
RUN playwright install chromium
RUN playwright install-deps

# Copy the application code
COPY app/ ./app/

# Create directories for reports
RUN mkdir -p reports/data reports/pdf

# Expose the port the app runs on
EXPOSE 8000

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]