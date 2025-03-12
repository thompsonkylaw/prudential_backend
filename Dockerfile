ARG PORT=443

FROM cypress/browsers:latest

# Install Python3, Pip3, and common build dependencies in one layer
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    build-essential \
    libssl-dev \
    libffi-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Optional: Echo the Python user base directory
RUN echo $(python3 -m site --user-base)

# Copy requirements.txt to the container
COPY requirements.txt .

# Set PATH environment variable (may be optional depending on requirements)
ENV PATH /home/root/.local/bin:${PATH}

# Install Python dependencies
RUN pip3 install -r requirements.txt

# Copy application code
COPY . .

# Run the application with Uvicorn
CMD uvicorn main:app --host 0.0.0.0 --port $PORT