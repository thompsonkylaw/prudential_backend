ARG PORT=443

# Use a valid base image (chrome is the default)
FROM cypress/browser:latest

# Install system dependencies
RUN apt-get update && \
    apt-get install -y python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Set environment variables
ENV PATH /home/root/.local/bin:${PATH}

# Expose and run the application
EXPOSE $PORT
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "${PORT}"]