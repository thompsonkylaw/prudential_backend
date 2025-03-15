# Use Python 3.13 base image
FROM python:3.13-rc-slim-bookworm

# Install system dependencies
RUN apt-get update && apt-get install -y \
    wget \
    unzip \
    fonts-liberation \
    libgl1 \
    libx11-6 \
    libxcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxi6 \
    libxrandr2 \
    libxrender1 \
    libxss1 \
    libxtst6 \
    --no-install-recommends



# Configure Python environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PYTHONPYCACHEPREFIX=/tmp/pycache \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Railway configuration
ENV PORT=8000
EXPOSE $PORT

# Start command (use uvicorn directly)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "${PORT}"]