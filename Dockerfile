# The server scan as a small always-on service: scans every Forever auction house when Blizzard has
# new data (once an hour), learns its price forecasts from the history after every scan, and hands
# out the data files on port 8080. Put HTTPS in front of it.
#
#   docker build -t ultimate-ah-scan .
#   docker run -d -p 8080:8080 -v ah-data:/data \
#       -e BLIZZARD_CLIENT_ID=... -e BLIZZARD_CLIENT_SECRET=... ultimate-ah-scan
#
# /data holds the database and the previous snapshots: keep it on a volume.
FROM python:3.12-slim

# one thread for the training: more only helps when the container may use more than one CPU
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1
WORKDIR /app
# for the learned forecasts (ah_ml.py); the scan itself needs nothing but Python
RUN pip install --no-cache-dir "numpy>=2,<3" "scikit-learn>=1.5,<2"
COPY ah_api.py ah_server.py ah_ml.py ./

RUN useradd --system --uid 10001 scan && mkdir /data && chown scan /data
USER scan
VOLUME /data
EXPOSE 8080

HEALTHCHECK --interval=60s --timeout=10s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=5)"

CMD ["python", "ah_server.py", "serve", "--dir", "/data", "--port", "8080"]
