# Use Python 3.12 base for stability
FROM python:3.12-slim-bookworm

# Install system dependencies
RUN apt-get update && apt-get install -y \
    wget \
    unzip \
    gnupg \
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

# Install Chrome
RUN wget -q https://dl.google.com/linux/chrome/deb/pool/main/g/google-chrome-stable/google-chrome-stable_124.0.6367.91-1_amd64.deb \
    && apt-get install -y ./google-chrome-stable_124.0.6367.91-1_amd64.deb \
    && rm google-chrome-stable_124.0.6367.91-1_amd64.deb

# Install matching ChromeDriver
RUN CHROME_DRIVER_VERSION=124.0.6367.91 \
    && wget -q https://chromedriver.storage.googleapis.com/$CHROME_DRIVER_VERSION/chromedriver_linux64.zip \
    && unzip chromedriver_linux64.zip \
    && mv chromedriver /usr/bin/chromedriver \
    && chmod +x /usr/bin/chromedriver \
    && rm chromedriver_linux64.zip

# Configure Python environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
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

# Start command
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "${PORT}"]