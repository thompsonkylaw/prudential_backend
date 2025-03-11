# Use a valid base image (make sure to use one that exists, e.g., cypress/included or a proper cypress/browser tag)
ARG PORT=443
FROM cypress/browser:latest

# Install python3 (fixing the install command)
RUN apt-get update && apt-get install -y python3

# Add missing Google Chrome public key
RUN curl -sSL https://dl.google.com/linux/linux_signing_key.pub | apt-key add -

# Remove duplicate Microsoft Edge repository file if not needed
RUN rm -f /etc/apt/sources.list.d/microsoft-edge.list

# Continue with updating and installing pip and requirements
RUN apt-get update && apt-get install -y python3-pip && pip3 install -r requirements.txt

# Copy source files
COPY . .

# Run uvicorn (note the correct spelling)
CMD uvicorn main:app --host 0.0.0.0 --port $PORT
