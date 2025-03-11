ARG PORT=443
FROM cypress/included:12.9.0

# Fix GPG key issue for Google Chrome
RUN apt-get update && apt-get install -y wget && \
    wget -q -O /etc/apt/trusted.gpg.d/google-linux-signing-key.gpg https://dl.google.com/linux/linux_signing_key.pub

# Remove duplicate Microsoft Edge repository
RUN rm -f /etc/apt/sources.list.d/microsoft-edge.list

# Install Python and dependencies
RUN apt-get update && apt-get install -y python3 python3-pip

# Set up Python environment
ENV PATH="/root/.local/bin:${PATH}"

# Copy and install requirements
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "$PORT"]