ARG PORT=443

FROM cypress/browsers:latest

# Install Python3, Pip3, and dependencies in one layer
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    build-essential \
    libssl-dev \
    libffi-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Create a virtual environment
RUN python3 -m venv /opt/venv

# Activate the virtual environment by updating PATH
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements.txt to the container
COPY requirements.txt .

# Install Python dependencies in the virtual environment
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Run the application with Uvicorn
CMD uvicorn main:app --host 0.0.0.0 --port $PORT