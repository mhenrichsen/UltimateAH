# The server scan as a small always-on service: scans every Forever auction house when Blizzard has
# new data (once an hour) and hands out the data files on port 8080. Put HTTPS in front of it.
#
#   docker build -t ultimate-ah-scan .
#   docker run -d -p 8080:8080 -v ah-data:/data \
#       -e BLIZZARD_CLIENT_ID=... -e BLIZZARD_CLIENT_SECRET=... ultimate-ah-scan
#
# /data holds the database and the previous snapshots: keep it on a volume.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY ah_api.py ah_server.py ./

RUN useradd --system --uid 10001 scan && mkdir /data && chown scan /data
USER scan
VOLUME /data
EXPOSE 8080

HEALTHCHECK --interval=60s --timeout=10s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=5)"

CMD ["python", "ah_server.py", "serve", "--dir", "/data", "--port", "8080"]
