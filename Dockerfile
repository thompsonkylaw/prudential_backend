ARG PORT=443

# Use official Cypress image with Chrome
FROM cypress/included:12.17.4

# Install Python and pip
RUN apt-get update && \
    apt-get install -y python3 curl && \
    curl -sSL https://bootstrap.pypa.io/get-pip.py -o get-pip.py && \
    python3 get-pip.py && \
    rm get-pip.py && \
    rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Configure environment
ENV PATH="/home/node/.local/bin:${PATH}"

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "${PORT}"]