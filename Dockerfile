ARG PORT=443

FROM cypress/browsers:latest

# Install system dependencies in a single RUN command
RUN apt-get update && \
    apt-get install -y \
    python3 \
    python3-pip \
    python3-dev \
    build-essential && \
    rm -rf /var/lib/apt/lists/*

# Set correct user-level binary path
ENV PATH /root/.local/bin:${PATH}

COPY requirements.txt .

# Install Python dependencies
RUN pip3 install --no-cache-dir -r requirements.txt

COPY . .

CMD uvicorn main:app --host 0.0.0.0 --port $PORT