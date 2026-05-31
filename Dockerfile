FROM python:3.11-slim

WORKDIR /srv

# System deps for PyMySQL
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# SQLite data volume
VOLUME /data

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD curl -f http://localhost:5000/ || exit 1

ENTRYPOINT ["/entrypoint.sh"]
