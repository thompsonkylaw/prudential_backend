# Base image - Python 3.11 slim version
FROM python:3.11-slim

# ===== SYSTEM DEPENDENCIES =====
# Install required system packages
# RUN apt-get update && apt-get install -y \
#     wget \          # For downloading files
    # unzip \         # For unzipping ChromeDriver
    # gnupg \         # For package verification
    # libnss3 \       # Chrome dependency
    # libgconf-2-4 \  # GUI library
    # libfontconfig1 \# Font handling
    # xvfb \          # Virtual framebuffer
    # gconf-service \ # GNOME config service
    # ca-certificates \# SSL certificates
    # fonts-liberation \# Fonts
    # libasound2 \    # Sound system
    # libatk-bridge2.0-0 \# Accessibility toolkit
    # libnspr4 \      # Netscape Portable Runtime
    # libxcomposite1 \# X Window System
    # libxkbcommon0 \ # Keyboard handling
    # libxrandr2      # X Resize and Rotate

# ===== CHROME INSTALLATION =====
# Add Google Chrome repository
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list

# Install Chrome
RUN apt-get update \
    && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# ===== CHROMEDRIVER INSTALLATION =====
# Get latest ChromeDriver version
RUN CHROME_DRIVER_VERSION=$(curl -sS https://chromedriver.storage.googleapis.com/LATEST_RELEASE) \
    && wget -N https://chromedriver.storage.googleapis.com/$CHROME_DRIVER_VERSION/chromedriver_linux64.zip \
    && unzip chromedriver_linux64.zip \
    && chmod +x chromedriver \
    && mv chromedriver /usr/local/bin/

# ===== APPLICATION SETUP =====
# Set working directory
WORKDIR /app

# Copy requirements first for layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Command to run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]