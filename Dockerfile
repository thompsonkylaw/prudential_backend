ARG PORT=443

FROM cypress/browser:14.2.0

RUN apt-get update && \
    apt-get install -y python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PATH /home/root/.local/bin:${PATH}

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "${PORT}"]