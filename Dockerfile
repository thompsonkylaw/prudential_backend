# Use Python 3.13 base image
FROM python:3.13

WORKDIR /app

COPY . /app

RUN pip install --trusted-host pypi.python.org -r requirements.txt

RUN apt-get update && apt-get install -y wget unzip && \
    wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && \
    apt install -y ./google-chrome-stable_current_amd64.deb && \
    rm google-chrome-stable_current_amd64.deb && \
    apt-get clean

# Railway configuration
ENV PORT=8000
EXPOSE $PORT

# Start command (use uvicorn directly)
# CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "${PORT}"]
CMD hypercorn main:app --bind "[::]:$PORT"
