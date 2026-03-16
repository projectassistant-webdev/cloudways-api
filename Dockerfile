FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    mariadb-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt

COPY . .
RUN pip install -e .

ENTRYPOINT ["cloudways"]
